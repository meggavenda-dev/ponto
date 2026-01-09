
# -*- coding: utf-8 -*-
"""
App de Registro de Ponto - Streamlit + GitHub (JSON) como banco.
Opção 2: Segredos no Streamlit Cloud (Settings → Secrets).
- Aba "Hoje": registra ponto automático (agora) ou horário selecionado (manual).
- Aba "Histórico": lista completa com filtros e download CSV.
- Necessita do GITHUB_TOKEN (PAT) nos Secrets do Streamlit Cloud.
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

# ---------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="Registro de Ponto",
    page_icon="🕒",
    layout="centered",
)

# ---------------------------------------------------------------------
# Defaults (só para fallback; no Cloud use Secrets)
# ---------------------------------------------------------------------
DEFAULT_OWNER   = "meggavenda-dev"
DEFAULT_REPO    = "registro-ponto-db"
DEFAULT_PATH    = "pontos.json"
DEFAULT_BRANCH  = "main"
DEFAULT_TZ_NAME = "America/Sao_Paulo"

def cfg(key: str, default: str = "") -> str:
    """Lê primeiro st.secrets, depois env, senão aplica default."""
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
GITHUB_TOKEN  = cfg("GITHUB_TOKEN",  "")  # SEM default propositalmente (obrigatório)

# ---------------------------------------------------------------------
# Guardas de segurança
# ---------------------------------------------------------------------
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
        "```"
    )
    st.stop()

# ---------------------------------------------------------------------
# Utilitários de data/hora (timezone)
# ---------------------------------------------------------------------
def get_tz(name: str | None) -> ZoneInfo:
    return ZoneInfo(name or DEFAULT_TZ_NAME)

TZ = get_tz(TIMEZONE_NAME)

def now_local(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)

# ---------------------------------------------------------------------
# Modelo de dados
# ---------------------------------------------------------------------
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

# ---------------------------------------------------------------------
# Camada de acesso ao JSON no GitHub (REST /contents)
# ---------------------------------------------------------------------
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
        """Carrega conteúdo JSON e retorna (data, sha). Cria arquivo [] se não existir."""
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
            # cria o arquivo com []
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
        """Grava JSON no GitHub. Se sha for None, cria; senão atualiza. Retorna novo sha."""
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
            # conflito de versão (alguém gravou antes)
            return None
        raise RuntimeError(f"Erro ao gravar no GitHub: {r.status_code} {r.text}")

    def append_with_retry(self, path: str, record: dict, max_retries: int = 3, sleep_seconds: float = 0.8) -> bool:
        """Adiciona um registro com tentativas para resolver conflitos (409)."""
        import time as _time
        for _ in range(max_retries):
            data, sha = self.load(path)
            data.append(record)
            new_sha = self.commit(
                path,
                data,
                sha,
                message=f"Ponto {record.get('usuario','?')} {record.get('date','')} {record.get('time','')}"
            )
            if new_sha:
                return True
            _time.sleep(sleep_seconds)
        return False

# ---------------------------------------------------------------------
# Instância do "banco"
# ---------------------------------------------------------------------
store = GithubJSONStore(
    owner=GITHUB_OWNER,
    repo=GITHUB_REPO,
    token=GITHUB_TOKEN,
    branch=GITHUB_BRANCH,
)

# ---------------------------------------------------------------------
# Carrega dados iniciais
# ---------------------------------------------------------------------
try:
    data, current_sha = store.load(GITHUB_PATH)
except Exception as e:
    st.error(f"Falha ao carregar dados do GitHub: {e}")
    st.stop()

# ---------------------------------------------------------------------
# UI principal
# ---------------------------------------------------------------------
st.title("🕒 Registro de Ponto")

# Identidade do usuário (automático com possibilidade de editar)
default_user = os.getenv("USERNAME") or os.getenv("USER") or "usuario"
usuario = st.text_input("Usuário", value=st.session_state.get("usuario", default_user))
st.session_state["usuario"] = usuario

aba_hoje, aba_hist = st.tabs(["Hoje", "Histórico"])

with aba_hoje:
    st.subheader("Bater ponto")

    col1, col2 = st.columns(2)
    with col1:
        dia = st.date_input("Dia", value=date.today())
    with col2:
        hora_selecionada = st.time_input("Hora", value=now_local(TZ).time().replace(microsecond=0))

    rotulos_padrao = ["Entrada", "Saída", "Intervalo", "Retorno", "Outro"]
    rotulo = st.selectbox("Rótulo", options=rotulos_padrao, index=0)
    observacao = st.text_input("Observação (opcional)")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Bater ponto agora", type="primary"):
            dt = now_local(TZ)
            rec = RegistroPonto.novo(usuario, dt, label="Automático", tag=rotulo, obs=observacao)
            ok = store.append_with_retry(GITHUB_PATH, rec.to_dict())
            if ok:
                st.success("Ponto registrado com sucesso.")
                # Recarrega para mostrar o novo registro imediatamente
                data, current_sha = store.load(GITHUB_PATH)
            else:
                st.error("Falha ao gravar no GitHub. Tente novamente.")

    with c2:
        if st.button("Salvar horário selecionado"):
            dt = datetime.combine(dia, hora_selecionada).replace(tzinfo=TZ)
            rec = RegistroPonto.novo(usuario, dt, label="Manual", tag=rotulo, obs=observacao)
            ok = store.append_with_retry(GITHUB_PATH, rec.to_dict())
            if ok:
                st.success("Horário salvo.")
                # Recarrega para mostrar o novo registro imediatamente
                data, current_sha = store.load(GITHUB_PATH)
            else:
                st.error("Falha ao gravar no GitHub. Tente novamente.")

    st.divider()
    st.subheader("Registros do dia")

    dia_str = dia.isoformat()
    registros_dia = [r for r in data if r.get("date") == dia_str and r.get("usuario") == usuario]
    # Ordena por hora de forma robusta
    def _key_time(r: dict) -> str:
        t = r.get("time", "00:00:00")
        return t if isinstance(t, str) else "00:00:00"
    registros_dia.sort(key=_key_time)

    if registros_dia:
        st.table(registros_dia)
    else:
        st.info("Nenhum ponto para o dia selecionado.")

with aba_hist:
    st.subheader("Todos os pontos (histórico)")

    colf1, colf2 = st.columns(2)
    with colf1:
        usuario_f = st.text_input("Filtrar por usuário (vazio = todos)", value=usuario)
    with colf2:
        periodo = st.date_input("Período", value=(date.today().replace(day=1), date.today()))

    if isinstance(periodo, tuple) and len(periodo) == 2:
        dt_ini, dt_fim = periodo
    else:
        dt_ini, dt_fim = date.today().replace(day=1), date.today()

    def in_period(r: dict) -> bool:
        try:
            d = datetime.strptime(r.get("date"), "%Y-%m-%d").date()
            return (d >= dt_ini) and (d <= dt_fim)
        except Exception:
            return True

    filtrados = [r for r in data if in_period(r) and (not usuario_f or r.get("usuario") == usuario_f)]

    if filtrados:
        st.dataframe(filtrados, use_container_width=True)
        df = pd.DataFrame(filtrados)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("Baixar CSV", data=csv, file_name="pontos.csv", mime="text/csv")
    else:
        st.info("Sem registros para o filtro aplicado.")

st.caption(
    "Dados salvos no GitHub (arquivo JSON). "
    f"Owner: **{GITHUB_OWNER}**, Repo: **{GITHUB_REPO}**, Path: **{GITHUB_PATH}**, Branch: **{GITHUB_BRANCH}**."
)

