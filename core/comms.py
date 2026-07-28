"""
KOMMUNIKATSIYA YADROSI — vazifalar API (Impulse ERP'dan moslashtirilgan).

Har qanday modul shu funksiyalarni chaqiradi:
  - log_event()    → faollik/audit jurnaliga yozadi
  - notify()       → aniq odam/rolega signal (inbox + Telegram)
  - create_task()  → vazifa uzatadi
  - advance_task() → holatni oldinga suradi (new→accepted→in_progress→done)
  - tasks_for()    → foydalanuvchiga ko'rinadigan vazifalar

Yagona, izchil mantiq: modullar to'g'ridan-to'g'ri Task/Notification yaratmaydi.
"""
import logging
from datetime import datetime, timedelta

from database import db
from models.communication import Notification, Task
from models.user import User

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
#  1. EVENT — faollik/audit jurnali (AuditLog ustidan)
# ══════════════════════════════════════════════════════════════════

def log_event(actor, action, *, entity="task", entity_id=None, summary=""):
    """Muhim amalni audit jurnaliga yozadi (rahbar ko'radi). Xatoda jim."""
    try:
        from models.audit import AuditLog
        from flask import request, has_request_context
        ip = ""
        if has_request_context():
            ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                  or request.remote_addr or "")
        db.session.add(AuditLog(
            user_name=getattr(actor, "name", "Tizim"),
            user_id=getattr(actor, "id", None),
            action=(action or "")[:40], entity=(entity or "task")[:40],
            summary=(summary or action or "")[:400], ip=ip[:48]))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning(f"log_event xato: {exc}")


# ══════════════════════════════════════════════════════════════════
#  2. NOTIFICATION — signal (inbox + Telegram)
# ══════════════════════════════════════════════════════════════════

def _notify_telegram(user_id, role, title, body, link):
    """Bildirishnomani Telegramга ham yuboradi (ulagan xodimlarga)."""
    try:
        from core.telegram import is_configured, tg_notify_user, tg_notify_role
        if not is_configured():
            return
        text = title or ""
        if body:
            text += "\n" + str(body)
        if link:
            from config import Config
            base = (getattr(Config, "APP_URL", "") or "").rstrip("/")
            text += "\n" + (base + link if base else link)
        if user_id:
            tg_notify_user(user_id, text)
        elif role:
            tg_notify_role(role, text)
    except Exception as exc:
        logger.debug(f"_notify_telegram: {exc}")


def notify(*, user_id=None, role=None, title="", body="",
           level="info", link="", telegram=True, dedup=True):
    """Bildirishnoma yuboradi.
      - user_id → shaxsiy
      - role → o'sha roldagi hammaga (bitta yozuv)
    DUBLIKAT HIMOYASI (dedup): aynan shu xabar shu manzilga so'nggi 24 soatда
    yuborilgan bo'lsa — qayta yuborilmaydi."""
    try:
        if dedup:
            cutoff = datetime.utcnow() - timedelta(hours=24)
            q = Notification.query.filter(
                Notification.title == title,
                Notification.body == body,
                Notification.created_at >= cutoff)
            if user_id is not None:
                q = q.filter(Notification.user_id == user_id)
            else:
                q = q.filter(Notification.role == role,
                             Notification.user_id.is_(None))
            dup = q.first()
            if dup is not None:
                return dup

        n = Notification(user_id=user_id, role=role, title=title, body=body,
                         level=level, link=link)
        db.session.add(n)
        db.session.commit()
        if telegram:
            _notify_telegram(user_id, role, title, body, link)
        return n
    except Exception as exc:
        db.session.rollback()
        logger.error(f"notify xato: {exc}")
        return None


def get_notifications_for(user, unread_only=False, limit=30):
    """Foydalanuvchiga tegishli bildirishnomalar (shaxsiy + role)."""
    q = Notification.query.filter(
        db.or_(Notification.user_id == user.id,
               Notification.role == user.role))
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    return q.order_by(Notification.created_at.desc()).limit(limit).all()


def unread_count(user):
    return Notification.query.filter(
        db.or_(Notification.user_id == user.id,
               Notification.role == user.role),
        Notification.is_read.is_(False)).count()


def mark_read(notif_id):
    n = Notification.query.get(notif_id)
    if n:
        n.is_read = True
        db.session.commit()
    return n


