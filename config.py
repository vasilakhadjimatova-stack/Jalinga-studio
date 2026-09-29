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

    # Ma'lumot XAVFI: productionда SQLite ishlatilsa, Railway konteyneri
    # fayl tizimi vaqtinchalik bo'lgani uchun HAR DEPLOY/RESTART'да butun baza
    # yo'qoladi. Doimiy Postgres ulash SHART (DATABASE_URL). Bu bayroq UI'да
    # qizil ogohlantirish va startда CRITICAL log chiqarish uchun ishlatiladi.
    DB_IS_SQLITE = SQLALCHEMY_DATABASE_URI.startswith("sqlite")
    DATA_AT_RISK = IS_PRODUCTION and DB_IS_SQLITE

    # Tashqi (absolyut) manzil — Telegram xabarlaridagi havolalar uchun.
    # APP_URL berilmasa Railway'ning ochiq domeni avtomatik olinadi.
    APP_URL = (os.environ.get("APP_URL") or (
        "https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"]
        if os.environ.get("RAILWAY_PUBLIC_DOMAIN") else "")).rstrip("/")

    COMPANY_NAME = "Jalinga Studio"
    # Ish vaqti (kalendar to'ri)
    WORK_START = 9    # 09:00
    WORK_END = 21     # 21:00

    # To'lov kalendari — minimal kassa zaxirasi (xavfsizlik buferi, so'm).
    # Kunlik bashorat qoldig'i bufer'dan past bo'lsa → sariq, manfiy → qizil.
    # UI'да ?buffer=... bilan vaqtincha o'zgartirish mumkin.
    CASH_SAFETY_BUFFER = float(os.environ.get("CASH_SAFETY_BUFFER", "20000000"))
