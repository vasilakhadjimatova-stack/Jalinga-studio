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
              "fin_transactions", "edit_jobs"):
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
