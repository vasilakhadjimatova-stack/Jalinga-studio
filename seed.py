"""Boshlang'ich ma'lumot: admin (ADMIN_CODE env) + 2 studiya. Idempotent."""
import logging
import os

from database import db
from models.user import User
from models.studio import Studio

logger = logging.getLogger(__name__)


def seed_all():
    try:
        env_code = (os.environ.get("ADMIN_CODE") or "").strip()
        if User.query.count() == 0:
            code = env_code or "111111"
            db.session.add(User(name="Rahbar", code=code, role="admin"))
            db.session.commit()
            logger.info(f"👤 Admin yaratildi (kod: {'ENV' if env_code else code})")
        elif env_code:
            # ADMIN_CODE o'rnatilgan — asosiy admin shu kodni ishlatsin.
            # (Railway env kodini o'zgartirsangiz, login kodi ham yangilanadi.)
            # Faqat bu kodni hech kim band qilmagan bo'lsa (konflikt bo'lmasin).
            taken = User.query.filter_by(code=env_code).first()
            if taken is None:
                admin = User.query.filter_by(
                    role="admin").order_by(User.id).first()
                if admin and admin.code != env_code:
                    admin.code = env_code
                    admin.is_active = True
                    db.session.commit()
                    logger.info("👤 Asosiy admin kodi ADMIN_CODE env bilan "
                                "yangilandi")
            elif taken.role != "admin":
                logger.warning("ADMIN_CODE boshqa foydalanuvchida band — "
                               "admin kodi yangilanmadi")
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
