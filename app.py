"""Jalinga Studio ERP — interaktiv video studiya boshqaruvi.

MVP 1-bosqich: studiyalar · bron (konflikt himoyasi) · ustozlar (paket/soat
balansi) · moliya · boshliq paneli. Impulse ERP arxitekturasi asosida.
"""
import logging
import os

from flask import Flask, redirect, url_for

from config import Config
from database import init_db
from core.auth import current_user, csrf_token

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    # Xavfsizlik: productionда SECRET_KEY majburiy (standart qiymat bilan
    # sessiya-cookie soxtalashtirilishi mumkin) — yo'q bo'lsa ishga tushmaymiz.
    if Config.IS_PRODUCTION:
        if app.config.get("SECRET_KEY") in ("", None, "dev-only-change-me"):
            raise RuntimeError(
                "SECRET_KEY o'rnatilmagan! Productionда haqiqiy maxfiy kalit "
                "kerak (Railway → Variables → SECRET_KEY).")
        # Admin kodi yagona hisob ma'lumot — productionда standart/bo'sh bo'lsa
        # istalgan begona kirib oladi. SECRET_KEY kabi majburiy qilamiz.
        _ac = (os.environ.get("ADMIN_CODE") or "").strip()
        if not _ac or _ac == "111111":
            raise RuntimeError(
                "ADMIN_CODE o'rnatilmagan yoki juda oddiy (111111)! "
                "Productionда kuchli maxfiy kod kerak "
                "(Railway → Variables → ADMIN_CODE, kamida 6 xonali).")
        app.config["SESSION_COOKIE_SECURE"] = True

    # Ma'lumot XAVFI: productionда SQLite = har deploy'да baza yo'qoladi.
    # Jimgina ma'lumot yo'qotishдан ko'ra ISHGA TUSHMASLIK xavfsizroq —
    # HARD-FAIL qilamiz (FORCE_SQLITE=1 bilan ataylab chetlab o'tsa bo'ladi).
    if Config.DATA_AT_RISK:
        if os.environ.get("FORCE_SQLITE") != "1":
            raise RuntimeError(
                "MA'LUMOT XAVF OSTIDA: productionда SQLite! Har deploy'да baza "
                "yo'qoladi. Postgres ulang (Railway → Database → PostgreSQL; "
                "DATABASE_URL avtomatik ulanadi). Ataylab davom etish uchun "
                "FORCE_SQLITE=1 qo'ying.")
        logging.critical("FORCE_SQLITE=1 — productionда SQLite bilan davom "
                         "etilyapti; har deploy'да baza yo'qoladi!")

    # Proxy ortida (Railway) haqiqiy klient IP'ni olish — rate-limit va audit
    # uchun. Aks holda remote_addr = proxy IP (barcha uchun bir xil) bo'ladi.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    init_db(app)

    from modules.auth.routes import bp as auth_bp
    from modules.dashboard.routes import bp as dash_bp
    from modules.studios.routes import bp as studios_bp
    from modules.bookings.routes import bp as bookings_bp
    from modules.teachers.routes import bp as teachers_bp
    from modules.finance.routes import bp as finance_bp
    from modules.portal.routes import bp as portal_bp
    from modules.analytics.routes import bp as analytics_bp
    from modules.team.routes import bp as team_bp
    from modules.pwa.routes import bp as pwa_bp
    from modules.book.routes import bp as book_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(dash_bp)
    app.register_blueprint(studios_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(teachers_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(team_bp)
    app.register_blueprint(pwa_bp)
    app.register_blueprint(book_bp)

    @app.context_processor
    def inject_globals():
        return {"current_user": current_user(), "csrf_token": csrf_token,
                "company": Config.COMPANY_NAME,
                "data_at_risk": Config.DATA_AT_RISK}

    @app.template_filter("som")
    def som(v):
        try:
            return f"{float(v):,.0f}".replace(",", " ")
        except (ValueError, TypeError):
            return "0"

    @app.template_filter("dmy")
    def dmy(v):
        """Sana ko'rinishi: 2026-07-10 → 10.07.2026 (kun.oy.yil).

        Faqat YYYY-MM-DD (yoki YYYY-MM-DD HH:MM...) boshlanadigan qatorni
        aylantiradi; boshqasiga tegmaydi."""
        s = str(v or "").strip()
        if len(s) >= 10 and s[4] == "-" and s[7] == "-" \
                and s[:4].isdigit() and s[5:7].isdigit() and s[8:10].isdigit():
            tail = s[10:]   # vaqt qismi bo'lsa saqlanadi (masalan " 14:30")
            return f"{s[8:10]}.{s[5:7]}.{s[:4]}{tail}"
        return s

    with app.app_context():
        from seed import seed_all
        seed_all()
        # Moliya: baza bo'sh bo'lsa repo'dagi Sheets snapshotini yuklaymiz
        # (birinchi ishga tushishda internetsiz ham ma'lumot bo'lsin)
        try:
            from modules.finance.sheets_sync import import_snapshot_if_empty
            import_snapshot_if_empty()
        except Exception:
            logging.exception("Moliya snapshotini yuklab bo'lmadi")

    # Telegram bot (token bo'lsa; testda o'chiq)
    if not app.config.get("TESTING") and not os.environ.get("DISABLE_BOT"):
        from core.telegram import start_bot
        start_bot(app)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5060))
    app.run(host="0.0.0.0", port=port,
            debug=not Config.IS_PRODUCTION)
