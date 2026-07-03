"""Toshkent vaqti — butun tizim uchun yagona manba."""
from datetime import datetime, timedelta, timezone

TASHKENT = timezone(timedelta(hours=5))


def now_tashkent() -> datetime:
    return datetime.now(TASHKENT).replace(tzinfo=None)


def today_iso() -> str:
    return now_tashkent().strftime("%Y-%m-%d")


def current_month_iso() -> str:
    return now_tashkent().strftime("%Y-%m")
