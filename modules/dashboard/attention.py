"""«Bugun e'tibor» — rahbar e'tiborini talab qiladigan ishlar bir joyda.

Dashboard kartasi ham, kelajakdagi Telegram kunlik digest ham shu bitta
funksiyadan foydalanadi (bir marta hisoblanadi, ikki joyda ishlatiladi).
Har element: {level, icon, title, count, detail, link}.
level: danger (qizil) > warn (sariq) > info.
"""
from datetime import datetime, timedelta

from core.timeutils import now_tashkent, today_iso
from database import db
from models.billing import Teacher, Payment, ClientNote
from models.studio import Booking


def attention_items():
    today = today_iso()
    today_d = now_tashkent().date()
    items = []

    # 🟡 Follow-up muddati kelgan/o'tgan (faol mijozlar)
    active_ids = {t.id for t in Teacher.query.filter_by(is_active=True).all()}
    due_fu = [n for n in ClientNote.query.filter_by(
        kind="followup", done=False).filter(ClientNote.due_date != "").all()
        if n.due_date <= today and n.teacher_id in active_ids]
    if due_fu:
        overdue_fu = sum(1 for n in due_fu if n.due_date < today)
        items.append({
            "level": "warn", "icon": "alarm-clock",
            "title": "Follow-up eslatmalar", "count": len(due_fu),
            "detail": (f"{overdue_fu} tasi muddati o'tgan" if overdue_fu
                       else "bugun bog'lanish kerak"),
            "link": "/teachers"})

    # 🟡 To'lanmagan studiya to'lovlari (tasdiqlanmagan)
    pending = Payment.query.filter_by(is_paid=False).all()
    if pending:
        s = sum(p.amount or 0 for p in pending)
        items.append({
            "level": "warn", "icon": "receipt",
            "title": "Tasdiqlanmagan to'lovlar", "count": len(pending),
            "detail": f"{s:,.0f} so'm — tasdiqlang".replace(",", " "),
            "link": "/finance/payments"})

    # 🟡 Paketi tugayotgan mijozlar (≤2 soat, 0 dan katta) — qayta sotuv
    low = 0
    for t in Teacher.query.filter_by(is_active=True).all():
        if t.hours_purchased() > 0 and 0 < t.balance_hours() <= 2:
            low += 1
    if low:
        items.append({
            "level": "info", "icon": "package",
            "title": "Paketi tugayotgan mijozlar", "count": low,
            "detail": "qayta sotish uchun eng qulay payt", "link": "/teachers"})

    # 🟠 Churn xavfi — 30+ kun tashrif yo'q (kelgusi broni bo'lmagan faol)
    last = {}
    future = set()
    for b in Booking.query.filter(
            Booking.status.in_(("active", "done"))).all():
        if b.date > today:
            future.add(b.teacher_id)
        elif b.date > last.get(b.teacher_id, ""):
            last[b.teacher_id] = b.date
    churn = 0
    for tid in active_ids:
        if tid in future:
            continue
        lv = last.get(tid, "")
        if not lv:
            continue   # hech tashrif yo'q — «yangi», churn emas
        days = (today_d - datetime.strptime(lv, "%Y-%m-%d").date()).days
        if days >= 30:
            churn += 1
    if churn:
        items.append({
            "level": "warn", "icon": "user-x",
            "title": "Churn xavfi", "count": churn,
            "detail": "30+ kun yozilmagan — qayta faollashtiring",
            "link": "/analytics#churn"})

    # Muhimlik bo'yicha: danger → warn → info
    order = {"danger": 0, "warn": 1, "info": 2}
    items.sort(key=lambda x: order.get(x["level"], 3))
    return items
