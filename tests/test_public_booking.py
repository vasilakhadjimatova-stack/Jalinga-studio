"""Ochiq online bron — mijoz o'zi band qiladi (login/parolsiz).

Bron aktiv yaratiladi, mijoz telefon bo'yicha topiladi/yaratiladi, soatbay
to'lov (kutilmoqda) yoziladi; konflikt/ish-vaqti/spam himoyalari ishlaydi.
"""
from datetime import timedelta

from core.timeutils import now_tashkent


def _sid(app):
    from models.studio import Studio
    with app.app_context():
        return Studio.query.first().id


def _future(days=10, hh="10:00"):
    d = (now_tashkent().date() + timedelta(days=days)).strftime("%Y-%m-%d")
    return d, hh


def test_public_page_open_no_login(client):
    r = client.get("/book")
    assert r.status_code == 200
    assert "Studiyani band".encode() in r.data


def test_slots_json(app, client):
    sid = _sid(app)
    day, _ = _future(11)
    r = client.get(f"/book/slots?studio_id={sid}&date={day}")
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True
    assert "busy" in j and "work_start" in j


def test_public_booking_creates_active_and_payment(app, client):
    sid = _sid(app)
    day, start = _future(12)
    r = client.post("/book/submit", data={
        "name": "Online Mijoz", "phone": "+998901234567",
        "studio_id": sid, "date": day, "start": start, "hours": "2"})
    assert r.status_code in (302, 303)
    assert "/book/done" in r.headers.get("Location", "")
    from models.studio import Booking
    from models.billing import Teacher, Payment
    with app.app_context():
        b = Booking.query.filter_by(date=day, start=start).first()
        assert b and b.status == "active"
        assert b.created_by.startswith("online:")
        t = Teacher.query.get(b.teacher_id)
        assert t and t.phone == "+998901234567"
        p = Payment.query.filter_by(booking_id=b.id).first()
        assert p and p.is_paid is False and p.kind == "hourly"


def test_public_booking_conflict_blocked(app, client):
    sid = _sid(app)
    day, start = _future(13)
    ok = client.post("/book/submit", data={
        "name": "A", "phone": "+998900000001", "studio_id": sid,
        "date": day, "start": start, "hours": "2"})
    assert "/book/done" in ok.headers.get("Location", "")
    from models.studio import Booking
    with app.app_context():
        n = Booking.query.filter_by(date=day).count()
    # 11:00 (start+1h) ustma-ust — bloklanadi
    client.post("/book/submit", data={
        "name": "B", "phone": "+998900000002", "studio_id": sid,
        "date": day, "start": "11:00", "hours": "2"})
    with app.app_context():
        assert Booking.query.filter_by(date=day).count() == n   # yangi yo'q


def test_public_booking_rejects_past(app, client):
    sid = _sid(app)
    past = (now_tashkent().date() - timedelta(days=1)).strftime("%Y-%m-%d")
    client.post("/book/submit", data={
        "name": "X", "phone": "+998900000009", "studio_id": sid,
        "date": past, "start": "10:00", "hours": "1"})
    from models.studio import Booking
    with app.app_context():
        assert Booking.query.filter_by(date=past).count() == 0   # yaratilmadi


def test_public_booking_reuses_teacher_by_phone(app, client):
    sid = _sid(app)
    d1, _ = _future(14)
    d2, _ = _future(15)
    client.post("/book/submit", data={
        "name": "Takror Mijoz", "phone": "+998911112222", "studio_id": sid,
        "date": d1, "start": "10:00", "hours": "1"})
    client.post("/book/submit", data={
        "name": "Takror Mijoz", "phone": "998 91 111 22 22", "studio_id": sid,
        "date": d2, "start": "10:00", "hours": "1"})
    from models.billing import Teacher
    with app.app_context():
        matches = [t for t in Teacher.query.all()
                   if "".join(c for c in (t.phone or "") if c.isdigit())[-9:]
                   == "911112222"]
    assert len(matches) == 1   # bitta mijoz (dublikat yaratilmadi)


def test_honeypot_silently_rejected(app, client):
    sid = _sid(app)
    day, start = _future(16)
    r = client.post("/book/submit", data={
        "name": "Bot", "phone": "+998900000077", "studio_id": sid,
        "date": day, "start": start, "hours": "1", "website": "spam"})
    assert "/book/done" in r.headers.get("Location", "")
    from models.studio import Booking
    with app.app_context():
        assert Booking.query.filter_by(date=day).count() == 0   # yaratilmadi