def mark_all_read(user):
    Notification.query.filter(
        db.or_(Notification.user_id == user.id,
               Notification.role == user.role),
        Notification.is_read.is_(False)).update(
        {"is_read": True}, synchronize_session=False)
    db.session.commit()


def prune_old_notifications(days=90):
    cutoff = datetime.utcnow() - timedelta(days=max(1, days))
    try:
        deleted = Notification.query.filter(
            Notification.created_at < cutoff).delete(synchronize_session=False)
        db.session.commit()
        return deleted
    except Exception as exc:
        db.session.rollback()
        logger.error(f"Habarnoma tozalash xato: {exc}")
        return 0


def prune_old_tasks(days=60):
    """N kundan eski TUGAGAN/BEKOR vazifalarni avtomatik o'chiradi.
    Ochiq (faol) vazifalar tegilmaydi."""
    from models.communication import TaskComment, TaskActivity, TaskWatcher
    cutoff = datetime.utcnow() - timedelta(days=max(1, days))
    try:
        ids = [t.id for t in Task.query.filter(
            Task.status.in_(("done", "cancelled")),
            Task.updated_at < cutoff).limit(5000).all()]
        if not ids:
            return 0
        TaskComment.query.filter(TaskComment.task_id.in_(ids)).delete(synchronize_session=False)
        TaskActivity.query.filter(TaskActivity.task_id.in_(ids)).delete(synchronize_session=False)
        TaskWatcher.query.filter(TaskWatcher.task_id.in_(ids)).delete(synchronize_session=False)
        deleted = Task.query.filter(Task.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        if deleted:
            logger.info(f"Eski tugagan vazifa tozalandi: {deleted} ta (>{days} kun)")
        return deleted
    except Exception as exc:
        db.session.rollback()
        logger.error(f"Vazifa tozalash xato: {exc}")
        return 0


# ══════════════════════════════════════════════════════════════════
#  3. TASK — vazifa uzatish
# ══════════════════════════════════════════════════════════════════

def find_recent_dup_task(assigner_id, title, assignee_id=None,
                         target_role=None, within_min=10):
    """Shu topshiruvchi oxirgi `within_min` daqiqada AYNAN shu vazifani
    yaratganmi? Bo'lsa — o'sha Task (dublikat), aks holda None."""
    title = (title or "").strip()
    if not assigner_id or not title:
        return None
    cutoff = datetime.utcnow() - timedelta(minutes=within_min)
    q = Task.query.filter(Task.assigner_id == assigner_id, Task.title == title,
                          Task.created_at >= cutoff)
    if assignee_id:
        q = q.filter(Task.assignee_id == assignee_id)
    else:
        q = q.filter(Task.assignee_id.is_(None))
    if target_role:
        q = q.filter(Task.target_role == target_role)
    else:
        q = q.filter(db.or_(Task.target_role.is_(None), Task.target_role == ""))
    return q.order_by(Task.id.desc()).first()


def create_task(*, title, description="", assigner=None,
                assignee_id=None, target_role=None,
                priority="normal", related_type="", related_id=None,
                due_date="", is_auto=False, notify_target=True):
    """Vazifa yaratadi va (ixtiyoriy) qabul qiluvchiga bildirishnoma yuboradi.
      - assignee_id → aniq odamga
      - target_role → butun rolega"""
    # Dublikat avto-vazifa himoyasi: aynan shu sarlavhali OCHIQ vazifa shu
    # manzilда allaqachon bo'lsa — ikkinchisi yaratilmaydi.
    if is_auto:
        dq = Task.query.filter(Task.title == title, Task.status != "done")
        if assignee_id:
            dq = dq.filter(Task.assignee_id == assignee_id)
        elif target_role:
            dq = dq.filter(Task.target_role == target_role,
                           Task.assignee_id.is_(None))
        else:
            dq = None
        if dq is not None:
            dup = dq.first()
            if dup is not None:
                return dup
    try:
        assignee_name = ""
        if assignee_id:
            u = User.query.get(assignee_id)
            assignee_name = u.name if u else ""

        t = Task(title=title, description=description,
                 assigner_id=getattr(assigner, "id", None),
                 assigner_name=getattr(assigner, "name", "Tizim"),
                 assignee_id=assignee_id, assignee_name=assignee_name,
                 target_role=target_role, priority=priority,
                 related_type=related_type, related_id=related_id,
                 due_date=due_date, is_auto=is_auto)
        db.session.add(t)
        db.session.commit()

        if notify_target:
            lvl = "urgent" if priority in ("high", "urgent") else "info"
            who = getattr(assigner, "name", "") or "Rahbaringiz"
            due = f"\n🗓 Muddat: {due_date}" if due_date else ""
            desc = f"\n{description}" if description else ""
            urg = " (shoshilinch ⚡)" if priority in ("high", "urgent") else ""
            notify(user_id=assignee_id,
                   role=target_role if not assignee_id else None,
                   title=f"📌 Yangi vazifa — {title}",
                   body=(f"Assalomu alaykum! {who} sizga yangi vazifa "
                         f"biriktirdi{urg}.\n📝 {title}{desc}{due}"
                         "\n\nQabul qilib, ishga kirishsangiz bo'ladi — omad! 💪"),
                   level=lvl, link=f"/tasks#task-{t.id}")
        return t
    except Exception as exc:
        db.session.rollback()
        logger.error(f"create_task xato: {exc}")
        return None


def advance_task(task_id, new_status, by_user=None):
    """Vazifa statusini o'zgartirish + tarix + topshiruvchiga signal.
    4 etap: new → accepted → in_progress → done."""
    from models.communication import TaskActivity

    t = Task.query.get(task_id)
    if not t:
        return None
    old_status = t.status
    if old_status == new_status:
        return t

    t.status = new_status
    now = datetime.utcnow()
    if new_status == "accepted" and not t.accepted_at:
        t.accepted_at = now
    elif new_status == "in_progress" and not t.started_at:
        t.started_at = now
    elif new_status == "done":
        t.completed_at = now
        t.progress = 100

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error(f"advance_task commit xato: {exc}")
        return None

    try:
        db.session.add(TaskActivity(
            task_id=t.id, user_id=getattr(by_user, "id", None),
            user_name=getattr(by_user, "name", "Tizim"), kind="status",
            old_value=Task.STATUS_LABELS.get(old_status, old_status),
            new_value=Task.STATUS_LABELS.get(new_status, new_status)))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning(f"TaskActivity log xato: {exc}")

    label = Task.STATUS_LABELS.get(new_status, new_status)
    log_event(by_user, f"Vazifa holati: {label}", entity="task",
              entity_id=t.id, summary=t.title)

    # Topshirgan odamга xabar — samimiy, inson tilida
    if t.assigner_id and getattr(by_user, "id", None) != t.assigner_id:
        who = getattr(by_user, "name", "") or "Xodim"
        msg = {
            "accepted": (f"✅ «{t.title}» qabul qilindi",
                         f"{who} vazifani qabul qildi va ishga kirishyapti. 👍"),
            "in_progress": (f"▶️ «{t.title}» — ish boshlandi",
                            f"{who} bu vazifa ustida ishni boshladi. 🚀"),
            "done": (f"🎉 «{t.title}» bajarildi!",
                     f"{who} vazifani muvaffaqiyatli yakunladi. Rahmat! 🙌"),
        }.get(new_status)
        if msg:
            notify(user_id=t.assigner_id, title=msg[0], body=msg[1],
                   level="info", link=f"/tasks#task-{t.id}")
    return t


def tasks_for(user, status=None):
    """Foydalanuvchiga ko'rinadigan vazifalar.
    • Rahbar (is_boss) — barcha vazifalar
    • Oddiy xodim — o'ziga (asosiy/qo'shimcha) tayinlangan, o'z rolega
      topshirilgan, YOKI o'zi topshirgan vazifalar"""
    uid = str(user.id)
    co_filter = db.or_(
        Task.co_assignee_ids == uid,
        Task.co_assignee_ids.like(f"{uid},%"),
        Task.co_assignee_ids.like(f"%,{uid}"),
        Task.co_assignee_ids.like(f"%,{uid},%"))

    if user.is_boss:
        q = Task.query
    else:
        q = Task.query.filter(db.or_(
            Task.assignee_id == user.id,
            Task.assigner_id == user.id,
            Task.target_role == user.role,
            co_filter))
    if status:
        q = q.filter(Task.status == status)
    return q.order_by(Task.created_at.desc()).all()
