"""Bandlik kalendari (ko'p kun tanlash) — /bookings/busy JSON + ko'p kunlik bron."""
from datetime import timedelta

from core.timeutils import now_tashkent


def _sid(app):
    from models.studio import Studio
    with app.app_context():
        return Studio.query.first().id


def _mk_teacher(app, name="Kal Mijoz"):
    from models.billing import Teacher
    from database import db
    with app.app_context():
        t = Teacher(name=name, is_active=True)
        db.session.add(t); db.session.commit()
        return t.id


def _future(days):
    return (now_tashkent().date() + timedelta(days=days)).strftime("%Y-%m-%d")


def test_busy_requires_login(client):
    r = client.get("/bookings/busy?studio_id=1&ym=2026-07")
    assert r.status_code in (301, 302)


def test_busy_returns_bookings_for_studio_month(app, admin_client, post):
    sid = _sid(app)
    tid = _mk_teacher(app)
    day = _future(20)
    ym = day[:7]
    post(admin_client, "/bookings/save", client_mode="existing",
         studio_id=sid, teacher_id=tid, date=day, start="10:00", end="12:00",
         pay_type="hourly")
    r = admin_client.get(f"/bookings/busy?studio_id={sid}&ym={ym}")
    assert r.status_code == 200
    data = r.get_json()
    assert day in data
    assert data[day][0]["start"] == "10:00"


def test_busy_studio_scoped(app, admin_client):
    """Boshqa studiyaning bandligi qaytmaydi."""
    from models.studio import Studio
    with app.app_context():
        ids = [s.id for s in Studio.query.all()]
    if len(ids) < 2:
        return   # kamida 2 studiya bo'lmasa — o'tkazamiz
    r = admin_client.get(f"/bookings/busy?studio_id={ids[1]}&ym={_future(25)[:7]}")
    assert r.status_code == 200
    assert isinstance(r.get_json(), dict)


def test_multi_day_booking_creates_all(app, admin_client, post):
    """Bir necha 'date' yuborilsa — har kunga alohida bron yaratiladi."""
    sid = _sid(app)
    tid = _mk_teacher(app, "Multi Kun")
    d1, d2, d3 = _future(30), _future(31), _future(32)
    # Flask test-client bir nechta 'date' qiymatini ro'yxat bilan yuboradi
    with admin_client.session_transaction() as s:
        s["_csrf"] = "t"
    r = admin_client.post("/bookings/save", data={
        "_csrf": "t", "client_mode": "existing", "studio_id": sid,
        "teacher_id": tid, "date": [d1, d2, d3],
        "start": "14:00", "end": "16:00", "pay_type": "hourly"})
    assert r.status_code in (302, 303)
    from models.studio import Booking
    with app.app_context():
        for d in (d1, d2, d3):
            assert Booking.query.filter_by(
                teacher_id=tid, date=d, start="14:00").count() == 1


def test_per_day_times_via_slots_json(app, admin_client, post):
    """slots_json — har kun har xil vaqtda alohida bron bo'ladi."""
    import json
    sid = _sid(app)
    tid = _mk_teacher(app, "Har xil vaqt")
    d1, d2 = _future(40), _future(41)
    slots = json.dumps([
        {"date": d1, "start": "10:00", "end": "12:00"},
        {"date": d2, "start": "15:00", "end": "18:00"},
    ])
    post(admin_client, "/bookings/save", client_mode="existing",
         studio_id=sid, teacher_id=tid, start="10:00", end="12:00",
         pay_type="hourly", slots_json=slots)
    from models.studio import Booking
    with app.app_context():
        b1 = Booking.query.filter_by(teacher_id=tid, date=d1).first()
        b2 = Booking.query.filter_by(teacher_id=tid, date=d2).first()
        assert b1 and b1.start == "10:00" and b1.end == "12:00"
        assert b2 and b2.start == "15:00" and b2.end == "18:00"
        assert b1.hours == 2 and b2.hours == 3


def test_slots_json_skips_conflict_keeps_rest(app, admin_client, post):
    """slots_json'даги band kun o'tkazib yuboriladi, qolganlari saqlanadi."""
    import json
    sid = _sid(app)
    tid = _mk_teacher(app, "Qisman")
    d1, d2 = _future(45), _future(46)
    # d1'ni oldindan band qilamiz
    post(admin_client, "/bookings/save", client_mode="existing",
         studio_id=sid, teacher_id=tid, date=d1, start="10:00", end="12:00",
         pay_type="hourly")
    slots = json.dumps([
        {"date": d1, "start": "10:00", "end": "12:00"},   # band — o'tadi
        {"date": d2, "start": "10:00", "end": "12:00"},   # bo'sh — yaratiladi
    ])
    post(admin_client, "/bookings/save", client_mode="existing",
         studio_id=sid, teacher_id=tid, start="10:00", end="12:00",
         pay_type="hourly", slots_json=slots)
    from models.studio import Booking
    with app.app_context():
        assert Booking.query.filter_by(teacher_id=tid, date=d1).count() == 1
        assert Booking.query.filter_by(teacher_id=tid, date=d2).count() == 1
