
# -*- coding: utf-8 -*-
"""App de Registro de Ponto — Streamlit + GitHub JSON via REST /contents."""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, date, timedelta, time as dtime
from typing import Optional, Tuple, List, Set, Dict

import requests
import pandas as pd
import streamlit as st
from zoneinfo import ZoneInfo
import html as html_escape  # para escapar atributos de tooltip com segurança

# ---------------------- Página & Estilo ----------------------
st.set_page_config(page_title="Ponto", page_icon="🕒", layout="centered")

COMPACT_CSS = """
<style>
/* Largura útil maior para comportar chips sem quebrar */
div.block-container { max-width: 600px; padding-top: 0.5rem; }

/* Tipografia compacta */
html, body, [class*="css"] { font-size: 14px; }
h1, h2, h3 { margin: 0.2rem 0 !important; }
.stButton>button { padding: 0.25rem 0.6rem; font-size: 0.9rem; }
.stDownloadButton>button { padding: 0.25rem 0.5rem; font-size: 0.85rem; }
.css-1v3fvcr, .css-5rimss, .stMarkdown { margin-bottom: 0.5rem !important; }
.stTable, .stDataFrame { font-size: 13px; }

/* Tabela do Histórico com chips */
.hist-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
.hist-table th, .hist-table td {
  border-bottom: 1px solid #e6e6e6;
  padding: 6px;
  vertical-align: top;
}
.hist-table th { text-align: left; font-weight: 600; }
.hist-dia   { width: 110px; }
.hist-total { width: 80px; text-align: right; white-space: nowrap; }

/* Linha de chips: sem quebra + scroll horizontal */
.chips {
  display: flex;
  flex-wrap: nowrap;      /* não quebra linha */
  gap: 8px;
  overflow-x: auto;       /* scroll horizontal */
  scrollbar-width: thin;  /* Firefox */
}
.chips::-webkit-scrollbar { height: 6px; }                 /* Chrome/Edge/Safari */
.chips::-webkit-scrollbar-track { background: #f1f1f1; border-radius: 6px; }
.chips::-webkit-scrollbar-thumb { background: #c7ccd3; border-radius: 6px; }
.chips::-webkit-scrollbar-thumb:hover { background: #a0a7b0; }

/* Chip quadrado/compacto */
.chip {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 4px 8px;
  min-width: 96px;                 /* largura mínima */
  border-radius: 4px;
  border: 1px solid #d0d4da;
  background: #f7f8fb;
  color: #1f2937;
  font-weight: 600;
  white-space: nowrap;
  box-sizing: border-box;
}

.chip .time {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-variant-numeric: tabular-nums;   /* dígitos alinhados */
  font-weight: 700;
}

.chip .tag {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid transparent;
}

/* Cores por rótulo */
.chip-Entrada  { border-color: #2e7d32; background: #e8f5e9; color: #1b5e20; }
.chip-Entrada .tag  { background: #c8e6c9; border-color: #2e7d32; color: #1b5e20; }

.chip-Saída    { border-color: #c62828; background: #ffebee; color: #b71c1c; }
.chip-Saída .tag    { background: #ffcdd2; border-color: #c62828; color: #b71c1c; }

.chip-Intervalo{ border-color: #1565c0; background: #e3f2fd; color: #0d47a1; }
.chip-Intervalo .tag{ background: #bbdefb; border-color: #1565c0; color: #0d47a1; }

.chip-Retorno  { border-color: #6a1b9a; background: #f3e5f5; color: #4a148c; }
.chip-Retorno .tag  { background: #e1bee7; border-color: #6a1b9a; color: #4a148c; }

.chip-Outro    { border-color: #616161; background: #f5f5f5; color: #212121; }
.chip-Outro .tag    { background: #eeeeee; border-color: #616161; color: #212121; }
</style>
"""
st.markdown(COMPACT_CSS, unsafe_allow_html=True)

