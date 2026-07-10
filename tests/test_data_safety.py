"""Ma'lumot xavfsizligi: backup eksport + prod SQLite ogohlantirishi."""
import json


def test_backup_export(admin_client):
    r = admin_client.get("/team/backup.json")
    assert r.status_code == 200
    assert "json" in r.mimetype
    assert "attachment" in r.headers.get("Content-Disposition", "")
    data = json.loads(r.data)
    # Barcha muhim jadvallar backup'da
    for t in ("users", "teachers", "bookings", "jalinga_payments",
              "fin_transactions"):
        assert t in data, t
    assert data["_meta"]["app"] == "Jalinga Studio"


def test_backup_admin_only(client):
    r = client.get("/team/backup.json")
    assert r.status_code in (302, 303, 403)


def test_data_at_risk_flag_dev():
    """Dev (production emas) → xavf bayrog'i o'chiq."""
    from config import Config
    # Test muhitida PRODUCTION o'rnatilmagan → DATA_AT_RISK False bo'lishi kerak
    assert Config.DATA_AT_RISK in (False, True)  # mavjud
    # sqlite bo'lsa-da, production bo'lmagani uchun xavf yo'q
    if not Config.IS_PRODUCTION:
        assert Config.DATA_AT_RISK is False


# ── Healthz + Audit-log ──

def test_healthz(client):
    import json
    r = client.get("/healthz")
    assert r.status_code == 200
    d = json.loads(r.data)
    assert d["status"] == "ok" and "db" in d


def test_audit_records_finance_action(app, admin_client, post):
    from models.finance import FinCategory, FinWallet
    from models.audit import AuditLog
    with app.app_context():
        cat = FinCategory.query.filter_by(direction="out").first().name
        w = FinWallet.query.first().name
        before = AuditLog.query.count()
    post(admin_client, "/finance/transactions/add",
         date="2026-07-04", amount="500000", wallet=w, category=cat,
         purpose="audit test")
    with app.app_context():
        assert AuditLog.query.count() == before + 1
        last = AuditLog.query.order_by(AuditLog.id.desc()).first()
        assert last.action == "create" and last.entity == "transaction"
        assert last.user_name  # kim qilgani yozilgan


def test_audit_page_admin_only(app, client, admin_client):
    assert admin_client.get("/team/audit").status_code == 200
    r = client.get("/team/audit")
    assert r.status_code in (302, 303, 403)


# ── APP_LOCKED — vaqtinchalik to'xtatish rejimi ──

def test_app_locked_mode():
    """APP_LOCKED=1 → hamma sahifa 503 (locked.html), /healthz ishlaydi."""
    import os
    os.environ["APP_LOCKED"] = "1"
    try:
        from app import create_app
        a = create_app()
        a.config.update(TESTING=True)
        c = a.test_client()
        for path in ("/", "/login", "/book", "/finance", "/team"):
            r = c.get(path)
            assert r.status_code == 503, path
            assert "xtatilgan" in r.get_data(as_text=True), path
        assert c.get("/healthz").status_code == 200   # monitoring ochiq
    finally:
        os.environ.pop("APP_LOCKED", None)
