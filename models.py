
# -*- coding: utf-8 -*-
from __future__ import annotations
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

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
            obs=obs or "",
            created_at=dt.isoformat(),
        )

    def to_dict(self) -> dict:
        return asdict(self)