# ---------------------- Config ----------------------
DEFAULT_OWNER   = "meggavenda-dev"
DEFAULT_REPO    = "registro-ponto-db"
DEFAULT_PATH    = "pontos.json"
DEFAULT_BRANCH  = "main"
DEFAULT_TZ_NAME = "America/Sao_Paulo"
DEFAULT_ALLOW_FUTURE = "false"

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
        "Falta o **GITHUB_TOKEN (PAT)** para gravar no GitHub.\n"
        "Defina em Settings → Secrets (Streamlit Cloud) ou como variável de ambiente.\n"
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
            # ignora ids não numéricos (ex.: UUID)
            pass
    return s

def generate_decimal_id(existing: Set[int]) -> int:
    """Gera ID inteiro baseado em timestamp (ms) e garante unicidade."""
    base = int(now_local(TZ).timestamp() * 1000)
    while base in existing:
        base += 1
    return base

def format_date_br(date_str: str) -> str:
    """Converte 'YYYY-MM-DD' -> 'dd/mm/aaaa' para exibição."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        return d.strftime("%d/%m/%Y")
    except Exception:
        return date_str or ""

def parse_hhmm_to_timestr(hhmm: str) -> Optional[str]:
    """Aceita 'HH:MM' ou 'HH:MM:SS' e devolve 'HH:MM:SS'. Retorna None se inválido."""
    try:
        hhmm = (hhmm or "").strip()
        if not hhmm:
            return None
        if len(hhmm) == 5 and ":" in hhmm:
            dt = datetime.strptime(hhmm, "%H:%M")
            return dt.strftime("%H:%M:%S")
        elif len(hhmm) == 8 and hhmm.count(":") == 2:
            dt = datetime.strptime(hhmm, "%H:%M:%S")
            return dt.strftime("%H:%M:%S")
        else:
            return None
    except Exception:
        return None

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
    """Camada de acesso ao 'banco' no GitHub (arquivo JSON via GitHub REST API)."""
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
        """Carrega conteúdo JSON e retorna (data, sha). Cria arquivo vazio [] se não existir."""
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
        """Grava JSON no GitHub. Se sha for None, cria; senão atualiza."""
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
        """Adiciona um registro com tentativa de resolução de conflitos (409)."""
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

    def replace_record(self, path: str, record_id: str, new_time: str) -> bool:
        """Atualiza 'time' de um registro, comparando ids como string (suporta int e UUID)."""
        data, sha = self.load(path)
        found = False
        for r in data:
            try:
                if str(r.get("id")) == str(record_id):
                    r["time"] = new_time
                    found = True
                    break
            except Exception:
                continue
        if not found:
            return False
        new_sha = self.commit(path, data, sha, message=f"Atualiza horário id={record_id} para {new_time}")
        return bool(new_sha)

store = GithubJSONStore(
    owner=GITHUB_OWNER,
    repo=GITHUB_REPO,
    token=GITHUB_TOKEN,
    branch=GITHUB_BRANCH,
)

# ---------------------- Estado ----------------------
def _init_session_defaults():
    st.session_state.setdefault("usuario", USER_FIXED)      # usuário sempre fixo
    st.session_state.setdefault("dia_sel", date.today())
    st.session_state.setdefault("hora_sel", now_local(TZ).time().replace(microsecond=0))
    st.session_state.setdefault("hora_text_reg", "")        # campo de hora manual no registro
    st.session_state.setdefault("dia_edit", st.session_state["dia_sel"])  # dia padrão para edição

_init_session_defaults()

# ---------------------- Carregar dados ----------------------
try:
    data, current_sha = store.load(GITHUB_PATH)
except Exception as e:
    st.error(f"Falha ao carregar dados do GitHub: {e}")
    st.stop()

# ---------------------- Callbacks ----------------------
def shift_minutes(delta_min: int):
    dia_atual: date = st.session_state["dia_sel"]
    hora_atual: dtime = st.session_state["hora_sel"]
    base_dt = datetime.combine(dia_atual, hora_atual).replace(tzinfo=TZ)
    novo_dt = base_dt + timedelta(minutes=delta_min)
    st.session_state["dia_sel"] = novo_dt.date()
    st.session_state["hora_sel"] = novo_dt.time().replace(microsecond=0)

def set_now():
    st.session_state["dia_sel"] = date.today()
    st.session_state["hora_sel"] = now_local(TZ).time().replace(microsecond=0)
    st.session_state["hora_text_reg"] = ""  # limpa o campo manual

def _save_now(rotulo: str, observacao: str):
    agora = now_local(TZ)
    new_id = generate_decimal_id(existing_ids_int(data))
    rec = RegistroPonto.novo(new_id, st.session_state["usuario"], agora, label="Automático", tag=rotulo, obs=observacao)
    ok = store.append_with_retry(GITHUB_PATH, rec.to_dict())
    if ok:
        st.success("Registrado (agora).")
        st.session_state.update(hora_text_reg="")  # limpa manual
        st.rerun()
    else:
        st.error("Falha ao gravar no GitHub.")

def _save_manual(rotulo: str, observacao: str, dt_sel: datetime, allow_future: bool):
    agora = now_local(TZ)
    if (not allow_future) and (dt_sel > agora):
        st.error("Horário no futuro não permitido. Ajuste para passado/atual.")
        return
    new_id = generate_decimal_id(existing_ids_int(data))
    rec = RegistroPonto.novo(new_id, st.session_state["usuario"], dt_sel, label="Manual", tag=rotulo, obs=observacao)
    ok = store.append_with_retry(GITHUB_PATH, rec.to_dict())
    if ok:
        st.success("Horário manual salvo.")
        st.session_state.update(hora_text_reg="")  # limpa manual
        st.rerun()
    else:
        st.error("Falha ao gravar no GitHub.")

# ---------------------- UI ----------------------
st.title("🕒 Ponto")

# Campo de usuário (fixo, desabilitado)
st.text_input("Usuário", key="usuario", disabled=True)

aba_hoje, aba_hist, aba_edit = st.tabs(["Hoje", "Histórico", "Editar"])

# ---------------------- ABA: HOJE ----------------------
with aba_hoje:
    # Widgets do registro
    c1, c2, c3 = st.columns([1.1, 1.1, 1.2])
    with c1:
        st.date_input("Dia", key="dia_sel", label_visibility="collapsed")
        st.caption("Dia")
    with c2:
        st.time_input("Hora", key="hora_sel", label_visibility="collapsed")
        st.caption("Hora")
    with c3:
        rotulo = st.selectbox("Rótulo",
                              ["Entrada", "Saída", "Intervalo", "Retorno", "Outro"],
                              index=0, label_visibility="collapsed")
        st.caption("Rótulo")

    # Hora manual (tem prioridade se válida)
    st.text_input("Hora manual (HH:MM ou HH:MM:SS)", key="hora_text_reg", placeholder="ex.: 08:09")

    # Observação e botões de ajuste rápido
    with st.expander("Observação (opcional)", expanded=False):
        observacao = st.text_input("Observação", value="", placeholder="Digite algo breve...")

    a1, a2, a3, a4 = st.columns(4)
    a1.button("-5",  use_container_width=True, on_click=shift_minutes, args=(-5,))
    a2.button("-10", use_container_width=True, on_click=shift_minutes, args=(-10,))
    a3.button("-15", use_container_width=True, on_click=shift_minutes, args=(-15,))
    a4.button("Agora", use_container_width=True, on_click=set_now)

    # Resolve o horário selecionado (manual sobrescreve se válido)
    parsed_manual = parse_hhmm_to_timestr(st.session_state["hora_text_reg"])
    hora_final_str = parsed_manual if parsed_manual else st.session_state["hora_sel"].strftime("%H:%M:%S")
    dt_sel = datetime.strptime(st.session_state["dia_sel"].isoformat() + " " + hora_final_str,
                               "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)

    # Feedback relação com 'agora'
    agora = now_local(TZ)
    if dt_sel < agora:
        st.info(f"⏱️ Horário **passado**: {hora_final_str} — registro retroativo permitido.")
    elif dt_sel == agora.replace(microsecond=0):
        st.info("✅ Horário **agora**.")
    else:
        if ALLOW_FUTURE:
            st.warning(f"⏳ Horário **no futuro**: {hora_final_str} — será aceito.")
        else:
            st.warning(f"⏳ Horário **no futuro**: {hora_final_str} — ajuste para passado/atual.")

    # Conjunto de IDs existentes como inteiros
    existing_ids = existing_ids_int(data)

    b1, b2 = st.columns([1, 1])
    with b1:
        st.button("Agora", type="primary", use_container_width=True,
                  on_click=_save_now, args=(rotulo, observacao))
    with b2:
        st.button("Salvar", use_container_width=True,
                  on_click=_save_manual, args=(rotulo, observacao, dt_sel, ALLOW_FUTURE))

    # Exibição "Hoje"
    st.markdown("---")
    st.subheader("Hoje (Rótulo, Dia, Hora)")
    dia_str = st.session_state["dia_sel"].isoformat()
    registros_dia = [r for r in data if r.get("date") == dia_str and r.get("usuario") == st.session_state["usuario"]]

    if registros_dia:
        df_dia = pd.DataFrame(registros_dia)
        df_dia["Dia_BR"] = df_dia["date"].apply(format_date_br)
        df_view = df_dia[["tag", "Dia_BR", "time"]].rename(columns={
            "tag": "Rótulo",
            "Dia_BR": "Dia",
            "time": "Hora",
        })
        try:
            df_dia["Dia_ord"] = pd.to_datetime(df_dia["date"], format="%Y-%m-%d", errors="coerce")
            df_view = df_view.join(df_dia[["Dia_ord"]])
            df_view = df_view.sort_values(by=["Dia_ord", "Hora"]).drop(columns=["Dia_ord"])
        except Exception:
            pass
        st.dataframe(df_view, height=320, use_container_width=True)
    else:
        st.info("Sem pontos hoje.")

# ---------------------- Função: total trabalhado por dia ----------------------
def total_trabalhado_hhmm_por_dia(df: pd.DataFrame) -> Dict[str, str]:
    """
    Soma pares Entrada -> Saída por 'date', em ordem de 'time'.
    Retorna {date_iso: "HH:MM"}.
    """
    totals: Dict[str, str] = {}
    if df.empty:
        return totals
    for day_iso, g in df.groupby("date"):
        pares_secs = 0
        start: Optional[str] = None
        g_sorted = g.sort_values(by="time")
        for _, row in g_sorted.iterrows():
            tag = (row.get("tag") or "").strip()
            hh = (row.get("time") or "").strip()
            if not hh:
                continue
            if tag == "Entrada" and start is None:
                start = hh
            elif tag == "Saída" and start is not None:
                try:
                    dt1 = datetime.strptime(day_iso + " " + start, "%Y-%m-%d %H:%M:%S")
                    dt2 = datetime.strptime(day_iso + " " + hh,   "%Y-%m-%d %H:%M:%S")
                    if dt2 >= dt1:
                        pares_secs += int((dt2 - dt1).total_seconds())
                except Exception:
                    pass
                start = None
        h = pares_secs // 3600
        m = (pares_secs % 3600) // 60
        totals[day_iso] = f"{h:02d}:{m:02d}"
    return totals

# ---------------------- ABA: HISTÓRICO (chips uma linha + total) ----------------------
with aba_hist:
    st.subheader("Histórico (dia em linha com chips + total)")

    # Filtros
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

    # Função: está no período?
    def in_period(r: dict) -> bool:
        try:
            d = datetime.strptime(r.get("date"), "%Y-%m-%d").date()
            return dt_ini <= d <= dt_fim
        except Exception:
            return False

    # Filtra dados
    filtrados = [
        r for r in data
        if in_period(r) and (not usuario_f or r.get("usuario") == usuario_f)
    ]

    if filtrados:
        # DataFrame base
        df = pd.DataFrame(filtrados)
        for col in ["date", "time", "tag", "usuario", "label", "obs", "id", "created_at"]:
            if col not in df.columns:
                df[col] = ""

        # Ordenação por data/hora
        try:
            df["Dia_ord"] = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
        except Exception:
            df["Dia_ord"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values(by=["Dia_ord", "time"])

        # Registros por dia -> DataFrame ["date", "records"]
        grouped = (
            df.groupby("date")
              .apply(lambda g: g.to_dict(orient="records"))
              .reset_index(name="records")
        )
        grouped["Dia_BR"] = grouped["date"].apply(format_date_br)

        # Totais por dia (HH:MM)
        totals_map = total_trabalhado_hhmm_por_dia(df)

        # Monta HTML com chips e coluna total
        rows_html = []
        for _, row in grouped.iterrows():
            dia_iso = row["date"]
            dia_br = row["Dia_BR"]
            registros = row["records"] or []

            chips_html = []
            for r in registros:
                hhmmss = (r.get("time") or "").strip()
                tag = (r.get("tag") or "Outro").strip()
                tag_class = f"chip-{tag}" if tag in ("Entrada", "Saída", "Intervalo", "Retorno", "Outro") else "chip-Outro"
                # Tooltip com observação e created_at (se existirem)
                obs = (r.get("obs") or "").strip()
                created = (r.get("created_at") or "").strip()
                tooltip = f"{tag} — {hhmmss}"
                if obs:
                    tooltip += f" | Obs: {obs}"
                if created:
                    tooltip += f" | Criado: {created}"
                # Escapa com segurança para atributo title
                tooltip_attr = html_escape.escape(tooltip, quote=True)
                chip = (
                    f'<span class="chip {tag_class}" title="{tooltip_attr}">'
                    f'  <span class="time">{hhmmss}</span><span class="tag">{tag}</span>'
                    f'</span>'
                )
                chips_html.append(chip)

            total_hhmm = totals_map.get(dia_iso, "00:00")

            row_html = f"""
            <tr>
              <td class="hist-dia"><strong>{dia_br}</strong></td>
              <td><div class="chips">{''.join(chips_html)}</div></td>
              <td class="hist-total"><code>{total_hhmm}</code></td>
            </tr>
            """
            rows_html.append(row_html)

        table_html = f"""
        <table class="hist-table">
          <thead>
            <tr>
              <th class="hist-dia">Dia</th>
              <th>Pontos</th>
              <th class="hist-total">Total</th>
            </tr>
          </thead>
          <tbody>
            {''.join(rows_html)}
          </tbody>
        </table>
        """

        st.markdown(table_html, unsafe_allow_html=True)

        # ---------- CSV agregado (Dia, Pontos do dia, Total) ----------
        def _fmt_point(r: dict) -> str:
            hhmmss = (r.get("time") or "")
            tag = (r.get("tag") or "")
            return f"{hhmmss} ({tag})" if hhmmss or tag else ""

        df["pt_fmt"] = df.apply(_fmt_point, axis=1)
        points_agg = (
            df.groupby("date")["pt_fmt"]
              .apply(lambda s: " · ".join([x for x in s.tolist() if x]))
              .reset_index(name="Pontos do dia")
        )
        # Junta com totais
        totals_df = pd.DataFrame({"date": list(totals_map.keys()), "Total": list(totals_map.values())})
        csv_df = points_agg.merge(totals_df, on="date", how="left")
        csv_df["Dia_BR"] = csv_df["date"].apply(format_date_br)
        try:
            csv_df["Dia_ord"] = pd.to_datetime(csv_df["date"], format="%Y-%m-%d", errors="coerce")
        except Exception:
            csv_df["Dia_ord"] = pd.to_datetime(csv_df["date"], errors="coerce")
        csv_view = csv_df[["Dia_BR", "Pontos do dia", "Total", "Dia_ord"]].sort_values("Dia_ord").drop(columns=["Dia_ord"])
        csv_view = csv_view.rename(columns={"Dia_BR": "Dia"})

        csv_bytes = csv_view.to_csv(index=False).encode("utf-8")
        st.download_button("CSV (dia, pontos e total)", data=csv_bytes,
                           file_name="pontos_historico_por_dia.csv", mime="text/csv")
    else:
        st.info("Sem registros no período.")

# ---------------------- ABA: EDITAR ----------------------
with aba_edit:
    st.subheader("Editar horário (por dia)")
    # Escolhe o dia para editar (por padrão, o mesmo de "Hoje")
    st.date_input("Dia para editar", key="dia_edit")
    dia_edit_iso = st.session_state["dia_edit"].isoformat()

    # Filtra registros do dia selecionado e do usuário
    registros_edit = [r for r in data if r.get("date") == dia_edit_iso and r.get("usuario") == st.session_state["usuario"]]

    # Ordena por hora
    def _key_time(r: dict) -> str:
        t = r.get("time", "00:00:00")
        return t if isinstance(t, str) else "00:00:00"
    registros_edit.sort(key=_key_time)

    if registros_edit:
        # Opções: exibe rótulo + hora + id para desambiguar
        entries = []
        for r in registros_edit:
            rec_id = r.get("id")
            if rec_id is None:
                continue
            display = f"{r.get('tag','?')} - {r.get('time','??:??:??')} (id {rec_id})"
            entries.append((display, str(rec_id)))

        labels = [e[0] for e in entries]
        choice_label = st.selectbox("Selecione o ponto", options=labels, key="edit_choice_label")
        chosen_id = next((e[1] for e in entries if e[0] == choice_label), None)

        # Entrada livre 'HH:MM' ou 'HH:MM:SS' + seletor de hora
        col_e1, col_e2 = st.columns([1.2, 1.2])
        with col_e1:
            time_str_input = st.text_input("Novo horário (HH:MM ou HH:MM:SS)", key="edit_time_text", placeholder="ex.: 08:09")
        with col_e2:
            time_picker = st.time_input("Ou escolha:", key="edit_time_picker", value=now_local(TZ).time().replace(microsecond=0))

        parsed_text = parse_hhmm_to_timestr(time_str_input)
        new_time_final = parsed_text if parsed_text else time_picker.strftime("%H:%M:%S")

        # Valida futuro conforme flag, usando 'dia_edit'
        agora = now_local(TZ)
        dt_edit_base = datetime.strptime(dia_edit_iso + " " + new_time_final, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
        if (not ALLOW_FUTURE) and (dt_edit_base > agora):
            st.warning(f"Horário {new_time_final} está no futuro. Ajuste para passado/atual.")
        else:
            if st.button("Salvar edição", use_container_width=True, key="edit_save_btn"):
                if chosen_id is None:
                    st.error("Seleção inválida.")
                else:
                    ok = store.replace_record(GITHUB_PATH, record_id=chosen_id, new_time=new_time_final)
                    if ok:
                        st.success(f"Horário atualizado para {new_time_final}.")
                        st.rerun()
                    else:
                        st.error("Falha ao atualizar registro no GitHub.")
    else:
        st.info("Sem pontos para o dia selecionado.")

st.caption(
    f"Usuário: {USER_FIXED} · DB: {GITHUB_OWNER}/{GITHUB_REPO} · {GITHUB_PATH} ({GITHUB_BRANCH}) · TZ: {TIMEZONE_NAME} · "
    f"{'Futuro permitido' if ALLOW_FUTURE else 'Futuro bloqueado'}"
)
