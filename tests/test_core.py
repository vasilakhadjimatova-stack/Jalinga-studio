"""Jalinga MVP yadrosi: kirish, bron konflikti, paket balansi, moliya."""
from datetime import date, timedelta

from core.timeutils import now_tashkent


def _future(days):
    """Boshqa test fayllari bilan to'qnashmaydigan nisbiy kelajak sanasi.

    Qat'iy sana (masalan «2026-08-10») vaqt o'tishi bilan boshqa testlarning
    now+N kunларига to'g'ri kelib flake beradi — shuning uchun nisbiy."""
    return (now_tashkent().date() + timedelta(days=days)).strftime("%Y-%m-%d")


def _mk_teacher(app, name="Ustoz Test", **kw):
    from models.billing import Teacher
    from database import db
    with app.app_context():
        t = Teacher(name=name, **kw)
        db.session.add(t); db.session.commit()
        return t.id


def _studio_id(app):
    from models.studio import Studio
    with app.app_context():
        return Studio.query.first().id


# ── Kirish ──
def test_login_required_redirect(client):
    r = client.get("/")
    assert r.status_code in (301, 302)
    assert "/login" in r.headers.get("Location", "")


def test_login_ok(client):
    r = client.post("/login", data={"code": "111111"})
    assert r.status_code in (302, 303)
    r2 = client.get("/")
    assert r2.status_code == 200
    assert "Boshqaruv paneli".encode() in r2.data


def test_login_wrong_code(client):
    r = client.post("/login", data={"code": "000000"})
    assert b"Kod noto" in r.data   # "noto'g'ri" (apostrof HTML-qochiriladi)


# ── Bron: konflikt himoyasi ──
def test_booking_conflict_blocked(app, admin_client, post):
    from models.studio import Booking
    sid = _studio_id(app)
    tid = _mk_teacher(app, "Konflikt Ustoz")
    day = _future(35)   # 35 — boshqa testlarда ishlatilmaydigan offset
    r1 = post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
              date=day, start="10:00", end="12:00", pay_type="hourly")
    assert r1.status_code in (302, 303)
    with app.app_context():
        assert Booking.query.filter_by(date=day).count() == 1
    # Ustma-ust (11:00–13:00) — bloklanadi
    r2 = post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
              date=day, start="11:00", end="13:00", pay_type="hourly")
    with app.app_context():
        assert Booking.query.filter_by(date=day).count() == 1   # yaratilmadi
    # Tegmaydigan vaqt (12:00–14:00) — ruxsat
    r3 = post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
              date=day, start="12:00", end="14:00", pay_type="hourly")
    with app.app_context():
        assert Booking.query.filter_by(date=day).count() == 2


# ── Paket balansi ──
def test_package_balance_flow(app, admin_client, post):
    from models.billing import Teacher
    from models.studio import Booking
    sid = _studio_id(app)
    tid = _mk_teacher(app, "Paket Ustoz")
    # 1) Balanssiz paket-bron → bloklanadi
    r = post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
             date=_future(36), start="10:00", end="12:00", pay_type="package")
    with app.app_context():
        assert Booking.query.filter_by(teacher_id=tid).count() == 0
    # 2) 10 soatlik paket sotamiz
    r = post(admin_client, f"/teachers/{tid}/package",
             hours="10", amount="2500000", method="naqd")
    assert r.status_code in (302, 303)
    with app.app_context():
        assert Teacher.query.get(tid).balance_hours() == 10
    # 3) Endi 2 soatlik paket-bron o'tadi, balans 8 ga tushadi
    r = post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
             date=_future(36), start="10:00", end="12:00", pay_type="package")
    with app.app_context():
        assert Booking.query.filter_by(teacher_id=tid).count() == 1
        assert Teacher.query.get(tid).balance_hours() == 8
    # 4) Bekor qilinsa soatlar qaytadi
    with app.app_context():
        bid = Booking.query.filter_by(teacher_id=tid).first().id
    post(admin_client, f"/bookings/{bid}/status", status="cancelled")
    with app.app_context():
        assert Teacher.query.get(tid).balance_hours() == 10


# ── Soatbay: to'lov yoziladi, bekorda o'chadi ──
def test_hourly_payment_lifecycle(app, admin_client, post):
    from models.billing import Payment
    from models.studio import Booking, Studio
    sid = _studio_id(app)
    tid = _mk_teacher(app, "Soatbay Ustoz")
    post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
         date=_future(37), start="14:00", end="16:00", pay_type="hourly")
    with app.app_context():
        b = Booking.query.filter_by(teacher_id=tid).first()
        p = Payment.query.filter_by(booking_id=b.id).first()
        rate = Studio.query.get(sid).hourly_rate
        assert p is not None and p.is_paid is False
        assert p.amount == round(2 * rate)      # 2 soat × narx
        bid = b.id
    # bekor → kutilayotgan to'lov o'chadi
    post(admin_client, f"/bookings/{bid}/status", status="cancelled")
    with app.app_context():
        assert Payment.query.filter_by(booking_id=bid).count() == 0


# ── Sahifalar ochiladi ──
def test_pages_render(admin_client):
    for url in ("/", "/calendar", "/teachers", "/studios", "/finance"):
        r = admin_client.get(url)
        assert r.status_code == 200, url
