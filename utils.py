
# -*- coding: utf-8 -*-
from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_TZ = "America/Sao_Paulo"

def get_tz(name: str | None) -> ZoneInfo:
    return ZoneInfo(name or DEFAULT_TZ)

def now_local(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)

