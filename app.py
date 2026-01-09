
# -*- coding: utf-8 -*-
"""
App de Registro de Ponto (compacto) — Streamlit + GitHub (JSON).
Janela pensada para ~360px de largura (pequena).
"""
from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, date
from typing import Optional, Tuple, List

import requests
import pandas as pd
import streamlit as st
from zoneinfo import ZoneInfo

# ---------------------- Página & Estilo compacto ----------------------
st.set_page_config(page_title="Ponto", page_icon="🕒", layout="centered")

# CSS para compactar componentes
COMPACT_CSS = """
<style>
/* reduzir largura máxima do container */
div.block-container { max-width: 360px; padding-top: 0.5rem; }

/* fonte geral levemente menor */
html, body, [class*="css"] { font-size: 14px; }

/* cabeçalhos mais enxutos */
h1, h2, h3 { margin: 0.2rem 0 !important; }

/* inputs e botões compactos */
.stButton>button { padding: 0.25rem 0.6rem; font-size: 0.9rem; }
.stDownloadButton>button { padding: 0.25rem 0.5rem; font-size: 0.85rem; }

/* reduzir espaço vertical entre elementos */
.css-1v3fvcr, .css-5rimss, .stMarkdown { margin-bottom: 0.5rem !important; }

/* tabela/dataframe mais compacta */
.stTable, .stDataFrame { font-size: 13px; }
</style>
"""
st.markdown(COMPACT_CSS, unsafe_allow_html=True)

# ---------------------- Defaults / Config ----------------------
DEFAULT_OWNER   = "meggavenda-dev"
DEFAULT_REPO    = "registro-ponto-db"
DEFAULT_PATH    = "pontos.json"
DEFAULT_BRANCH  = "main"
DEFAULT_TZ_NAME = "America/Sao_Paulo"

def cfg(key: str, default: str = "") -> str:
    if key in st.secrets:
        val = st.secrets.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    v = os.getenv(key)
    if v and v.strip():
        return v.strip()
    return default

GITHUB_OWNER  = cfg("GITHUB_OWNER",  DEFAULT_OWNER)
GITHUB_REPO   = cfg("GITHUB_REPO",   DEFAULT_REPO)
GITHUB_PATH   = cfg("GITHUB_PATH",   DEFAULT_PATH)
GITHUB_BRANCH = cfg("GITHUB_BRANCH", DEFAULT_BRANCH)
TIMEZONE_NAME = cfg("TIMEZONE",      DEFAULT_TZ_NAME)
GITHUB_TOKEN  = cfg("GITHUB_TOKEN",  "")  # obrigatório

if not GITHUB_TOKEN:
    st.error("Defina o **GITHUB_TOKEN** em Settings → Secrets (Streamlit Cloud).")
    st.stop()

# ---------------------- Utilitários ----------------------
def get_tz(name: str | None) -> ZoneInfo:
    return ZoneInfo(name or DEFAULT_TZ_NAME)

TZ = get_tz(TIMEZONE_NAME)

def now_local(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)

# ---------------------- Modelo ----------------------
@dataclass
class RegistroPonto:
    id: str
    usuario: str
    date: str   # YYYY-MM-DD
    time: str   # HH:MM:SS
    label: str  # "Automático" | "Manual"
    tag: str    # "Entrada" | "Saída" | "Intervalo" | "Retorno" | "Outro"
    obs: Optional[str]
    created_at: str  # ISO8601

    @staticmethod
    def novo(usuario: str, dt: datetime, label: str, tag: str, obs: Optional[str]) -> 'RegistroPonto':
        return RegistroPonto(
            id=str(uuid.uuid4()),
            usuario=usuario,
            date=dt.date().isoformat(),
            time=dt.strftime("%H:%M:%S"),
            label=label,
            tag=tag,
            obs=(obs or ""),
            created_at=dt.isoformat(),
        )

    def to_dict(self) -> dict:
        return asdict(self)

# ---------------------- Acesso GitHub ----------------------
class GithubJSONStore:
    def __init__(self, owner: str, repo: str, token: str, branch: str = "main") -> None:
        self.owner = owner
        self.repo = repo
        self.token = token
        self.branch = branch
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _contents_url(self, path: str) -> str:
        return f"https://api.github.com/repos/{self.owner}/{self.repo}/contents/{path}"

    def load(self, path: str) -> Tuple[List[dict], Optional[str]]:
        url = self._contents_url(path)
        r = requests.get(url, headers=self._headers, params={"ref": self.branch})
        if r.status_code == 200:
            payload = r.json()
            content_b64 = payload.get("content", "")
            sha = payload.get("sha")
            try:
                content = base64.b64decode(content_b64).decode("utf-8")
                data = json.loads(content)
            except Exception:
                data = []
            return data, sha
        elif r.status_code == 404:
            empty_content = base64.b64encode("[]".encode("utf-8")).decode("utf-8")
            payload = {
                "message": "Inicializa banco de pontos (arquivo JSON)",
                "content": empty_content,
                "branch": self.branch,
            }
            cr = requests.put(url, headers=self._headers, json=payload)
            if cr.status_code in (200, 201):
                sha = cr.json().get("content", {}).get("sha")
                return [], sha
            raise RuntimeError(f"Erro ao criar arquivo no GitHub: {cr.status_code} {cr.text}")
        else:
            raise RuntimeError(f"Erro ao carregar arquivo: {r.status_code} {r.text}")

    def commit(self, path: str, data: List[dict], sha: Optional[str], message: str) -> Optional[str]:
        url = self._contents_url(path)
        content_str = json.dumps(data, ensure_ascii=False, indent=2)
        content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
        payload = {
            "message": message,
            "content": content_b64,
            "branch": self.branch,
        }
        if sha:
            payload["sha"] = sha
        r = requests.put(url, headers=self._headers, json=payload)
        if r.status_code in (200, 201):
            return r.json().get("content", {}).get("sha")
        if r.status_code == 409:
            return None
        raise RuntimeError(f"Erro ao gravar no GitHub: {r.status_code} {r.text}")

    def append_with_retry(self, path: str, record: dict, max_retries: int = 3, sleep_seconds: float = 0.8) -> bool:
        import time as _time
        for _ in range(max_retries):
            data, sha = self.load(path)
            data.append(record)
            new_sha = self.commit(
                path, data, sha,
                message=f"Ponto {record.get('usuario','?')} {record.get('date','')} {record.get('time','')}"
            )
            if new_sha:
                return True
            _time.sleep(sleep_seconds)
        return False

