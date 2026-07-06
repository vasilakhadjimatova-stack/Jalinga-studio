"""Baza + yengil avto-migratsiya (Impulse'da sinalgan yondashuv).

db.create_all() faqat yangi JADVAL yaratadi; model'ga keyin qo'shilgan
ustunlar ALTER TABLE bilan qo'shiladi. Idempotent — har startda xavfsiz.
"""
import logging

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)
db = SQLAlchemy()


def init_db(app):
    db.init_app(app)
    with app.app_context():
        import models  # noqa: F401 — barcha modellarni ro'yxatga oladi
        db.create_all()
        _auto_migrate()
        _ensure_indexes()


def _ensure_indexes():
    """Konkurent double-booking backstop: bir studiya+sana+boshlanish vaqtiga
    faqat bitta FAOL/YOZILGAN bron (qisman unikal indeks — SQLite/Postgres).
    Commitдан oldingi konflikt tekshiruvi bilan birga ishlaydi: ikki so'rov
    poyga qilsa, DB ikkinchisini rad etadi (ikki bron/arvoh bo'lmaydi)."""
    ddl = ("CREATE UNIQUE INDEX IF NOT EXISTS ux_booking_slot "
           "ON bookings (studio_id, date, start) "
           "WHERE status IN ('active', 'done')")
    try:
        db.session.execute(text(ddl))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning(f"slot unikal indeksi o'rnatilmadi: {exc}")


def _column_default_sql(col):
    d = col.default.arg if col.default is not None and not callable(
        getattr(col.default, "arg", None)) else None
    if d is None:
        return ""
    if isinstance(d, bool):
        # Postgres boolean ustunga integer default (1/0) qabul qilmaydi —
        # TRUE/FALSE kalit so'zi ikkала dialektда ham ishlaydi.
        return " DEFAULT TRUE" if d else " DEFAULT FALSE"
    if isinstance(d, (int, float)):
        return f" DEFAULT {d}"
    return " DEFAULT '" + str(d).replace("'", "''") + "'"


def _auto_migrate():
    try:
        inspector = inspect(db.engine)
        dialect = db.engine.dialect
    except Exception as exc:
        logger.warning(f"auto-migrate inspector xato: {exc}")
        return
    for table in db.metadata.sorted_tables:
        try:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                try:
                    col_type = col.type.compile(dialect=dialect)
                except Exception:
                    col_type = "VARCHAR(255)"
                ddl = (f"ALTER TABLE {table.name} ADD COLUMN "
                       f"{col.name} {col_type}{_column_default_sql(col)}")
                try:
                    db.session.execute(text(ddl))
                    db.session.commit()
                    logger.info(f"🔧 migratsiya: {table.name}.{col.name}")
                except Exception as exc:
                    db.session.rollback()
                    logger.warning(f"migratsiya o'tmadi {table.name}.{col.name}: {exc}")
        except Exception as exc:
            logger.warning(f"migratsiya jadval {table.name}: {exc}")
