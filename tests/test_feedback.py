"""Mijoz fikri (CSAT + NPS): so'rovnoma oqimi, charchatmaslik, service recovery."""
from datetime import datetime, timedelta

from database import db


_DAY = {"n": 0}


def _done_booking(app, name, start="10:00"):
    """O'tgan kundagi «Yozildi» bron (to'g'ridan bazaga). Har chaqiriq
    alohida kun — boshqa bronlar bilan slot to'qnashmasin."""
    _DAY["n"] += 1
    day_offset = -_DAY["n"]
    from models.billing import Teacher
    from models.studio import Studio, Booking
    from core.timeutils import now_tashkent
    with app.app_context():
        t = Teacher(name=name, is_active=True)
        db.session.add(t)
        db.session.flush()
        d = (now_tashkent().date() + timedelta(days=day_offset)).strftime(
            "%Y-%m-%d")
        b = Booking(studio_id=Studio.query.first().id, teacher_id=t.id,
                    date=d, start=start, end=f"{int(start[:2]) + 1:02d}:00",
                    status="done")
        db.session.add(b)
        db.session.commit()
        return t.id, b.id


def test_status_done_creates_survey(app, admin_client, post):
    from models.billing import Teacher
    from models.studio import Studio, Booking
    from models.feedback import Survey
    from core.timeutils import now_tashkent
    with app.app_context():
        t = Teacher(name="Fikr Ustoz", is_active=True)
        db.session.add(t)
        db.session.flush()
        d = (now_tashkent().date() + timedelta(days=430)).strftime("%Y-%m-%d")
        b = Booking(studio_id=Studio.query.first().id, teacher_id=t.id,
                    date=d, start="12:00", end="13:00", status="active")
        db.session.add(b)
        db.session.commit()
        bid = b.id
    post(admin_client, f"/bookings/{bid}/status", status="done")
    with app.app_context():
        s = Survey.query.filter_by(booking_id=bid).first()
        assert s is not None and s.status == "pending" and len(s.token) >= 16


def test_survey_cooldown_per_client(app):
    """Bitta mijozga 21 kun ichida bittadan ortiq so'rovnoma ketmaydi."""
    from core.feedback import create_survey_for_booking
    from models.studio import Booking
    from models.feedback import Survey
    tid, bid = _done_booking(app, "Charchamasin")
    with app.app_context():
        b1 = Booking.query.get(bid)
        assert create_survey_for_booking(b1, send=False) is not None
        b2 = Booking(studio_id=b1.studio_id, teacher_id=tid, date=b1.date,
                     start="15:00", end="16:00", status="done")
        db.session.add(b2)
        db.session.commit()
        assert create_survey_for_booking(b2, send=False) is None
        assert Survey.query.filter_by(teacher_id=tid).count() == 1
        # Idempotent: o'sha bron uchun qayta chaqirish — o'sha so'rovnoma
        assert create_survey_for_booking(b1, send=False).booking_id == bid


def test_public_survey_flow_happy(app, client):
    from core.feedback import create_survey_for_booking
    from models.studio import Booking
    from models.feedback import Survey
    from models.communication import Task
    tid, bid = _done_booking(app, "Mamnun Mijoz", start="09:00")
    with app.app_context():
        tok = create_survey_for_booking(Booking.query.get(bid),
                                        send=False).token
    r = client.get(f"/survey/{tok}")
    assert r.status_code == 200 and "Fikringiz".encode() in r.data
    # Umumiy baho majburiy
    r = client.post(f"/survey/{tok}", data={"recommend": "10"})
    assert "umumiy".encode() in r.data
    with app.app_context():
        assert Survey.query.filter_by(token=tok).first().status == "pending"
    r = client.post(f"/survey/{tok}", data={
        "overall": "5", "tech": "5", "operator": "4", "comfort": "5",
        "value": "4", "recommend": "10", "comment": "Zo'r studiya!"})
    assert r.status_code == 200 and "Rahmat".encode() in r.data
    assert "ulashish".encode() in r.data          # tarafdor → tavsiya taklifi
    with app.app_context():
        s = Survey.query.filter_by(token=tok).first()
        assert s.status == "done" and s.overall == 5 and s.recommend == 10
        assert not s.is_unhappy
        assert Task.query.filter(Task.title.like("%Mamnun Mijoz%")).count() == 0
    # Ikkinchi marta — «allaqachon baholagansiz», o'zgarmaydi
    client.post(f"/survey/{tok}", data={"overall": "1"})
    with app.app_context():
        assert Survey.query.filter_by(token=tok).first().overall == 5


def test_unhappy_client_creates_urgent_task(app, client):
    from core.feedback import create_survey_for_booking
    from models.studio import Booking
    from models.communication import Task
    tid, bid = _done_booking(app, "Norozi Mijoz", start="13:00")
    with app.app_context():
        tok = create_survey_for_booking(Booking.query.get(bid),
                                        send=False).token
    client.post(f"/survey/{tok}", data={
        "overall": "2", "tech": "1", "issue_tech": "Mikrofon shovqin berdi",
        "recommend": "3"})
    with app.app_context():
        t = Task.query.filter(Task.title.like("%Norozi Mijoz%")).first()
        assert t is not None and t.priority == "urgent"
        assert t.target_role == "admin" and "Mikrofon" in t.description


def test_bad_token_404(client):
    assert client.get("/survey/short").status_code == 404
    assert client.get("/survey/" + "x" * 30).status_code == 404


def test_survey_stats_nps(app):
    from core.feedback import survey_stats
    from models.feedback import Survey
    with app.app_context():
        Survey.query.delete()
        db.session.commit()
    rows = [(5, 10), (5, 9), (4, 8), (2, 3)]
    for i, (ov, rec) in enumerate(rows):
        tid, bid = _done_booking(app, f"NPS {i}", start=f"{10 + i}:00")
        with app.app_context():
            db.session.add(Survey(
                booking_id=bid, teacher_id=tid, token=Survey.new_token(),
                status="done", overall=ov, tech=ov, recommend=rec,
                done_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M")))
            db.session.commit()
    with app.app_context():
        st = survey_stats(90)
        assert st["done"] == 4 and st["promoters"] == 2
        assert st["detractors"] == 1 and st["nps"] == 25
        assert st["avg"] == 4.0 and st["unhappy"] == 1


def test_portal_shows_pending_survey(app, client):
    from core.feedback import create_survey_for_booking
    from models.studio import Booking
    from models.billing import Teacher
    tid, bid = _done_booking(app, "Portal Fikr", start="16:00")
    with app.app_context():
        t = Teacher.query.get(tid)
        tok = t.ensure_token()
        db.session.commit()
        stok = create_survey_for_booking(Booking.query.get(bid),
                                         send=False).token
    r = client.get(f"/my/{tok}")
    assert r.status_code == 200 and stok.encode() in r.data


def test_analytics_has_feedback_card(admin_client):
    r = admin_client.get("/analytics")
    assert r.status_code == 200 and "Mijoz fikri".encode() in r.data