store = GithubJSONStore(
    owner=GITHUB_OWNER,
    repo=GITHUB_REPO,
    token=GITHUB_TOKEN,
    branch=GITHUB_BRANCH,
)

# ---------------------- Carregar dados ----------------------
try:
    data, current_sha = store.load(GITHUB_PATH)
except Exception as e:
    st.error(f"Falha ao carregar dados do GitHub: {e}")
    st.stop()

# ---------------------- UI Compacta ----------------------
st.title("🕒 Ponto")

# Usuário com valor default curto
default_user = os.getenv("USERNAME") or os.getenv("USER") or "usuario"
usuario = st.text_input("Usuário", value=st.session_state.get("usuario", default_user))
st.session_state["usuario"] = usuario

aba_hoje, aba_hist = st.tabs(["Hoje", "Histórico"])

with aba_hoje:
    # Linha compacta de inputs
    c1, c2, c3 = st.columns([1.1, 1.1, 1.2])
    with c1:
        dia = st.date_input("Dia", value=date.today(), label_visibility="collapsed")
        st.caption("Dia")
    with c2:
        hora_selecionada = st.time_input("Hora", value=now_local(TZ).time().replace(microsecond=0), label_visibility="collapsed")
        st.caption("Hora")
    with c3:
        rotulo = st.selectbox("Rótulo", ["Entrada", "Saída", "Intervalo", "Retorno", "Outro"], index=0, label_visibility="collapsed")
        st.caption("Rótulo")

    with st.expander("Observação (opcional)", expanded=False):
        observacao = st.text_input("Observação", value="", placeholder="Digite algo breve...")

    b1, b2 = st.columns([1, 1])
    with b1:
        if st.button("Agora", type="primary"):
            dt = now_local(TZ)
            rec = RegistroPonto.novo(usuario, dt, label="Automático", tag=rotulo, obs=observacao)
            ok = store.append_with_retry(GITHUB_PATH, rec.to_dict())
            if ok:
                st.success("Registrado.")
                data, current_sha = store.load(GITHUB_PATH)
            else:
                st.error("Falha ao gravar.")
    with b2:
        if st.button("Salvar"):
            dt = datetime.combine(dia, hora_selecionada).replace(tzinfo=TZ)
            rec = RegistroPonto.novo(usuario, dt, label="Manual", tag=rotulo, obs=observacao)
            ok = store.append_with_retry(GITHUB_PATH, rec.to_dict())
            if ok:
                st.success("Salvo.")
                data, current_sha = store.load(GITHUB_PATH)
            else:
                st.error("Falha ao gravar.")

    st.markdown("---")
    st.subheader("Hoje")
    dia_str = dia.isoformat()
    registros_dia = [r for r in data if r.get("date") == dia_str and r.get("usuario") == usuario]

    # Ordenação compacta
    def _key_time(r: dict) -> str:
        t = r.get("time", "00:00:00")
        return t if isinstance(t, str) else "00:00:00"
    registros_dia.sort(key=_key_time)

    if registros_dia:
        # Exibir com altura limitada
        df_dia = pd.DataFrame(registros_dia)
        st.dataframe(df_dia, height=180, use_container_width=True)
    else:
        st.info("Sem pontos hoje.")

with aba_hist:
    st.subheader("Histórico")
    hf1, hf2 = st.columns([1, 1])
    with hf1:
        usuario_f = st.text_input("Usuário (filtro)", value=usuario)
    with hf2:
        periodo = st.date_input("Período", value=(date.today().replace(day=1), date.today()))

    if isinstance(periodo, tuple) and len(periodo) == 2:
        dt_ini, dt_fim = periodo
    else:
        dt_ini, dt_fim = date.today().replace(day=1), date.today()

    def in_period(r: dict) -> bool:
        try:
            d = datetime.strptime(r.get("date"), "%Y-%m-%d").date()
            return dt_ini <= d <= dt_fim
        except Exception:
            return True

    filtrados = [r for r in data if in_period(r) and (not usuario_f or r.get("usuario") == usuario_f)]

    if filtrados:
        df = pd.DataFrame(filtrados)
        st.dataframe(df, height=220, use_container_width=True)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("CSV", data=csv, file_name="pontos.csv", mime="text/csv")
    else:
        st.info("Sem registros no período.")

st.caption(f"DB: {GITHUB_OWNER}/{GITHUB_REPO} · {GITHUB_PATH} ({GITHUB_BRANCH}) · TZ: {TIMEZONE_NAME}")
