
# -*- coding: utf-8 -*-
"""
App de Registro de Ponto (compacto) — Streamlit + GitHub (JSON via REST /contents).
- Usuário fixo: "Guilherme Henrique Cavalcante" (exibido, desabilitado).
- ID decimal (inteiro) único por registro.
- Permite registrar horário passado (ex.: agora 09:04 e salvar 08:09).
- Bloqueio de horário futuro opcional (ALLOW_FUTURE=false por padrão).
- UI compacta para janelas pequenas.
- Correção: botões de ajuste usam on_click (sem st.rerun), evitando StreamlitAPIException.
- Exibição:
  • HOJE → somente Rótulo, Dia, Hora
  • HISTÓRICO → somente Dia, Rótulo, Hora

Config (ordem de prioridade): st.secrets → variáveis de ambiente → defaults.
Necessário: GITHUB_TOKEN (PAT) com escopo 'repo'.

Secrets recomendados (Streamlit Cloud → Settings → Secrets):
GITHUB_OWNER  = "meggavenda-dev"
GITHUB_REPO   = "registro-ponto-db"
GITHUB_PATH   = "pontos.json"
GITHUB_BRANCH = "main"
GITHUB_TOKEN  = "ghp_SEU_TOKEN_AQUI"
TIMEZONE      = "America/Sao_Paulo"
ALLOW_FUTURE  = "false"        # ou "true" para permitir horário futuro
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, date, timedelta, time as dtime
from typing import Optional, Tuple, List, Set

import requests
import pandas as pd
import streamlit as st
from zoneinfo import ZoneInfo

# ---------------------- Página & Estilo compacto ----------------------
st.set_page_config(page_title="Ponto", page_icon="🕒", layout="centered")

COMPACT_CSS = """
<style>
div.block-container { max-width: 360px; padding-top: 0.5rem; }
html, body, [class*="css"] { font-size: 14px; }
h1, h2, h3 { margin: 0.2rem 0 !important; }
.stButton>button { padding: 0.25rem 0.6rem; font-size: 0.9rem; }
.stDownloadButton>button { padding: 0.25rem 0.5rem; font-size: 0.85rem; }
.css-1v3fvcr, .css-5rimss, .stMarkdown { margin-bottom: 0.5rem !important; }
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
DEFAULT_ALLOW_FUTURE = "false"

# Usuário fixo (pedido)
USER_FIXED = "Guilherme Henrique Cavalcante"

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
ALLOW_FUTURE  = cfg("ALLOW_FUTURE",  DEFAULT_ALLOW_FUTURE).lower() in ("1", "true", "yes", "y")

if not GITHUB_TOKEN:
    st.error(
        "Falta o **GITHUB_TOKEN (PAT)** para gravar no GitHub.\n\n"
        "No Streamlit Cloud, vá em *Settings → Secrets* e cole:\n\n"
        "```\n"
        f"GITHUB_OWNER  = \"{DEFAULT_OWNER}\"\n"
        f"GITHUB_REPO   = \"{DEFAULT_REPO}\"\n"
        f"GITHUB_PATH   = \"{DEFAULT_PATH}\"\n"
        f"GITHUB_BRANCH = \"{DEFAULT_BRANCH}\"\n"
        "GITHUB_TOKEN  = \"ghp_SEU_TOKEN_AQUI\"\n"
        f"TIMEZONE      = \"{DEFAULT_TZ_NAME}\"\n"
        "ALLOW_FUTURE  = \"false\"\n"
        "```"
    )
    st.stop()

# ---------------------- Utilitários ----------------------
def get_tz(name: str | None) -> ZoneInfo:
    return ZoneInfo(name or DEFAULT_TZ_NAME)

TZ = get_tz(TIMEZONE_NAME)

def now_local(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)

def existing_ids_int(records: List[dict]) -> Set[int]:
    s: Set[int] = set()
    for r in records:
        try:
            s.add(int(r.get("id")))
        except Exception:
            pass
    return s

def generate_decimal_id(existing: Set[int]) -> int:
    """Gera ID inteiro baseado em timestamp (ms) e garante unicidade."""
    base = int(now_local(TZ).timestamp() * 1000)
    while base in existing:
        base += 1
    return base

