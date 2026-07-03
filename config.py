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
