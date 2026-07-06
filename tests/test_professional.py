"""Professional mantiq: ish vaqti, tahrirlash, noshow, jamoa, xavfsizlik, dedup."""
from datetime import date, timedelta


def _mk_teacher(app, name, hours=0, phone=""):
    from models.billing import Teacher, Payment
    from core.timeutils import today_iso
    from database import db
    with app.app_context():
        t = Teacher(name=name, phone=phone)
        db.session.add(t); db.session.flush()
        if hours:
            db.session.add(Payment(teacher_id=t.id, kind="package",
                                   hours=hours, amount=hours*250000,
                                   date=today_iso(), is_paid=True))
        db.session.commit()
        return t.id


def _sid(app):
    from models.studio import Studio
    with app.app_context():
        return Studio.query.first().id


# ── 1. Ish vaqti chegarasi ──
def test_work_hours_enforced(app, admin_client, post):
    from models.studio import Booking
    tid = _mk_teacher(app, "IshVaqt Ustoz")
    sid = _sid(app)
    # 07:00 — ish vaqtidan tashqari, bloklanadi
    post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
         date="2026-10-01", start="07:00", end="09:00", pay_type="hourly")
    with app.app_context():
        assert Booking.query.filter_by(teacher_id=tid).count() == 0
    # 22:00 gacha — tashqari, bloklanadi
    post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
         date="2026-10-01", start="20:00", end="22:00", pay_type="hourly")
    with app.app_context():
        assert Booking.query.filter_by(teacher_id=tid).count() == 0
    # 09:00–11:00 — ichida, o'tadi
    post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
         date="2026-10-01", start="09:00", end="11:00", pay_type="hourly")
    with app.app_context():
        assert Booking.query.filter_by(teacher_id=tid).count() == 1


# ── 2. Bronni tahrirlash (reschedule) ──
def test_booking_edit_flow(app, admin_client, post):
    from models.studio import Booking, Studio
    from models.billing import Payment
    tid = _mk_teacher(app, "Edit Ustoz")
    sid = _sid(app)
    post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
         date="2026-10-02", start="10:00", end="12:00", pay_type="hourly")
    with app.app_context():
        b = Booking.query.filter_by(teacher_id=tid).first()
        bid, rate = b.id, Studio.query.get(sid).hourly_rate
    # Boshqa bron bilan to'qnashuvga ko'chirish — bloklanadi
    tid2 = _mk_teacher(app, "Edit Ustoz 2")
    post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid2,
         date="2026-10-02", start="14:00", end="16:00", pay_type="hourly")
    post(admin_client, f"/bookings/{bid}/edit", studio_id=sid,
         date="2026-10-02", start="15:00", end="17:00")
    with app.app_context():
        assert Booking.query.get(bid).start == "10:00"   # o'zgarmadi
    # Bo'sh vaqtga 3 soatga ko'chirish — o'tadi, to'lov yangilanadi
    post(admin_client, f"/bookings/{bid}/edit", studio_id=sid,
         date="2026-10-03", start="09:00", end="12:00")
    with app.app_context():
        b = Booking.query.get(bid)
        assert b.date == "2026-10-03" and b.hours == 3
        p = Payment.query.filter_by(booking_id=bid, is_paid=False).first()
        assert p.amount == round(3 * rate)               # summa yangilandi


def test_booking_edit_package_balance_guard(app, admin_client, post):
    """Paket bronni uzaytirishда balans yetmasa — bloklanadi."""
    from models.studio import Booking
    tid = _mk_teacher(app, "EditPaket Ustoz", hours=2)
    sid = _sid(app)
    post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
         date="2026-10-04", start="10:00", end="12:00", pay_type="package")
    with app.app_context():
        bid = Booking.query.filter_by(teacher_id=tid).first().id
    # 2 soatlik balans bilan 4 soatga uzaytirish — yo'q
    post(admin_client, f"/bookings/{bid}/edit", studio_id=sid,
         date="2026-10-04", start="10:00", end="14:00")
    with app.app_context():
        assert Booking.query.get(bid).hours == 2


# ── 3. Noshow paket soatini kuydiradi ──
def test_noshow_burns_package_hours(app, admin_client, post):
    from models.studio import Booking
    from models.billing import Teacher
    tid = _mk_teacher(app, "Noshow Ustoz", hours=10)
    sid = _sid(app)
    post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
         date="2026-10-05", start="10:00", end="12:00", pay_type="package")
    with app.app_context():
        bid = Booking.query.filter_by(teacher_id=tid).first().id
        assert Teacher.query.get(tid).balance_hours() == 8
    post(admin_client, f"/bookings/{bid}/status", status="noshow")
    with app.app_context():
        assert Teacher.query.get(tid).balance_hours() == 8   # kuydi (qaytmadi)
    # Bekor esa qaytaradi
    post(admin_client, f"/bookings/{bid}/status", status="cancelled")
    with app.app_context():
        assert Teacher.query.get(tid).balance_hours() == 10


