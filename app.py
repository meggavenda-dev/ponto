
# -*- coding: utf-8 -*-
import os
from datetime import datetime, date
from typing import List

import streamlit as st
import pandas as pd

from services.github_store import GithubJSONStore
from models import RegistroPonto
from utils import get_tz, now_local

st.set_page_config(page_title="Registro de Ponto", page_icon="🕒", layout="centered")

# --------- Config ---------
owner = st.secrets.get("GITHUB_OWNER", "")
repo = st.secrets.get("GITHUB_REPO", "")
path = st.secrets.get("GITHUB_PATH", "pontos.json")
branch = st.secrets.get("GITHUB_BRANCH", "main")
token = st.secrets.get("GITHUB_TOKEN", "")
TZ_NAME = st.secrets.get("TIMEZONE", "America/Sao_Paulo")

with st.sidebar:
    st.header("⚙️ Configuração")
    owner = st.text_input("Owner", value=owner)
    repo = st.text_input("Repositório", value=repo)
    path = st.text_input("Arquivo JSON", value=path)
    branch = st.text_input("Branch", value=branch)
    token = st.text_input("GitHub Token (PAT)", value=token, type="password")

    st.divider()
    st.subheader("Identidade")
    default_user = os.getenv("USERNAME") or os.getenv("USER") or "usuario"
    usuario = st.text_input("Usuário", value=st.session_state.get("usuario", default_user))
    st.session_state["usuario"] = usuario

if not (owner and repo and token and path):
    st.info("Informe Owner, Repo, Token e Path para iniciar.")
    st.stop()

TZ = get_tz(TZ_NAME)
store = GithubJSONStore(owner, repo, token, branch)

# Carrega dados
try:
    data, sha = store.load(path)
except Exception as e:
    st.error(str(e))
    st.stop()

st.title("🕒 Registro de Ponto")
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
            ok = store.append_with_retry(path, rec.to_dict())
            if ok:
                st.success("Ponto registrado com sucesso.")
                st.cache_data.clear()
            else:
                st.error("Falha ao gravar. Tente novamente.")
    with c2:
        if st.button("Salvar horário selecionado"):
            dt = datetime.combine(dia, hora_selecionada).replace(tzinfo=TZ)
            rec = RegistroPonto.novo(usuario, dt, label="Manual", tag=rotulo, obs=observacao)
            ok = store.append_with_retry(path, rec.to_dict())
            if ok:
                st.success("Horário salvo.")
                st.cache_data.clear()
            else:
                st.error("Falha ao gravar. Tente novamente.")

    st.divider()
    st.subheader("Registros do dia")
    dia_str = dia.isoformat()
    registros_dia = [r for r in data if r.get("date") == dia_str and r.get("usuario") == usuario]
    # Ordenar por hora
    registros_dia.sort(key=lambda r: r.get("time", "00:00:00"))
    if registros_dia:
        st.table(registros_dia)
    else:
        st.info("Nenhum ponto para o dia selecionado.")

with aba_hist:
    st.subheader("Todos os pontos (histórico)")
    colf1, colf2 = st.columns(2)
    with colf1:
        usuario_f = st.text_input("Filtrar usuário", value=usuario)
    with colf2:
        periodo = st.date_input("Período", value=(date.today().replace(day=1), date.today()))

    dt_ini, dt_fim = periodo if isinstance(periodo, tuple) else (date.today().replace(day=1), date.today())

    def in_period(r: dict) -> bool:
        try:
            d = datetime.strptime(r.get("date"), "%Y-%m-%d").date()
            return d >= dt_ini and d <= dt_fim
        except Exception:
            return True

    filtrados = [r for r in data if in_period(r) and (not usuario_f or r.get("usuario") == usuario_f)]

    if filtrados:
        st.dataframe(filtrados, use_container_width=True)
        df = pd.DataFrame(filtrados)
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("Baixar CSV", data=csv, file_name="pontos.csv", mime="text/csv")
    else:
        st.info("Sem registros para o filtro.")

st.caption("Dados salvos em um arquivo JSON no GitHub.")
