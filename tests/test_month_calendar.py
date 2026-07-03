"""Oylik kalendar (yagona ko'rinish) — grid, studiya filtri, ko'p kunlik bron."""


def _mk_teacher(app, name, hours=0):
    from models.billing import Teacher, Payment
    from core.timeutils import today_iso
    from database import db
    with app.app_context():
        t = Teacher(name=name)
        db.session.add(t); db.session.flush()
        if hours:
            db.session.add(Payment(teacher_id=t.id, kind="package",
                                   hours=hours, amount=hours * 250000,
                                   date=today_iso(), is_paid=True))
        db.session.commit()
        return t.id


def test_month_view_shows_bookings(app, admin_client, post):
    from models.studio import Studio
    with app.app_context():
        sid = Studio.query.first().id
    tid = _mk_teacher(app, "Oylik Ustoz")
    post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
         date="2026-11-05", start="10:00", end="12:00", pay_type="hourly")

    r = admin_client.get("/calendar?year=2026&month=11")
    html = r.data.decode()
    assert r.status_code == 200
    assert "Noyabr 2026" in html
    assert "10:00 Oylik Ustoz" in html          # bron chipi ko'rinadi
    assert "Barcha studiyalar" in html          # studiya tablari


def test_month_view_studio_filter(app, admin_client, post):
    """Studiya tanlansa — faqat o'sha studiyaning bronlari ko'rinadi."""
    from database import db
    from models.studio import Studio
    with app.app_context():
        s1 = Studio.query.first()
        s2 = Studio(name="Filter Studio B", hourly_rate=100000)
        db.session.add(s2); db.session.commit()
        sid1, sid2 = s1.id, s2.id
    t1 = _mk_teacher(app, "FiltrA Ustoz")
    t2 = _mk_teacher(app, "FiltrB Ustoz")
    post(admin_client, "/bookings/save", studio_id=sid1, teacher_id=t1,
         date="2026-12-03", start="09:00", end="10:00", pay_type="hourly")
    post(admin_client, "/bookings/save", studio_id=sid2, teacher_id=t2,
         date="2026-12-03", start="09:00", end="10:00", pay_type="hourly")

    r = admin_client.get(f"/calendar?year=2026&month=12&studio={sid2}")
    html = r.data.decode()
    assert "FiltrB Ustoz" in html
    assert "09:00 FiltrA Ustoz" not in html     # boshqa studiya chiqmaydi


def test_month_view_invalid_month_rolls_over(app, admin_client):
    """month=13 → keyingi yil yanvarga o'giriladi (Impulse'dagidek)."""
    r = admin_client.get("/calendar?year=2026&month=13")
    assert r.status_code == 200
    assert "Yanvar 2027" in r.data.decode()


def test_calendar_date_param_opens_right_month(app, admin_client):
    """Eski ?date= havolalari o'sha oyning oylik ko'rinishini ochadi."""
    r = admin_client.get("/calendar?date=2027-03-15")
    assert r.status_code == 200
    assert "Mart 2027" in r.data.decode()


def test_old_month_url_redirects(app, admin_client):
    r = admin_client.get("/calendar/month?year=2026&month=5")
    assert r.status_code == 302
    assert "/calendar" in r.headers["Location"]


def test_studios_page_links_to_calendar(app, admin_client):
    r = admin_client.get("/studios")
    assert "/calendar?studio=" in r.data.decode()


# ── Ko'p kunlik bron ──
def test_multi_day_booking_creates_all_free_days(app, admin_client, post):
    """3 kun so'raladi, bittasi band → 2 tasi yaratiladi, band kun xato
    sifatida ko'rsatiladi; har soatbay bronga alohida to'lov yoziladi."""
    from models.studio import Studio, Booking
    from models.billing import Payment
    with app.app_context():
        sid = Studio.query.first().id
    busy = _mk_teacher(app, "Band Ustoz")
    post(admin_client, "/bookings/save", studio_id=sid, teacher_id=busy,
         date="2027-01-05", start="10:00", end="12:00", pay_type="hourly")

    tid = _mk_teacher(app, "KopKun Ustoz")
    r = post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
             date=["2027-01-04", "2027-01-05", "2027-01-06"],
             start="10:00", end="12:00", pay_type="hourly")
    assert r.status_code == 302
    with app.app_context():
        got = [b.date for b in Booking.query.filter_by(teacher_id=tid).all()]
        assert sorted(got) == ["2027-01-04", "2027-01-06"]   # band kun tushib qoldi
        pays = Payment.query.filter_by(teacher_id=tid, is_paid=False).count()
        assert pays == 2                                     # har kunga to'lov


def test_multi_day_package_stops_when_balance_runs_out(app, admin_client, post):
    """4 soat paket, 3 kun × 2 soat so'raladi → faqat 2 kun yoziladi."""
    from models.studio import Studio, Booking
    with app.app_context():
        sid = Studio.query.first().id
    tid = _mk_teacher(app, "PaketKop Ustoz", hours=4)
    post(admin_client, "/bookings/save", studio_id=sid, teacher_id=tid,
         date=["2027-02-01", "2027-02-02", "2027-02-03"],
         start="14:00", end="16:00", pay_type="package")
    with app.app_context():
        got = sorted(b.date for b in Booking.query.filter_by(teacher_id=tid).all())
        assert got == ["2027-02-01", "2027-02-02"]           # 3-kunga balans yetmadi
