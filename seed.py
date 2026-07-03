"""Boshlang'ich ma'lumot: admin (ADMIN_CODE env) + 2 studiya. Idempotent."""
import logging
import os

from database import db
from models.user import User
from models.studio import Studio

logger = logging.getLogger(__name__)


def seed_all():
    try:
        if User.query.count() == 0:
            code = os.environ.get("ADMIN_CODE", "111111")
            db.session.add(User(name="Rahbar", code=code, role="admin"))
            db.session.commit()
            logger.info(f"👤 Admin yaratildi (kod: {'ENV' if 'ADMIN_CODE' in os.environ else code})")
        if Studio.query.count() == 0:
            db.session.add_all([
                Studio(name="Studiya A — Interaktiv doska",
                       description="Yashil ekran + interaktiv panel",
                       hourly_rate=300000, color="#6098F2", sort=1),
                Studio(name="Studiya B — Podkast",
                       description="2 mikrofon, yumshoq yorug'lik",
                       hourly_rate=200000, color="#F0B548", sort=2),
            ])
            db.session.commit()
            logger.info("🎬 2 ta studiya yaratildi")
    except Exception as exc:
        db.session.rollback()
        logger.error(f"Seed xato: {exc}")