# ---------------------- Modelo ----------------------
@dataclass
class RegistroPonto:
    id: int            # ID decimal (inteiro)
    usuario: str
    date: str          # YYYY-MM-DD
    time: str          # HH:MM:SS
    label: str         # "Automático" | "Manual"
    tag: str           # "Entrada" | "Saída" | "Intervalo" | "Retorno" | "Outro"
    obs: Optional[str]
    created_at: str    # ISO8601

    @staticmethod
    def novo(id_int: int, usuario: str, dt: datetime, label: str, tag: str, obs: Optional[str]) -> 'RegistroPonto':
        return RegistroPonto(
            id=id_int,
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
            return None  # conflito (alguém gravou antes)
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

# ---------------------- Inicialização de estado ----------------------
def _init_session_defaults():
    # Usuário sempre fixo
    st.session_state["usuario"] = USER_FIXED
    if "dia_sel" not in st.session_state:
        st.session_state["dia_sel"] = date.today()
    if "hora_sel" not in st.session_state:
        st.session_state["hora_sel"] = now_local(TZ).time().replace(microsecond=0)

_init_session_defaults()

# ---------------------- Carregar dados ----------------------
try:
    data, current_sha = store.load(GITHUB_PATH)
except Exception as e:
    st.error(f"Falha ao carregar dados do GitHub: {e}")
    st.stop()

# ---------------------- Callbacks para ajuste de hora/dia ----------------------
def shift_minutes(delta_min: int):
    """Callback chamado pelos botões de ajuste (-5/-10/-15/Agora). Sem st.rerun()."""
    dia_atual: date = st.session_state["dia_sel"]
    hora_atual: dtime = st.session_state["hora_sel"]
    base_dt = datetime.combine(dia_atual, hora_atual).replace(tzinfo=TZ)
    novo_dt = base_dt + timedelta(minutes=delta_min)
    st.session_state["dia_sel"] = novo_dt.date()
    st.session_state["hora_sel"] = novo_dt.time().replace(microsecond=0)

def set_now():
    """Callback para botão 'Agora' (ajusta dia/hora)."""
    st.session_state["dia_sel"] = date.today()
    st.session_state["hora_sel"] = now_local(TZ).time().replace(microsecond=0)

# ---------------------- UI ----------------------
st.title("🕒 Ponto")

# Campo de usuário (fixo, desabilitado)
st.text_input("Usuário", key="usuario", disabled=True)

aba_hoje, aba_hist = st.tabs(["Hoje", "Histórico"])

with aba_hoje:
    # Widgets com key sem value (usa somente session_state)
    c1, c2, c3 = st.columns([1.1, 1.1, 1.2])
    with c1:
        st.date_input("Dia", key="dia_sel", label_visibility="collapsed")
        st.caption("Dia")
    with c2:
        st.time_input("Hora", key="hora_sel", label_visibility="collapsed")
        st.caption("Hora")
    with c3:
        rotulo = st.selectbox("Rótulo", ["Entrada", "Saída", "Intervalo", "Retorno", "Outro"], index=0, label_visibility="collapsed")
        st.caption("Rótulo")

    # Observação e botões de ajuste rápido (usando callbacks)
    with st.expander("Observação (opcional)", expanded=False):
        observacao = st.text_input("Observação", value="", placeholder="Digite algo breve...")

    a1, a2, a3, a4 = st.columns(4)
    a1.button("-5",  use_container_width=True, on_click=shift_minutes, args=(-5,))
    a2.button("-10", use_container_width=True, on_click=shift_minutes, args=(-10,))
    a3.button("-15", use_container_width=True, on_click=shift_minutes, args=(-15,))
    a4.button("Agora", use_container_width=True, on_click=set_now)

    # Avaliar relação com 'agora'
    dt_sel = datetime.combine(st.session_state["dia_sel"], st.session_state["hora_sel"]).replace(tzinfo=TZ)
    agora = now_local(TZ)
    if dt_sel < agora:
        st.info(f"⏱️ Horário **passado**: {dt_sel.strftime('%H:%M:%S')} — registro retroativo permitido.")
    elif dt_sel == agora.replace(microsecond=0):
        st.info("✅ Horário **agora**.")
    else:
        if ALLOW_FUTURE:
            st.warning(f"⏳ Horário **no futuro**: {dt_sel.strftime('%H:%M:%S')} — será aceito.")
        else:
            st.warning(f"⏳ Horário **no futuro**: {dt_sel.strftime('%H:%M:%S')} — ajuste para passado/atual.")

    b1, b2 = st.columns([1, 1])
    with b1:
        if st.button("Agora", type="primary", use_container_width=True):
            dt = agora
            new_id = generate_decimal_id(existing_ids_int(data))  # recalcula por segurança
            rec = RegistroPonto.novo(new_id, st.session_state["usuario"], dt, label="Automático", tag=rotulo, obs=observacao)
            ok = store.append_with_retry(GITHUB_PATH, rec.to_dict())
            if ok:
                st.success("Registrado (agora).")
                data, current_sha = store.load(GITHUB_PATH)
            else:
                st.error("Falha ao gravar no GitHub.")
    with b2:
        if st.button("Salvar", use_container_width=True):  # manual (passado permitido; futuro depende do flag)
            if (not ALLOW_FUTURE) and (dt_sel > agora):
                st.error("Horário no futuro não permitido. Ajuste para passado/atual.")
            else:
                new_id = generate_decimal_id(existing_ids_int(data))
                rec = RegistroPonto.novo(new_id, st.session_state["usuario"], dt_sel, label="Manual", tag=rotulo, obs=observacao)
                ok = store.append_with_retry(GITHUB_PATH, rec.to_dict())
                if ok:
                    st.success("Horário manual salvo.")
                    data, current_sha = store.load(GITHUB_PATH)
                else:
                    st.error("Falha ao gravar no GitHub.")

    st.markdown("---")
    st.subheader("Hoje")
    dia_str = st.session_state["dia_sel"].isoformat()
    registros_dia = [r for r in data if r.get("date") == dia_str and r.get("usuario") == st.session_state["usuario"]]

    # Ordenação por hora e exibição compacta (só Rótulo, Dia e Hora)
    def _key_time(r: dict) -> str:
        t = r.get("time", "00:00:00")
        return t if isinstance(t, str) else "00:00:00"
    registros_dia.sort(key=_key_time)

    if registros_dia:
        df_dia = pd.DataFrame(registros_dia)
        cols = ["tag", "date", "time"]
        cols_existentes = [c for c in cols if c in df_dia.columns]
        df_view = df_dia[cols_existentes].rename(columns={
            "tag": "Rótulo",
            "date": "Dia",
            "time": "Hora",
        })
        # Ordena por Dia e Hora
        try:
            df_view = df_view.sort_values(by=["Dia", "Hora"])
        except Exception:
            pass
        st.dataframe(df_view, height=180, use_container_width=True)
    else:
        st.info("Sem pontos hoje.")

with aba_hist:
    st.subheader("Histórico")
    hf1, hf2 = st.columns([1, 1])
    with hf1:
        usuario_f = st.text_input("Usuário (filtro)", value=st.session_state["usuario"])
    with hf2:
        periodo = st.date_input("Período", value=(date.today().replace(day=1), date.today()))

    # Normaliza o período
    if isinstance(periodo, tuple) and len(periodo) == 2:
        dt_ini, dt_fim = periodo
    else:
        dt_ini, dt_fim = date.today().replace(day=1), date.today()

    # Filtro por período
    def in_period(r: dict) -> bool:
        try:
            d = datetime.strptime(r.get("date"), "%Y-%m-%d").date()
            return dt_ini <= d <= dt_fim
        except Exception:
            return False

    filtrados = [
        r for r in data
        if in_period(r) and (not usuario_f or r.get("usuario") == usuario_f)
    ]

    if filtrados:
        # Monta DataFrame só com: date, tag, time
        df = pd.DataFrame(filtrados)
        cols = ["date", "tag", "time"]
        cols_existentes = [c for c in cols if c in df.columns]
        df_view = df[cols_existentes].rename(columns={
            "date": "Dia",
            "tag": "Rótulo",
            "time": "Hora",
        })
        # Ordena por Dia e Hora
        try:
            df_view = df_view.sort_values(by=["Dia", "Hora"])
        except Exception:
            pass

        # Exibição compacta
        st.dataframe(df_view, height=220, use_container_width=True)

        # Download CSV apenas dessas três colunas
        csv = df_view.to_csv(index=False).encode("utf-8")
        st.download_button("CSV", data=csv, file_name="pontos_historico.csv", mime="text/csv")
    else:
        st.info("Sem registros no período.")

st.caption(
    f"Usuário: {USER_FIXED} · DB: {GITHUB_OWNER}/{GITHUB_REPO} · {GITHUB_PATH} ({GITHUB_BRANCH}) · TZ: {TIMEZONE_NAME} · "
    f"{'Futuro permitido' if ALLOW_FUTURE else 'Futuro bloqueado'}"
)
