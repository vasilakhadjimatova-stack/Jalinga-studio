"""Jalinga Studio — sozlamalar (env orqali, sirlar kodda YO'Q)."""
import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///jalinga.db").replace(
        "postgres://", "postgresql://")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    IS_PRODUCTION = bool(os.environ.get("RAILWAY_ENVIRONMENT")
                         or os.environ.get("PRODUCTION"))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    COMPANY_NAME = "Jalinga Studio"
    # Ish vaqti (kalendar to'ri)
    WORK_START = 9    # 09:00
    WORK_END = 21     # 21:00

    # ── Moliya ERP — Google Sheets «Jalinga 2026» ───────────────────────────
    # Jadval havola orqali ochiq bo'lishi kerak (anyone with link, Viewer) —
    # sync autentifikatsiyasiz xlsx eksport URL'idan o'qiydi.
    FINANCE_SPREADSHEET_ID = os.environ.get(
        "FINANCE_SPREADSHEET_ID",
        "1IRRQDOjHI0iJEUqov0Aq1XaD8mLzwlwe0j3A4xgPjTk")
    # $ kassani so'm ekvivalentiga keltirish kursi (ochilish qoldig'i uchun)
    USD_RATE = float(os.environ.get("USD_RATE", "12000"))
    # Avto-sync intervali (daqiqa). 0 → o'chiq (faqat qo'lda «Sync» tugmasi).
    # Railway'да masalan 120 (2 soat) qo'yish tavsiya etiladi.
    FINANCE_SYNC_INTERVAL = int(os.environ.get("FINANCE_SYNC_INTERVAL", "0"))
    # To'lov kalendari — minimal kassa zaxirasi (xavfsizlik buferi, so'm).
    # Kunlik bashorat qoldig'i bufer'dan past bo'lsa → sariq, manfiy → qizil.
    # UI'да ?buffer=... bilan vaqtincha o'zgartirish mumkin.
    CASH_SAFETY_BUFFER = float(os.environ.get("CASH_SAFETY_BUFFER", "20000000"))
