"""Retention dvigateli — «mijoz bizdan jimgina ketib qolmasin».

Impulse ERP'dagi retention g'oyasi: signal faqat panelda ko'rinib tursa,
hech kim unga «egalik» qilmaydi. Shuning uchun kuniga bir marta har signal
ANIQ VAZIFAGA aylanadi (operatorlarga; operator bo'lmasa rahbarga):

  1. 📦 Paketi tugayapti   — 0 < balans ≤ 2 soat → qayta sotish payti
  2. 📡 Uxlab qolgan mijoz — CHURN_DAYS+ kun kelmagan, kelgusi broni yo'q
  3. ⏰ Follow-up muddati  — mijoz kartasidagi eslatma muddati keldi

Takrorlanmaslik: ochiq vazifa bo'lsa yangisi yaratilmaydi (create_task
dedup); yopilgandan keyin ham COOLDOWN_DAYS ichida qayta yaratilmaydi
(aks holda «bajarildi» qilingan vazifa ertasi kuni yana chiqib flood qiladi).
Bir yurishda har tur uchun MAX_PER_KIND tadan ortiq emas (taxta to'lmasin).
"""
import logging
from datetime import datetime, timedelta

from database import db

logger = logging.getLogger(__name__)

CHURN_DAYS = 30
COOLDOWN_DAYS = 14
MAX_PER_KIND = 5


def _owner_role():
    """Mijoz bilan ishlash — operatorlarniki; ular yo'q bo'lsa rahbar."""
    from models.user import User
    has_op = User.query.filter_by(role="operator", is_active=True).first()
    return "operator" if has_op else "admin"


def _recently_handled(title):
    """Shu sarlavhali vazifa COOLDOWN ichida yopilganmi / hali ochiqmi."""
    from models.communication import Task
    cutoff = datetime.utcnow() - timedelta(days=COOLDOWN_DAYS)
    return db.session.query(Task.id).filter(
        Task.title == title,
        db.or_(Task.status.notin_(("done", "cancelled")),
               Task.updated_at >= cutoff)).first() is not None


def _make(title, description, related_id, due, priority="normal"):
    from core.comms import create_task
    if _recently_handled(title):
        return False
    t = create_task(title=title, description=description,
                    target_role=_owner_role(), priority=priority,
                    related_type="teacher", related_id=related_id,
                    due_date=due, is_auto=True)
    return t is not None


def run_retention(today=None):
    """Kunlik yurish. Qaytaradi: {tur: yaratilgan_soni}."""
    from core.timeutils import now_tashkent
    from models.billing import Teacher, ClientNote, package_balances
    from models.studio import Booking

    d0 = today or now_tashkent().date()
    today_s = d0.strftime("%Y-%m-%d")
    due = (d0 + timedelta(days=1)).strftime("%Y-%m-%d")
    active = {t.id: t for t in Teacher.query.filter_by(is_active=True).all()}
    made = {"low_balance": 0, "churn": 0, "followup": 0}

    # 1) Paketi tugayapti — eng kam qolganlar birinchi
    bal = package_balances()
    low = sorted(((info["balance"], tid) for tid, info in bal.items()
                  if tid in active and info["purchased"] > 0
                  and 0 < info["balance"] <= 2))
    for b, tid in low:
        if made["low_balance"] >= MAX_PER_KIND:
            break
        t = active[tid]
        if _make(f"📦 Paket tugayapti: {t.name} — yangi paket taklif qiling",
                 f"Balans: {b:g} soat qoldi. Qo'ng'iroq qilib keyingi paketni "
                 f"taklif qiling (hozir eng qulay payt)."
                 + (f"\n☎ {t.phone}" if t.phone else ""), tid, due):
            made["low_balance"] += 1

    # 2) Uxlab qolgan mijozlar — eng uzoq kelmaganlar birinchi
    last, future = {}, set()
    for b in Booking.query.filter(Booking.status.in_(("active", "done"))).all():
        if b.date > today_s:
            future.add(b.teacher_id)
        elif b.date > last.get(b.teacher_id, ""):
            last[b.teacher_id] = b.date
    sleepers = []
    for tid, lv in last.items():
        if tid not in active or tid in future:
            continue
        days = (d0 - datetime.strptime(lv, "%Y-%m-%d").date()).days
        if days >= CHURN_DAYS:
            sleepers.append((days, tid))
    for days, tid in sorted(sleepers, reverse=True):
        if made["churn"] >= MAX_PER_KIND:
            break
        t = active[tid]
        if _make(f"📡 Qayta faollashtiring: {t.name}",
                 f"{days} kundan beri yozilmagan, kelgusi broni yo'q. "
                 f"Holini so'rang va bo'sh kunduzgi vaqtni chegirma bilan "
                 f"taklif qiling." + (f"\n☎ {t.phone}" if t.phone else ""),
                 tid, due):
            made["churn"] += 1

    # 3) Follow-up muddati kelgan eslatmalar (mijoz kartasidan)
    for n in ClientNote.query.filter(
            ClientNote.kind == "followup", ClientNote.done.is_(False),
            ClientNote.due_date != "", ClientNote.due_date <= today_s).order_by(
            ClientNote.due_date.asc()).all():
        if made["followup"] >= MAX_PER_KIND:
            break
        t = active.get(n.teacher_id)
        if not t:
            continue
        if _make(f"⏰ Follow-up: {t.name} — {n.text[:60]}",
                 f"Muddat: {n.due_date}. Eslatma: {n.text}\n"
                 f"Bajarilgach mijoz kartasida belgilang.", t.id, today_s,
                 priority="high" if n.due_date < today_s else "normal"):
            made["followup"] += 1

    if any(made.values()):
        logger.info(f"🔁 retention: {made}")
    return made