# ── 5. Jamoa boshqaruvi ──
def test_team_add_and_guards(app, admin_client, post):
    from models.user import User
    r = post(admin_client, "/team/save", name="Operator Ali", code="778899",
             role="operator", is_active="1")
    assert r.status_code in (302, 303)
    with app.app_context():
        u = User.query.filter_by(code="778899").first()
        assert u is not None and u.role == "operator"
    # Kod dublikati — rad
    post(admin_client, "/team/save", name="Boshqa", code="778899",
         role="operator", is_active="1")
    with app.app_context():
        assert User.query.filter_by(code="778899").count() == 1
    # Oxirgi faol adminni faolsizlantirish — rad
    with app.app_context():
        admin = User.query.filter_by(role="admin", is_active=True).first()
        aid = admin.id
        n_admins = User.query.filter_by(role="admin", is_active=True).count()
    if n_admins == 1:
        post(admin_client, "/team/save", id=aid, name="Rahbar",
             role="operator", is_active="1")
        with app.app_context():
            assert User.query.get(aid).role == "admin"   # o'zgarmadi


def test_team_admin_only(app, post):
    """Operator /team ga kira olmaydi."""
    from models.user import User
    from database import db
    with app.app_context():
        if not User.query.filter_by(code="556677").first():
            db.session.add(User(name="Op", code="556677", role="operator"))
            db.session.commit()
    c = app.test_client()
    c.post("/login", data={"code": "556677"})
    r = c.get("/team")
    assert r.status_code in (302, 303)   # dashboardga qaytariladi


# ── 6. Login rate-limit ──
def test_login_rate_limit(app):
    from core.auth import _FAILED
    _FAILED.clear()
    c = app.test_client()
    for _ in range(5):
        c.post("/login", data={"code": "000000"},
               environ_base={"REMOTE_ADDR": "10.9.9.9"})
    # 6-urinish TO'G'RI kod bilan ham bloklanadi
    r = c.post("/login", data={"code": "111111"},
               environ_base={"REMOTE_ADDR": "10.9.9.9"})
    assert "Juda ko'p urinish".encode() in r.data or b"Juda ko" in r.data
    _FAILED.clear()   # boshqa testlarga xalaqit bermasin


# ── 7. Ustoz telefon dedup ──
def test_teacher_phone_dedup(app, admin_client, post):
    from models.billing import Teacher
    _mk_teacher(app, "Dedup Ustoz", phone="+998 90 555 33 22")
    with app.app_context():
        before = Teacher.query.count()
    post(admin_client, "/teachers/save", name="Boshqa Nom",
         phone="998905553322")   # bir xil raqam, boshqa format
    with app.app_context():
        assert Teacher.query.count() == before   # yaratilmadi


# ── 8. ADMIN_CODE env asosiy admin kodini yangilaydi (Railway) ──
def test_admin_code_env_syncs_existing_admin(app):
    """ADMIN_CODE o'zgarсa — mavjud asosiy admin kodi ham yangilanadi
    (baza allaqachon to'la bo'lsa ham). Holat 111111 ga tiklanadi."""
    import os
    from models.user import User
    from seed import seed_all
    old_env = os.environ.get("ADMIN_CODE")
    try:
        with app.app_context():
            os.environ["ADMIN_CODE"] = "902413"
            seed_all()
            a = User.query.filter_by(role="admin").order_by(User.id).first()
            assert a.code == "902413" and a.is_active
    finally:
        # Holatni tiklaymiz — boshqa testlar 111111 bilan kiradi
        with app.app_context():
            os.environ["ADMIN_CODE"] = "111111"
            seed_all()
            a = User.query.filter_by(role="admin").order_by(User.id).first()
            assert a.code == "111111"
        if old_env is None:
            os.environ.pop("ADMIN_CODE", None)
        else:
            os.environ["ADMIN_CODE"] = old_env


# ── 9. POST formalarda server tomonidan CSRF token bo'ladi (JS'ga bog'liq emas) ──
def test_forms_have_server_csrf(app, admin_client):
    """CSRF bug: forma ichida {{ csrf_token() }} yashirin maydon bo'lishi shart
    (service worker/JS eskirsa ham «Bad Request: CSRF token xato» chiqmasin)."""
    from models.billing import Teacher
    from database import db
    with app.app_context():
        t = Teacher(name="CSRF Form", is_active=True)
        db.session.add(t); db.session.commit(); tid = t.id
    for path in (f"/teachers/{tid}", "/finance/payments", "/team", "/pricing"):
        html = admin_client.get(path).get_data(as_text=True)
        assert 'name="_csrf"' in html, f"{path} formalarida server CSRF yo'q"
