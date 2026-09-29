"""Avtopilot: retention avto-vazifalari, kunlik zaxira, bir martalik kafolat."""
import gzip
import json
from datetime import timedelta

from database import db


def _teacher(name, phone=""):
    from models.billing import Teacher
    t = Teacher(name=name, phone=phone, is_active=True)
    db.session.add(t)
    db.session.flush()
    return t


def test_retention_low_balance_and_cooldown(app):
    from core.retention import run_retention
    from core.timeutils import today_iso
    from models.billing import Payment
    from models.studio import Booking, Studio
    from models.communication import Task
    with app.app_context():
        t = _teacher("Retention Paket", "+998901112233")
        db.session.add(Payment(teacher_id=t.id, kind="package", hours=3,
                               amount=1, date=today_iso(), is_paid=True))
        db.session.add(Booking(studio_id=Studio.query.first().id,
                               teacher_id=t.id, date="2020-01-06",
                               start="10:00", end="12:00", status="done",
                               pay_type="package"))
        db.session.commit()
        run_retention()
        title = "📦 Paket tugayapti: Retention Paket — yangi paket taklif qiling"
        tasks = Task.query.filter_by(title=title).all()
        assert len(tasks) == 1 and tasks[0].is_auto
        assert "+998901112233" in tasks[0].description
        # Ikkinchi yurish — dublikat yo'q
        run_retention()
        assert Task.query.filter_by(title=title).count() == 1
        # Bajarildi qilinsa ham COOLDOWN ichida qayta chiqmaydi
        tasks[0].status = "done"
        db.session.commit()
        run_retention()
        assert Task.query.filter_by(title=title).count() == 1


def test_retention_churn_and_followup(app):
    from core.retention import run_retention, CHURN_DAYS
    from core.timeutils import now_tashkent, today_iso
    from models.billing import ClientNote
    from models.studio import Booking, Studio
    from models.communication import Task
    with app.app_context():
        old = (now_tashkent().date() - timedelta(days=CHURN_DAYS + 20))
        t = _teacher("Uxlagan Mijoz")
        db.session.add(Booking(studio_id=Studio.query.first().id,
                               teacher_id=t.id,
                               date=old.strftime("%Y-%m-%d"),
                               start="17:00", end="18:00", status="done"))
        f = _teacher("Followup Mijoz")
        db.session.add(ClientNote(teacher_id=f.id, kind="followup",
                                  text="Narxni qayta aytish", due_date=today_iso()))
        db.session.commit()
        run_retention()
        assert Task.query.filter_by(
            title="📡 Qayta faollashtiring: Uxlagan Mijoz").first() is not None
        fu = Task.query.filter(Task.title.like("⏰ Follow-up: Followup Mijoz%")).first()
        assert fu is not None and fu.due_date == today_iso()


def test_backup_build_is_complete(app):
    from core.backup import backup_json_bytes
    with app.app_context():
        raw, total = backup_json_bytes()
    dump = json.loads(raw)
    assert dump["_meta"]["format"] == 1 and total > 0
    for tbl in ("users", "bookings", "teachers", "fin_transactions", "surveys"):
        assert tbl in dump


def test_backup_sent_to_linked_admins(app, monkeypatch):
    import core.telegram as tg
    from core.backup import send_backup_telegram
    from models.user import User
    sent = []
    monkeypatch.setattr(tg, "TOKEN", "x")
    monkeypatch.setattr(tg, "tg_send_document",
                        lambda chat, fn, data, cap="", content_type="": (
                            sent.append((chat, fn, data)) or True))
    with app.app_context():
        a = User.query.filter_by(role="admin").first()
        old = a.tg_chat_id
        a.tg_chat_id = "555"
        db.session.commit()
        try:
            assert send_backup_telegram() == 1
        finally:
            a.tg_chat_id = old
            db.session.commit()
    chat, fn, data = sent[0]
    assert chat == "555" and fn.endswith(".json.gz")
    assert json.loads(gzip.decompress(data))["_meta"]["app"] == "Jalinga Studio"


def test_backup_noop_without_bot(app):
    from core.backup import send_backup_telegram
    with app.app_context():
        assert send_backup_telegram() == 0


def test_autopilot_runs_once_per_day(app, monkeypatch):
    import core.autopilot as ap
    from models.finance import FinSetting
    monkeypatch.setattr(ap, "AUTOPILOT_HOUR", 0)
    with app.app_context():
        FinSetting.set(ap._MARK, "")
        db.session.commit()
        assert ap._due_today() is True
        assert ap._due_today() is False
        rep = ap.run_daily()
        assert set(rep) >= {"surveys", "retention", "prune"}
        assert not any(str(v).startswith("xato") for v in rep.values())


def test_team_backup_download(admin_client):
    r = admin_client.get("/team/backup.json")
    assert r.status_code == 200
    assert json.loads(r.data)["_meta"]["app"] == "Jalinga Studio"
