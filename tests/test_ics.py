"""Kalendar obunasi (ICS): mijoz va xodim lentalari."""
from datetime import timedelta

from database import db


def _future_booking(app, name, days=450, start="10:00", end="12:00",
                    status="active"):
    from core.timeutils import now_tashkent
    from models.billing import Teacher
    from models.studio import Studio, Booking
    with app.app_context():
        t = Teacher(name=name, phone="+998 90 000 00 00", is_active=True)
        db.session.add(t)
        db.session.flush()
        tok = t.ensure_token()
        d = (now_tashkent().date() + timedelta(days=days % 170 + 1)
             ).strftime("%Y-%m-%d")
        b = Booking(studio_id=Studio.query.first().id, teacher_id=t.id,
                    date=d, start=start, end=end, status=status)
        db.session.add(b)
        db.session.commit()
        return tok, b.id, d


def test_ics_builder_format():
    from core.ics import build_calendar
    body = build_calendar("Test", [{
        "uid": "booking-1@jalinga", "date": "2026-10-10", "start": "10:00",
        "end": "11:30", "summary": "Ali; Vali, test",
        "description": "a\nb " + "x" * 120}], alarm_minutes=60)
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "DTSTART:20261010T050000Z" in body      # 10:00 Toshkent = 05:00 UTC
    assert "DTEND:20261010T063000Z" in body
    assert "SUMMARY:Ali\\; Vali\\, test" in body
    assert "TRIGGER:-PT60M" in body
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))


def test_client_feed(app, client):
    tok, bid, d = _future_booking(app, "ICS Mijoz", days=451)
    _future_booking(app, "Begona Mijoz", days=452, start="14:00", end="15:00")
    r = client.get(f"/my/{tok}/calendar.ics")
    assert r.status_code == 200 and r.mimetype == "text/calendar"
    body = r.data.decode()
    assert f"UID:booking-{bid}@jalinga" in body
    assert body.count("BEGIN:VEVENT") == 1         # faqat o'z bronlari
    assert "VALARM" in body
    assert client.get("/my/" + "z" * 24 + "/calendar.ics").status_code == 404


def test_cancelled_not_in_feed(app, client):
    tok, bid, d = _future_booking(app, "ICS Bekor", days=453, start="16:00",
                                  end="17:00", status="cancelled")
    r = client.get(f"/my/{tok}/calendar.ics")
    assert "BEGIN:VEVENT" not in r.data.decode()


def test_staff_feed_and_reset(app, admin_client, post):
    from models.user import User
    _future_booking(app, "Xodim Lenta", days=454, start="18:00", end="19:00")
    r = admin_client.get("/calendar")
    assert r.status_code == 200 and b"/calendar/feed/" in r.data
    with app.app_context():
        tok = User.query.filter_by(code="111111").first().feed_token
    assert len(tok) >= 16
    r = admin_client.get(f"/calendar/feed/{tok}.ics")     # cookie shart emas
    assert r.status_code == 200 and "Xodim Lenta".encode() in r.data
    post(admin_client, "/calendar/feed/reset")
    assert admin_client.get(f"/calendar/feed/{tok}.ics").status_code == 404
    assert admin_client.get("/calendar/feed/short.ics").status_code == 404
