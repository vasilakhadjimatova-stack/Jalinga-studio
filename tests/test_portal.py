"""Ustoz portali: token xavfsizligi, online bron, 24 soat bekor siyosati."""
from datetime import timedelta


def _mk_teacher_with_token(app, name="Portal Ustoz", hours=0):
    from models.billing import Teacher, Payment
    from core.timeutils import today_iso
    from database import db
    with app.app_context():
        t = Teacher(name=name)
        t.ensure_token()
        db.session.add(t)
        db.session.flush()
        if hours:
            db.session.add(Payment(teacher_id=t.id, kind="package",
                                   hours=hours, amount=hours * 250000,
                                   date=today_iso(), is_paid=True))
        db.session.commit()
        return t.id, t.portal_token


def _studio_id(app):
    from models.studio import Studio
    with app.app_context():
        return Studio.query.first().id


def _future(days=3, hh="10:00"):
    from core.timeutils import now_tashkent
    return ((now_tashkent() + timedelta(days=days)).strftime("%Y-%m-%d"), hh)


# ── Token xavfsizligi ──
def test_portal_requires_valid_token(app, client):
    _tid, token = _mk_teacher_with_token(app)
    assert client.get(f"/my/{token}").status_code == 200
    assert client.get("/my/notogritoken12345678").status_code == 404
    assert client.get("/my/x").status_code == 404


def test_portal_shows_balance(app, client):
    _tid, token = _mk_teacher_with_token(app, name="Balansli Ustoz", hours=10)
    r = client.get(f"/my/{token}")
    assert r.status_code == 200
    assert b"Balansli Ustoz" in r.data
    assert b"10.0 soat" in r.data or b"10 soat" in r.data


# ── Online bron ──
def test_portal_booking_package(app, client):
    from models.studio import Booking
    from models.billing import Teacher
    tid, token = _mk_teacher_with_token(app, name="Online Bron", hours=10)
    sid = _studio_id(app)
    day, hh = _future(3)
    r = client.post(f"/my/{token}/book", data={
        "studio_id": sid, "date": day, "start": hh, "hours": "2",
        "pay_type": "package"})
    assert r.status_code in (302, 303)
    with app.app_context():
        b = Booking.query.filter_by(teacher_id=tid).first()
        assert b is not None and b.hours == 2
        assert b.created_by.startswith("portal:")
        assert Teacher.query.get(tid).balance_hours() == 8


def test_portal_booking_conflict_blocked(app, client):
    from models.studio import Booking
    tid, token = _mk_teacher_with_token(app, name="Konflikt Portal", hours=10)
    sid = _studio_id(app)
    day, _ = _future(4)
    client.post(f"/my/{token}/book", data={
        "studio_id": sid, "date": day, "start": "10:00", "hours": "2",
        "pay_type": "package"})
    # ustma-ust — bloklanadi
    client.post(f"/my/{token}/book", data={
        "studio_id": sid, "date": day, "start": "11:00", "hours": "1",
        "pay_type": "package"})
    with app.app_context():
        assert Booking.query.filter_by(teacher_id=tid, date=day).count() == 1


def test_portal_booking_past_blocked(app, client):
    from models.studio import Booking
    tid, token = _mk_teacher_with_token(app, name="Otgan Vaqt", hours=5)
    sid = _studio_id(app)
    r = client.post(f"/my/{token}/book", data={
        "studio_id": sid, "date": "2020-01-01", "start": "10:00",
        "hours": "1", "pay_type": "package"})
    with app.app_context():
        assert Booking.query.filter_by(teacher_id=tid).count() == 0


def test_portal_no_balance_hourly_payment(app, client):
    """Balanssiz ustoz soatbay bron qiladi → kutilayotgan to'lov yoziladi."""
    from models.billing import Payment
    from models.studio import Booking
    tid, token = _mk_teacher_with_token(app, name="Soatbay Portal", hours=0)
    sid = _studio_id(app)
    day, hh = _future(5)
    client.post(f"/my/{token}/book", data={
        "studio_id": sid, "date": day, "start": hh, "hours": "1",
        "pay_type": "hourly"})
    with app.app_context():
        b = Booking.query.filter_by(teacher_id=tid).first()
        assert b is not None
        p = Payment.query.filter_by(booking_id=b.id).first()
        assert p is not None and p.is_paid is False and p.amount > 0


# ── Bekor qilish siyosati ──
def test_portal_cancel_policy(app, client):
    from models.studio import Booking
    from models.billing import Teacher
    from database import db
    from core.timeutils import now_tashkent
    tid, token = _mk_teacher_with_token(app, name="Bekor Ustoz", hours=10)
    sid = _studio_id(app)
    # 8 kun keyingi bron — bekor QILINADI (>24h); boshqa testlar bilan
    # to'qnashmasligi uchun alohida kun/soat
    day, hh = _future(8, "13:00")
    client.post(f"/my/{token}/book", data={
        "studio_id": sid, "date": day, "start": hh, "hours": "2",
        "pay_type": "package"})
    with app.app_context():
        b1 = Booking.query.filter_by(teacher_id=tid, date=day).first().id
    r = client.post(f"/my/{token}/cancel/{b1}")
    with app.app_context():
        assert Booking.query.get(b1).status == "cancelled"
        assert Teacher.query.get(tid).balance_hours() == 10   # soat qaytdi
    # 2 soat keyingi bron — bekor QILINMAYDI (<24h)
    soon = now_tashkent() + timedelta(hours=2)
    with app.app_context():
        b2 = Booking(studio_id=sid, teacher_id=tid,
                     date=soon.strftime("%Y-%m-%d"),
                     start=soon.strftime("%H:%M"),
                     end=(soon + timedelta(hours=1)).strftime("%H:%M"),
                     pay_type="package", status="active")
        db.session.add(b2); db.session.commit()
        b2id = b2.id
    client.post(f"/my/{token}/cancel/{b2id}")
    with app.app_context():
        assert Booking.query.get(b2id).status == "active"   # o'zgarmadi


def test_portal_cannot_cancel_others_booking(app, client):
    """Bir ustoz boshqasining bronini bekor qila olmaydi (404)."""
    from models.studio import Booking
    tid1, token1 = _mk_teacher_with_token(app, name="Egasi", hours=5)
    _tid2, token2 = _mk_teacher_with_token(app, name="Begona", hours=5)
    sid = _studio_id(app)
    day, hh = _future(6)
    client.post(f"/my/{token1}/book", data={
        "studio_id": sid, "date": day, "start": hh, "hours": "1",
        "pay_type": "package"})
    with app.app_context():
        bid = Booking.query.filter_by(teacher_id=tid1, date=day).first().id
    r = client.post(f"/my/{token2}/cancel/{bid}")
    assert r.status_code == 404
    with app.app_context():
        assert Booking.query.get(bid).status == "active"
