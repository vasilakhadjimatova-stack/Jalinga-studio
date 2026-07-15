"""Moliya ERP — Google Sheets («Jalinga 2026») jurnali asosida.

Sahifalar: dashboard (hisoblar+KPI+grafiklar) · tranzaksiyalar jurnali ·
ДДС hisoboti (yillik pul oqimi) · qarzlar (DOLG) · dividendlar ·
studiya to'lovlari (eski jurnal). Sync: ochiq xlsx eksport orqali.
"""
import logging
import math
from collections import defaultdict
from datetime import date, datetime


def _bad_amount(x):
    """Summa yaroqsizmi: inf/nan yoki musbat emas (0 yoki manfiy)."""
    try:
        return (not math.isfinite(float(x))) or float(x) <= 0
    except (ValueError, TypeError):
        return True


def _bad_date(d):
    """Sana YYYY-MM-DD emasmi (int krash / poison oy-yil oldini oladi)."""
    try:
        datetime.strptime((d or "").strip(), "%Y-%m-%d")
        return False
    except (ValueError, TypeError):
        return True

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash)

from config import Config
from core.auth import finance_required
from core.timeutils import current_month_iso
from database import db
from models.billing import Teacher, Payment, PAY_METHODS
from models.finance import (FinWallet, FinCategory, FinTransaction,
                            FinDebt, FinSetting, FinRecurring, FinPlan)
from models.audit import record
from modules.finance.sheets_sync import ACTIVITY_LABELS

logger = logging.getLogger(__name__)
bp = Blueprint("finance", __name__)

MONTH_NAMES = ["", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
               "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"]


# ── Yordamchilar ─────────────────────────────────────────────────────────────

def _years():
    rows = db.session.query(FinTransaction.year).distinct().all()
    ys = sorted({r[0] for r in rows}) or [date.today().year]
    return ys


def _pick_year():
    try:
        y = int(request.args.get("year", ""))
    except ValueError:
        y = 0
    ys = _years()
    return y if y in ys else ys[-1]


def _latest_month(year):
    row = (db.session.query(db.func.max(FinTransaction.month))
           .filter_by(year=year).scalar())
    return int(row or date.today().month)


def _wallet_balances():
    """Hamyon balansi = ochilish + kirim - chiqim (butun davr)."""
    wallets = FinWallet.query.order_by(FinWallet.sort).all()
    sums = dict(db.session.query(
        FinTransaction.wallet,
        db.func.sum(db.case((FinTransaction.direction == "in",
                             FinTransaction.amount),
                            else_=-FinTransaction.amount))
    ).group_by(FinTransaction.wallet).all())
    out = []
    for w in wallets:
        bal = (w.opening_balance or 0) + float(sums.get(w.name) or 0)
        out.append({"name": w.name, "balance": bal, "currency": w.currency})
    return out


def _sync_info():
    return {"last_sync": FinSetting.get("last_sync", "—"),
            "source": FinSetting.get("sync_source", "")}


# ── Dashboard ────────────────────────────────────────────────────────────────

@bp.route("/finance")
@finance_required
def index():
    year = _pick_year()
    try:
        month = int(request.args.get("month", 0)) or _latest_month(year)
    except ValueError:
        month = _latest_month(year)
    month = min(max(month, 1), 12)

    txns = FinTransaction.query.filter_by(year=year).all()

    # Oylik seriya (texnik o'tkazmalarsiz — biznes oqimi)
    inc = [0.0] * 13
    exp = [0.0] * 13
    for t in txns:
        if t.activity == "technical":
            continue
        if t.direction == "in":
            inc[t.month] += t.amount
        else:
            exp[t.month] += t.amount

    month_in, month_out = inc[month], exp[month]
    year_in, year_out = sum(inc), sum(exp)

    # Xarajat strukturasi — tanlangan oy, top statyalar
    cat_exp = defaultdict(float)
    for t in txns:
        if (t.month == month and t.direction == "out"
                and t.activity != "technical"):
            cat_exp[t.category] += t.amount
    top_exp = sorted(cat_exp.items(), key=lambda kv: -kv[1])[:7]

    balances = _wallet_balances()
    total_balance = sum(b["balance"] for b in balances)

    debts = FinDebt.query.all()
    debt_out = sum(d.remainder for d in debts if d.remainder > 0)

    recent = (FinTransaction.query.order_by(
        FinTransaction.date.desc(), FinTransaction.id.desc()).limit(9).all())

    # Yig'ma qoldiq dinamikasi — har oy oxiridagi kassa (o'tkazmalar bilan)
    closing = build_dds(year)["closing"]
    bal_series = [round(closing[m]) for m in range(1, 13)]

    return render_template(
        "finance.html", year=year, month=month, years=_years(),
        month_names=MONTH_NAMES,
        month_in=month_in, month_out=month_out,
        month_net=month_in - month_out,
        year_in=year_in, year_out=year_out,
        balances=balances, total_balance=total_balance,
        inc_series=[round(v) for v in inc[1:]],
        exp_series=[round(v) for v in exp[1:]],
        bal_series=bal_series, last_month=max([t.month for t in txns],
                                              default=0),
        top_exp=top_exp, debt_out=debt_out, recent=recent,
        sync=_sync_info())


# ── Tranzaksiyalar jurnali ───────────────────────────────────────────────────

@bp.route("/finance/transactions")
@finance_required
def transactions():
    month = (request.args.get("month") or "").strip()[:7]   # YYYY-MM yoki ''
    wallet = (request.args.get("wallet") or "").strip()
    category = (request.args.get("category") or "").strip()
    dirf = (request.args.get("dir") or "").strip()
    q = (request.args.get("q") or "").strip()

    pay_ref0 = request.args.get("pay", type=int)
    # Filtr berilmagan birinchi ochilishda — oxirgi faol oy
    if not month and not (wallet or category or dirf or q or pay_ref0
                          or request.args.get("all")):
        y = _years()[-1]
        month = f"{y}-{_latest_month(y):02d}"

    pay_ref = request.args.get("pay", type=int)   # bitta to'lovga bog'langan yozuv

    qry = FinTransaction.query
    if pay_ref:
        qry = qry.filter_by(payment_id=pay_ref, source="studio")
    if month:
        qry = qry.filter(FinTransaction.date.like(month + "%"))
    if wallet:
        qry = qry.filter_by(wallet=wallet)
    if category:
        qry = qry.filter_by(category=category)
    if dirf in ("in", "out"):
        qry = qry.filter_by(direction=dirf)
    if q:
        like = f"%{q}%"
        qry = qry.filter(db.or_(FinTransaction.purpose.ilike(like),
                                FinTransaction.counterparty.ilike(like),
                                FinTransaction.category.ilike(like)))
    rows = qry.order_by(FinTransaction.date.desc(),
                        FinTransaction.id.desc()).limit(500).all()

    # O'zaro bog'lanish: studiya to'loviga bog'langan yozuvlarга mijoz havolasi
    studio_pids = {t.payment_id for t in rows
                   if t.source == "studio" and t.payment_id}
    pay_teacher = {}
    if studio_pids:
        for p in Payment.query.filter(Payment.id.in_(studio_pids)).all():
            pay_teacher[p.id] = p.teacher_id
    for t in rows:
        tid = pay_teacher.get(t.payment_id) if t.source == "studio" else None
        t.ref_url = f"/teachers/{tid}" if tid else None

    t_in = sum(t.amount for t in rows if t.direction == "in")
    t_out = sum(t.amount for t in rows if t.direction == "out")

    wallets = FinWallet.query.order_by(FinWallet.sort).all()
    cats = FinCategory.query.order_by(FinCategory.direction.desc(),
                                      FinCategory.sort).all()
    return render_template(
        "finance_txns.html", rows=rows, month=month, wallet=wallet,
        category=category, dirf=dirf, q=q, t_in=t_in, t_out=t_out,
        wallets=wallets, cats=cats, activity_labels=ACTIVITY_LABELS,
        sync=_sync_info())


@bp.route("/finance/transactions/add", methods=["POST"])
@finance_required
def txn_add():
    d = (request.form.get("date") or "").strip()[:10]
    cat_name = (request.form.get("category") or "").strip()
    wallet = (request.form.get("wallet") or "").strip()
    try:
        amount = float((request.form.get("amount") or "0").replace(" ", "")
                       .replace(",", "."))
    except ValueError:
        amount = 0
    cat = FinCategory.query.filter_by(name=cat_name).first()
    if _bad_date(d) or _bad_amount(amount) or cat is None or not wallet:
        flash("Sana, summa (>0), hamyon va statya to'g'ri kiritilishi shart",
              "error")
        return redirect(url_for("finance.transactions"))
    db.session.add(FinTransaction(
        date=d, year=int(d[:4]), month=int(d[5:7]), amount=amount,
        wallet=wallet,
        counterparty=(request.form.get("counterparty") or "").strip()[:200],
        purpose=(request.form.get("purpose") or "").strip()[:400],
        category=cat.name, direction=cat.direction, activity=cat.activity,
        source="manual"))
    record("create", "transaction",
           f"{cat.direction} {amount:.0f} — {cat.name} ({wallet})")
    db.session.commit()
    flash("✅ Tranzaksiya qo'shildi", "success")
    return redirect(url_for("finance.transactions", month=d[:7]))


# Foydalanuvchi qo'lда tahrirlashi/o'chirishi mumkin bo'lgan manbalar.
# 'studio' — studiya to'loviга bog'langan (Studiya to'lovlari sahifasi);
# 'plan'/'recurring' — to'lov kalendari boshqaradi.
EDITABLE_SOURCES = ("sheet", "manual")
LOCKED_MSG = {
    "studio": "Bu yozuv studiya to'loviга bog'langan — «Studiya to'lovlari» "
              "sahifasidan boshqaring",
    "plan": "Bu yozuv to'lov kalendari rejasiга bog'langan — «To'lov "
            "kalendari» sahifasidan boshqaring",
    "recurring": "Bu yozuv doimiy to'lovga bog'langan — «To'lov kalendari» "
                 "sahifasidan boshqaring",
}


@bp.route("/finance/transactions/<int:tid>/edit", methods=["POST"])
@finance_required
def txn_edit(tid):
    t = FinTransaction.query.get_or_404(tid)
    if t.source not in EDITABLE_SOURCES:
        flash(LOCKED_MSG.get(t.source, "Bu yozuv tahrirlanmaydi"), "error")
        return redirect(url_for("finance.transactions", month=t.date[:7]))
    d = (request.form.get("date") or "").strip()[:10]
    cat = FinCategory.query.filter_by(
        name=(request.form.get("category") or "").strip()).first()
    try:
        amount = float((request.form.get("amount") or "0").replace(" ", "")
                       .replace(",", "."))
    except ValueError:
        amount = 0
    wallet = (request.form.get("wallet") or "").strip()
    if _bad_date(d) or _bad_amount(amount) or cat is None or not wallet:
        flash("Sana, summa (>0), hamyon va statya to'g'ri bo'lishi shart",
              "error")
        return redirect(url_for("finance.transactions", month=t.date[:7]))
    t.date, t.year, t.month = d, int(d[:4]), int(d[5:7])
    t.amount = amount
    t.wallet = wallet
    t.counterparty = (request.form.get("counterparty") or "").strip()[:200]
    t.purpose = (request.form.get("purpose") or "").strip()[:400]
    t.category, t.direction, t.activity = cat.name, cat.direction, cat.activity
    record("update", "transaction", f"#{t.id} → {amount:.0f} {cat.name}")
    db.session.commit()
    flash("✅ Tranzaksiya yangilandi", "success")
    return redirect(url_for("finance.transactions", month=d[:7]))


@bp.route("/finance/transactions/<int:tid>/delete", methods=["POST"])
@finance_required
def txn_delete(tid):
    t = FinTransaction.query.get_or_404(tid)
    if t.source not in EDITABLE_SOURCES:
        flash(LOCKED_MSG.get(t.source, "Bu yozuv o'chirilmaydi"), "error")
        return redirect(url_for("finance.transactions", month=t.date[:7]))
    month = t.date[:7]
    record("delete", "transaction",
           f"#{t.id} {t.amount:.0f} {t.category} ({t.date})")
    db.session.delete(t)
    db.session.commit()
    flash("🗑 Tranzaksiya o'chirildi", "success")
    return redirect(url_for("finance.transactions", month=month))


# ── ДДС (pul oqimi hisoboti) ─────────────────────────────────────────────────

def _opening_total(year):
    """Yil boshidagi jami qoldiq: ochilish qoldiqlari + oldingi yillar oqimi."""
    opening = db.session.query(db.func.sum(FinWallet.opening_balance)).filter(
        FinWallet.opening_year <= year).scalar() or 0.0
    prev = db.session.query(db.func.sum(
        db.case((FinTransaction.direction == "in", FinTransaction.amount),
                else_=-FinTransaction.amount)
    )).filter(FinTransaction.year < year).scalar() or 0.0
    return float(opening) + float(prev)


def build_dds(year):
    """Yillik ДДС: oyma-oy, faoliyat bo'limlari bilan (Sheets ДДС_2026 kabi)."""
    txns = FinTransaction.query.filter_by(year=year).all()
    # tree[activity][direction][category] = [0]*13 oylik summalar
    tree = defaultdict(lambda: defaultdict(lambda: defaultdict(
        lambda: [0.0] * 13)))
    for t in txns:
        tree[t.activity][t.direction][t.category][t.month] += t.amount

    cat_sort = {c.name: c.sort for c in FinCategory.query.all()}
    sections = []
    for act in ("operating", "investing", "financing"):
        sec = {"key": act, "label": ACTIVITY_LABELS[act], "rows_in": [],
               "rows_out": [], "in": [0.0] * 13, "out": [0.0] * 13}
        for direction, key in (("in", "rows_in"), ("out", "rows_out")):
            cats = sorted(tree[act][direction].items(),
                          key=lambda kv: cat_sort.get(kv[0], 999))
            for name, months in cats:
                total = sum(months)
                if total == 0:
                    continue
                sec[key].append({"name": name, "months": months,
                                 "total": total})
                agg = sec["in" if direction == "in" else "out"]
                for m in range(1, 13):
                    agg[m] += months[m]
        sec["net"] = [sec["in"][m] - sec["out"][m] for m in range(13)]
        sec["in_total"] = sum(sec["in"])
        sec["out_total"] = sum(sec["out"])
        sec["net_total"] = sec["in_total"] - sec["out_total"]
        sections.append(sec)

    # Texnik o'tkazmalar (ma'lumot qatori — netto oqimga kirmaydi)
    tr_in = [0.0] * 13
    tr_out = [0.0] * 13
    for months in tree["technical"]["in"].values():
        for m in range(1, 13):
            tr_in[m] += months[m]
    for months in tree["technical"]["out"].values():
        for m in range(1, 13):
            tr_out[m] += months[m]

    opening = [0.0] * 13
    closing = [0.0] * 13
    net_flow = [0.0] * 13
    run = _opening_total(year)
    for m in range(1, 13):
        opening[m] = run
        net_flow[m] = sum(s["net"][m] for s in sections)
        run = run + net_flow[m] + tr_in[m] - tr_out[m]
        closing[m] = run

    last_m = max([t.month for t in txns], default=0)
    return {"year": year, "sections": sections, "opening": opening,
            "closing": closing, "net_flow": net_flow,
            "net_flow_total": sum(net_flow),
            "transfer_in": tr_in, "transfer_out": tr_out,
            "last_month": last_m}


@bp.route("/finance/dds")
@finance_required
def dds():
    year = _pick_year()
    report = build_dds(year)
    return render_template("finance_dds.html", r=report, year=year,
                           years=_years(), month_names=MONTH_NAMES,
                           sync=_sync_info())


# ── Qarzlar (DOLG) — to'liq boshqaruv ────────────────────────────────────────

@bp.route("/finance/debts")
@finance_required
def debts():
    rows = FinDebt.query.order_by(FinDebt.id.desc()).all()
    total = sum(d.amount or 0 for d in rows)
    repaid = sum(d.repaid or 0 for d in rows)
    return render_template("finance_debts.html", rows=rows, total=total,
                           repaid=repaid, outstanding=total - repaid,
                           sync=_sync_info())


def _num(field, default=0.0):
    try:
        v = float((request.form.get(field) or "0").replace(" ", "")
                  .replace(",", "."))
        return v if math.isfinite(v) else default   # inf/nan → default
    except ValueError:
        return default


@bp.route("/finance/debts/add", methods=["POST"])
@finance_required
def debt_add():
    amount = _num("amount")
    if _bad_amount(amount):
        flash("Summa 0 dan katta bo'lishi shart", "error")
        return redirect(url_for("finance.debts"))
    db.session.add(FinDebt(
        date=(request.form.get("date") or "").strip()[:24],
        debtor=(request.form.get("debtor") or "").strip()[:120],
        creditor=(request.form.get("creditor") or "").strip()[:120],
        reason=(request.form.get("reason") or "").strip()[:500],
        amount=amount, repaid=max(0.0, min(_num("repaid"), amount)),
        source="manual"))
    record("create", "debt", f"{amount:.0f} — {request.form.get('creditor','')}")
    db.session.commit()
    flash("✅ Qarz qo'shildi", "success")
    return redirect(url_for("finance.debts"))


@bp.route("/finance/debts/<int:did>/edit", methods=["POST"])
@finance_required
def debt_edit(did):
    d = FinDebt.query.get_or_404(did)
    amount = _num("amount")
    if _bad_amount(amount):
        flash("Summa 0 dan katta bo'lishi shart", "error")
        return redirect(url_for("finance.debts"))
    d.date = (request.form.get("date") or "").strip()[:24]
    d.debtor = (request.form.get("debtor") or "").strip()[:120]
    d.creditor = (request.form.get("creditor") or "").strip()[:120]
    d.reason = (request.form.get("reason") or "").strip()[:500]
    d.amount = amount
    d.repaid = max(0.0, min(_num("repaid"), amount))
    record("update", "debt", f"#{d.id} → {amount:.0f} {d.creditor}")
    db.session.commit()
    flash("✅ Qarz yangilandi", "success")
    return redirect(url_for("finance.debts"))


@bp.route("/finance/debts/<int:did>/repay", methods=["POST"])
@finance_required
def debt_repay(did):
    """Qisman/to'liq qaytarishni qo'shish (qaytarilgan summani oshiradi)."""
    d = FinDebt.query.get_or_404(did)
    add = _num("amount")
    if add <= 0:
        flash("Qaytarilgan summa 0 dan katta bo'lsin", "error")
        return redirect(url_for("finance.debts"))
    d.repaid = min((d.repaid or 0) + add, d.amount or 0)
    if (request.form.get("date") or "").strip():
        d.repaid_date = request.form.get("date").strip()[:24]
    record("repay", "debt", f"#{d.id} +{add:.0f} ({d.creditor})")
    db.session.commit()
    flash(f"✅ {add:,.0f} so'm qaytarildi belgilandi", "success")
    return redirect(url_for("finance.debts"))


@bp.route("/finance/debts/<int:did>/delete", methods=["POST"])
@finance_required
def debt_delete(did):
    d = FinDebt.query.get_or_404(did)
    record("delete", "debt", f"#{d.id} {d.amount:.0f} {d.creditor}")
    db.session.delete(d)
    db.session.commit()
    flash("🗑 Qarz o'chirildi", "success")
    return redirect(url_for("finance.debts"))


# ── Dividendlar ──────────────────────────────────────────────────────────────

@bp.route("/finance/dividends")
@finance_required
def dividends():
    rows = (FinTransaction.query.filter_by(category="Дивиденды")
            .order_by(FinTransaction.date.desc()).all())
    total = sum(t.amount for t in rows)
    by_year = defaultdict(float)
    for t in rows:
        by_year[t.year] += t.amount
    return render_template("finance_dividends.html", rows=rows, total=total,
                           by_year=sorted(by_year.items()),
                           sync=_sync_info())


# ── Sozlamalar: hisoblar (ochilish qoldig'i) + statyalar ─────────────────────

@bp.route("/finance/settings")
@finance_required
def settings():
    wallets = FinWallet.query.order_by(FinWallet.sort).all()
    # Joriy balansni ham ko'rsatamiz (ochilish + harakatlar)
    bal = {b["name"]: b["balance"] for b in _wallet_balances()}
    wal = [{"row": w, "balance": bal.get(w.name, w.opening_balance or 0)}
           for w in wallets]
    cats = FinCategory.query.order_by(FinCategory.direction.desc(),
                                      FinCategory.sort).all()
    return render_template("finance_settings.html", wallets=wal, cats=cats,
                           activity_labels=ACTIVITY_LABELS, sync=_sync_info())


@bp.route("/finance/wallets/save", methods=["POST"])
@finance_required
def wallet_save():
    wid = (request.form.get("id") or "").strip()
    name = (request.form.get("name") or "").strip()[:120]
    if not name:
        flash("Hisob nomi kiritilishi shart", "error")
        return redirect(url_for("finance.settings"))
    opening = _num("opening_balance")
    cur = (request.form.get("currency") or "UZS").strip()[:8]
    if wid.isdigit():
        w = FinWallet.query.get(int(wid))
        if w:
            other = FinWallet.query.filter(FinWallet.name == name,
                                           FinWallet.id != w.id).first()
            if other:
                flash("Bu nomli hisob allaqachon bor", "error")
                return redirect(url_for("finance.settings"))
            old_name = w.name
            w.name, w.opening_balance, w.currency = name, opening, cur
            # Nom o'zgarsa — hisob nomi (matn kalit) bilan bog'langan barcha
            # yozuvlarni ko'chiramiz (aks holda balans/DDS yetim qoladi).
            if old_name != name:
                FinTransaction.query.filter_by(wallet=old_name).update(
                    {"wallet": name}, synchronize_session=False)
                FinRecurring.query.filter_by(wallet=old_name).update(
                    {"wallet": name}, synchronize_session=False)
                FinPlan.query.filter_by(wallet=old_name).update(
                    {"wallet": name}, synchronize_session=False)
                Payment.query.filter_by(wallet=old_name).update(
                    {"wallet": name}, synchronize_session=False)
    else:
        if FinWallet.query.filter_by(name=name).first():
            flash("Bu nomli hisob allaqachon bor", "error")
            return redirect(url_for("finance.settings"))
        mx = db.session.query(db.func.max(FinWallet.sort)).scalar() or 0
        db.session.add(FinWallet(name=name, opening_balance=opening,
                                 currency=cur, sort=mx + 1,
                                 opening_year=date.today().year))
    record("update" if wid.isdigit() else "create", "wallet",
           f"{name} — ochilish {opening:.0f}")
    db.session.commit()
    flash("✅ Hisob saqlandi", "success")
    return redirect(url_for("finance.settings"))


@bp.route("/finance/wallets/<int:wid>/delete", methods=["POST"])
@finance_required
def wallet_delete(wid):
    w = FinWallet.query.get_or_404(wid)
    used = FinTransaction.query.filter_by(wallet=w.name).count()
    if used:
        flash(f"Bu hisobда {used} ta tranzaksiya bor — avval ularni "
              f"o'chiring yoki boshqa hisobga o'tkazing", "error")
        return redirect(url_for("finance.settings"))
    record("delete", "wallet", w.name)
    db.session.delete(w)
    db.session.commit()
    flash("🗑 Hisob o'chirildi", "success")
    return redirect(url_for("finance.settings"))


@bp.route("/finance/categories/add", methods=["POST"])
@finance_required
def category_add():
    name = (request.form.get("name") or "").strip()[:200]
    direction = "in" if request.form.get("direction") == "in" else "out"
    activity = (request.form.get("activity") or "operating").strip()
    if activity not in ("operating", "investing", "financing", "technical"):
        activity = "operating"
    if not name:
        flash("Statya nomi kiritilishi shart", "error")
        return redirect(url_for("finance.settings"))
    if FinCategory.query.filter_by(name=name).first():
        flash("Bu statya allaqachon bor", "error")
        return redirect(url_for("finance.settings"))
    mx = db.session.query(db.func.max(FinCategory.sort)).scalar() or 0
    db.session.add(FinCategory(name=name, direction=direction,
                               activity=activity, sort=mx + 1))
    record("create", "category", f"{direction} — {name}")
    db.session.commit()
    flash("✅ Statya qo'shildi", "success")
    return redirect(url_for("finance.settings"))


@bp.route("/finance/categories/<int:cid>/delete", methods=["POST"])
@finance_required
def category_delete(cid):
    c = FinCategory.query.get_or_404(cid)
    used = FinTransaction.query.filter_by(category=c.name).count()
    if used:
        flash(f"Bu statyaда {used} ta tranzaksiya bor — o'chirib bo'lmaydi",
              "error")
        return redirect(url_for("finance.settings"))
    record("delete", "category", c.name)
    db.session.delete(c)
    db.session.commit()
    flash("🗑 Statya o'chirildi", "success")
    return redirect(url_for("finance.settings"))


# ── To'lov kalendari (kassa bashorati) ──────────────────────────────────────

def _opening_for_month(year, month):
    """Oy boshidagi kassa qoldig'i = ochilish + shu oygacha barcha harakat."""
    opening = db.session.query(db.func.sum(FinWallet.opening_balance)).filter(
        FinWallet.opening_year <= year).scalar() or 0.0
    prev = db.session.query(db.func.sum(
        db.case((FinTransaction.direction == "in", FinTransaction.amount),
                else_=-FinTransaction.amount)
    )).filter(db.or_(FinTransaction.year < year,
                     db.and_(FinTransaction.year == year,
                             FinTransaction.month < month))).scalar() or 0.0
    return float(opening) + float(prev)


def _actual_net_by_day(year, month):
    """Shu oyning haqiqiy tranzaksiyalari — kun bo'yicha netto (so'm)."""
    rows = FinTransaction.query.filter_by(year=year, month=month).all()
    by_day = defaultdict(float)
    for t in rows:
        try:
            d = int(t.date[8:10])
        except (ValueError, IndexError):
            continue
        by_day[d] += t.signed
    return by_day


def _recurring_paid(rec_id, year, month, category=None):
    """Shu recurring shu oyда qoplanganmi?

    Ikki holat: (1) kalendardan to'langan — bog'langan tranzaksiya bor;
    (2) jadval/qo'lда shu oyда shu statyada haqiqiy chiqim bor (masalan ijara
    Sheets'da allaqachon yozilgan) — ikki marta sanamaslik uchun qoplangan
    deb hisoblanadi (Impulse reconciliation mantig'i)."""
    if db.session.query(FinTransaction.id).filter_by(
            recurring_id=rec_id, year=year, month=month).first():
        return True
    # Qo'lda reconciliation: shu oyда shu statyada AYNAN shu summali chiqim
    # bo'lsagina qoplangan deb hisoblaymiz. Faqat statya bo'yicha moslash
    # xavfli edi — umumiy statyaда (masalan «прочие расходы») bitta tasodifiy
    # xarajat shu statyaдаги barcha doimiy to'lovlarni «to'langan» qilib
    # qo'yardi va kassa bashoratini soxta yaxshilardi.
    if category:
        rec = FinRecurring.query.get(rec_id)
        if rec and rec.amount:
            exists = db.session.query(FinTransaction.id).filter_by(
                year=year, month=month, category=category,
                direction="out", amount=rec.amount).filter(
                FinTransaction.source != "recurring").first()
            if exists:
                return True
    return False


@bp.route("/finance/calendar")
@finance_required
def calendar():
    import calendar as pycal
    from datetime import date as _date
    today = _date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month
    month = min(max(month, 1), 12)
    try:
        buffer = float(request.args.get("buffer", Config.CASH_SAFETY_BUFFER))
    except (TypeError, ValueError):
        buffer = Config.CASH_SAFETY_BUFFER

    first_wd, num_days = pycal.monthrange(year, month)
    first_wd = (first_wd) % 7    # 0=dushanba (pycal: 0=Mon) — mos

    days = {d: [] for d in range(1, num_days + 1)}
    planned_in = planned_out = 0.0

    # Doimiy to'lovlar (har oy chiqim)
    for r in FinRecurring.query.filter_by(is_active=True).order_by(
            FinRecurring.pay_day).all():
        d = min(max(r.pay_day or 1, 1), num_days)
        paid = _recurring_paid(r.id, year, month, r.category)
        if not paid:
            planned_out += r.amount or 0
        days[d].append({
            "kind": "recurring", "id": r.id, "title": f"🔄 {r.name}",
            "amount": r.amount or 0, "is_in": False, "paid": paid,
            "category": r.category, "wallet": r.wallet,
            "meta": "✅ To'langan" if paid else "Oylik doimiy to'lov"})

    # Rejalashtirilgan bir martalik to'lov/tushum
    mstr = f"{year}-{month:02d}"
    for f in FinPlan.query.filter(FinPlan.date.like(mstr + "%")).all():
        try:
            d = int(f.date[8:10])
        except (ValueError, IndexError):
            continue
        if not (1 <= d <= num_days):
            continue
        is_in = (f.direction == "in")
        overdue = (is_in and not f.is_paid
                   and _date(year, month, d) < today)
        if not f.is_paid:
            if is_in and not overdue:
                planned_in += f.amount or 0
            elif not is_in:
                planned_out += f.amount or 0
        days[d].append({
            "kind": "plan", "id": f.id,
            "title": ("📝 " + (f.description or "Reja")
                      + (" (QARZ!)" if overdue else "")),
            "amount": f.amount or 0, "is_in": is_in, "paid": f.is_paid,
            "category": f.category, "wallet": f.wallet,
            "overdue": overdue,
            "meta": ("⚠️ Muddati o'tgan!" if overdue else
                     "✅ To'landi" if f.is_paid else
                     ("Kutilgan tushum" if is_in else "Kutilgan to'lov"))})

    # Kunlik bashorat (running balance) + xavf darajasi
    actual = _actual_net_by_day(year, month)
    running = _opening_for_month(year, month)
    opening_balance = running
    min_proj = running
    grid = [None] * first_wd
    for d in range(1, num_days + 1):
        day_in = sum(e["amount"] for e in days[d]
                     if e["is_in"] and not e.get("paid")
                     and not e.get("overdue"))
        day_out = sum(e["amount"] for e in days[d]
                      if not e["is_in"] and not e.get("paid"))
        running += actual.get(d, 0.0) + day_in - day_out
        min_proj = min(min_proj, running)
        level = "gap" if running < 0 else ("warn" if running < buffer else "ok")
        grid.append({
            "day": d, "events": days[d], "inflow": day_in, "outflow": day_out,
            "running": running, "level": level,
            "is_today": (d == today.day and month == today.month
                         and year == today.year)})
    while len(grid) % 7:
        grid.append(None)

    prev_y, prev_m = (year, month - 1) if month > 1 else (year - 1, 12)
    next_y, next_m = (year, month + 1) if month < 12 else (year + 1, 1)

    wallets = FinWallet.query.order_by(FinWallet.sort).all()
    cats = FinCategory.query.order_by(FinCategory.direction.desc(),
                                      FinCategory.sort).all()
    recs = FinRecurring.query.order_by(FinRecurring.pay_day).all()
    return render_template(
        "finance_calendar.html", year=year, month=month,
        month_names=MONTH_NAMES, grid=grid, weeks=[grid[i:i + 7]
        for i in range(0, len(grid), 7)],
        planned_in=planned_in, planned_out=planned_out,
        net=planned_in - planned_out, opening_balance=opening_balance,
        min_proj=min_proj, buffer=buffer,
        at_risk=(min_proj < 0), below_buffer=(min_proj < buffer),
        prev_y=prev_y, prev_m=prev_m, next_y=next_y, next_m=next_m,
        wallets=wallets, cats=cats, recs=recs, sync=_sync_info())


@bp.route("/finance/calendar/plan/add", methods=["POST"])
@finance_required
def plan_add():
    d = (request.form.get("date") or "").strip()[:10]
    direction = "in" if request.form.get("direction") == "in" else "out"
    try:
        amount = float((request.form.get("amount") or "0").replace(" ", "")
                       .replace(",", "."))
    except ValueError:
        amount = 0
    if _bad_date(d) or _bad_amount(amount):
        flash("Sana va musbat summa kiritilishi shart", "error")
        return redirect(url_for("finance.calendar"))
    db.session.add(FinPlan(
        date=d, amount=amount, direction=direction,
        description=(request.form.get("description") or "").strip()[:300],
        category=(request.form.get("category") or "").strip()[:200],
        wallet=(request.form.get("wallet") or "").strip()[:120]))
    db.session.commit()
    flash("✅ Rejaga qo'shildi", "success")
    return redirect(url_for("finance.calendar", year=d[:4], month=int(d[5:7])))


@bp.route("/finance/calendar/plan/<int:pid>/delete", methods=["POST"])
@finance_required
def plan_delete(pid):
    f = FinPlan.query.get_or_404(pid)
    y, m = f.date[:4], int(f.date[5:7])
    FinTransaction.query.filter_by(plan_id=f.id, source="plan").delete()
    db.session.delete(f)
    db.session.commit()
    flash("🗑 Reja o'chirildi", "success")
    return redirect(url_for("finance.calendar", year=y, month=m))


@bp.route("/finance/calendar/recurring/add", methods=["POST"])
@finance_required
def recurring_add():
    name = (request.form.get("name") or "").strip()
    try:
        amount = float((request.form.get("amount") or "0").replace(" ", "")
                       .replace(",", "."))
        pay_day = int(request.form.get("pay_day") or "1")
    except ValueError:
        amount, pay_day = 0, 1
    if not name or _bad_amount(amount):
        flash("Nom va musbat summa kiritilishi shart", "error")
        return redirect(url_for("finance.calendar"))
    db.session.add(FinRecurring(
        name=name[:200], amount=amount, pay_day=min(max(pay_day, 1), 31),
        category=(request.form.get("category") or "").strip()[:200],
        wallet=(request.form.get("wallet") or "").strip()[:120]))
    db.session.commit()
    flash("✅ Doimiy to'lov qo'shildi", "success")
    return redirect(request.referrer or url_for("finance.calendar"))


@bp.route("/finance/calendar/recurring/<int:rid>/delete", methods=["POST"])
@finance_required
def recurring_delete(rid):
    r = FinRecurring.query.get_or_404(rid)
    db.session.delete(r)
    db.session.commit()
    flash("🗑 Doimiy to'lov o'chirildi", "success")
    return redirect(request.referrer or url_for("finance.calendar"))


@bp.route("/finance/calendar/pay", methods=["POST"])
@finance_required
def calendar_pay():
    """Rejali/doimiy to'lovni bajarish → moliya jurnaliga tranzaksiya tushadi."""
    kind = (request.form.get("kind") or "").strip()
    try:
        item_id = int(request.form.get("item_id") or "0")
    except ValueError:
        item_id = 0
    wallet = (request.form.get("wallet") or "").strip()[:60]
    # Faqat mavjud hisob (aks holda soxta/uzun nom jurnalga tushib, umumiy
    # pul manzarasini og'dirardi yoki Postgres'да 500 berardi) — noto'g'ri
    # bo'lsa bo'shatamiz, quyida reja/doimiy to'lovнинг o'z hisobi yoki
    # standart hisob ishlatiladi.
    if wallet and not FinWallet.query.filter_by(name=wallet).first():
        wallet = ""
    d = (request.form.get("date") or "").strip()[:10]
    if _bad_date(d):
        from datetime import date as _date
        d = _date.today().strftime("%Y-%m-%d")

    def _cat(name, fallback_dir, fallback_act="operating"):
        c = FinCategory.query.filter_by(name=name).first()
        return c

    if kind == "recurring":
        r = FinRecurring.query.get_or_404(item_id)
        if _recurring_paid(r.id, int(d[:4]), int(d[5:7]), r.category):
            flash("Bu doimiy to'lov shu oyda allaqachon to'langan/qoplangan",
                  "error")
            return redirect(url_for("finance.calendar"))
        cat = _cat(r.category, "out")
        db.session.add(FinTransaction(
            date=d, year=int(d[:4]), month=int(d[5:7]), amount=r.amount or 0,
            wallet=wallet or r.wallet or "РС Jalinga",
            purpose=f"Doimiy to'lov: {r.name}",
            category=cat.name if cat else (r.category or "прочие расходы"),
            direction=cat.direction if cat else "out",
            activity=cat.activity if cat else "operating",
            source="recurring", recurring_id=r.id))
        db.session.commit()
        flash(f"✅ «{r.name}» to'landi — jurnalga tushdi", "success")
        return redirect(url_for("finance.calendar", year=d[:4],
                                month=int(d[5:7])))

    if kind == "plan":
        f = FinPlan.query.get_or_404(item_id)
        if f.is_paid:
            flash("Bu reja allaqachon bajarilgan", "error")
            return redirect(url_for("finance.calendar"))
        cat = _cat(f.category, f.direction)
        db.session.add(FinTransaction(
            date=d, year=int(d[:4]), month=int(d[5:7]), amount=f.amount or 0,
            wallet=wallet or f.wallet or "РС Jalinga",
            purpose=f"Reja: {f.description}",
            category=cat.name if cat else (
                f.category or ("Прочие поступления" if f.direction == "in"
                               else "прочие расходы")),
            direction=cat.direction if cat else f.direction,
            activity=cat.activity if cat else "operating",
            source="plan", plan_id=f.id))
        f.is_paid = True
        db.session.commit()
        flash(f"✅ «{f.description}» bajarildi — jurnalga tushdi", "success")
        return redirect(url_for("finance.calendar", year=f.date[:4],
                                month=int(f.date[5:7])))

    flash("Noma'lum to'lov turi", "error")
    return redirect(url_for("finance.calendar"))


# ── Tahlil (statya strukturasi + kontragentlar) ─────────────────────────────

@bp.route("/finance/analysis")
@finance_required
def analysis():
    year = _pick_year()
    txns = FinTransaction.query.filter_by(year=year).filter(
        FinTransaction.activity != "technical").all()

    def _build(direction):
        cat_months = defaultdict(lambda: [0.0] * 13)
        for t in txns:
            if t.direction == direction:
                cat_months[t.category][t.month] += t.amount
        rows = []
        total = 0.0
        for name, months in cat_months.items():
            s = sum(months)
            total += s
            rows.append({"name": name, "months": months, "total": s})
        rows.sort(key=lambda r: -r["total"])
        for r in rows:
            r["share"] = (r["total"] / total * 100) if total else 0
        return rows, total

    exp_rows, exp_total = _build("out")
    inc_rows, inc_total = _build("in")

    # Kontragentlar (bo'sh bo'lmaganlar) — kim bo'yicha kirim/chiqim
    ctr = defaultdict(lambda: {"in": 0.0, "out": 0.0})
    for t in txns:
        who = (t.counterparty or "").strip()
        if who:
            ctr[who][t.direction] += t.amount
    counterparties = sorted(
        [{"name": k, "in": v["in"], "out": v["out"],
          "net": v["in"] - v["out"]} for k, v in ctr.items()],
        key=lambda x: -(x["in"] + x["out"]))[:20]

    return render_template(
        "finance_analysis.html", year=year, years=_years(),
        month_names=MONTH_NAMES, exp_rows=exp_rows, exp_total=exp_total,
        inc_rows=inc_rows, inc_total=inc_total,
        counterparties=counterparties, sync=_sync_info())


# ── Studiya to'lovlari (eski jurnal — paket/soatbay tasdiqlash) ─────────────

def _safe_back(month=None):
    """Ochiq-yo'naltirishdan himoya: faqat ichki /finance sahifasiga."""
    return redirect(url_for("finance.payments", month=month))


@bp.route("/finance/payments")
@finance_required
def payments():
    month = (request.args.get("month") or current_month_iso()).strip()[:7]
    rows = Payment.query.filter(Payment.date.like(month + "%")).order_by(
        Payment.is_paid.asc(), Payment.id.desc()).all()
    tmap = {t.id: t.name for t in Teacher.query.all()}
    items = []
    for p in rows:
        d = p.to_dict()
        d["teacher_name"] = tmap.get(p.teacher_id, "?")
        items.append(d)
    paid = sum(p.amount or 0 for p in rows if p.is_paid)
    pending = sum(p.amount or 0 for p in rows if not p.is_paid)
    wallets = FinWallet.query.order_by(FinWallet.sort).all()
    return render_template("finance_payments.html", items=items, month=month,
                           paid=paid, pending=pending,
                           wallets=[w.name for w in wallets],
                           methods=PAY_METHODS)


@bp.route("/finance/<int:pid>/pay", methods=["POST"])
@finance_required
def pay(pid):
    """To'lovni «to'landi» qiladi — QAYSI HISOB (hamyon)ga tushishini so'raydi
    va o'sha hisobga moliya kirim yozuvini bog'laydi (impulse-erp uslubi)."""
    from modules.finance.studio_link import sync_payment_to_finance
    p = Payment.query.get_or_404(pid)
    wallet = (request.form.get("wallet") or "").strip()[:60]
    method = (request.form.get("method") or "").strip()[:20]
    if method:
        p.method = method
    if wallet:
        p.wallet = wallet
    p.is_paid = True
    t = Teacher.query.get(p.teacher_id)
    tx = sync_payment_to_finance(p, teacher_name=t.name if t else None)
    record("pay", "payment",
           f"#{p.id} {(t.name if t else '?')} {p.amount:.0f} → "
           f"{tx.wallet if tx else '—'}")
    db.session.commit()
    if tx:   # bonus/nol summa moliyaga tushmaydi — yolg'on tasdiq bermaymiz
        flash(f"✅ To'landi — «{tx.wallet}» hisobiga moliya jurnaliga tushdi",
              "success")
    else:
        flash("✅ To'landi (bonus/nol summa — moliya jurnaliga tushmadi)",
              "success")
    return _safe_back(p.date[:7] if p.date else None)


@bp.route("/finance/<int:pid>/toggle", methods=["POST"])
@finance_required
def toggle(pid):
    from modules.finance.studio_link import sync_payment_to_finance
    p = Payment.query.get_or_404(pid)
    p.is_paid = not p.is_paid
    # «kutilmoqda»ga qaytganda p.wallet SAQLANADI — qayta «to'landi» qilinsa
    # o'sha hisobga tushsin (aks holda daromad boshqa hisobga ko'chib ketardi).
    # Tasdiqlanganда moliya jurnaliga kirim tushadi (bekor bo'lsa yo'qoladi)
    t = Teacher.query.get(p.teacher_id)
    sync_payment_to_finance(p, teacher_name=t.name if t else None)
    record("toggle", "payment",
           f"#{p.id} {(t.name if t else '?')} {p.amount:.0f} → "
           f"{'to`landi' if p.is_paid else 'kutilmoqda'}")
    db.session.commit()
    flash("✅ To'landi — moliya jurnaliga tushdi" if p.is_paid
          else "↩️ Kutilmoqda — moliyadan olib tashlandi", "success")
    return _safe_back(p.date[:7] if p.date else None)


@bp.route("/finance/<int:pid>/delete", methods=["POST"])
@finance_required
def delete(pid):
    from modules.finance.studio_link import unlink_payment_finance
    p = Payment.query.get_or_404(pid)
    month = p.date[:7] if p.date else None
    unlink_payment_finance(p.id)   # bog'langan moliya yozuvини ham o'chiramiz
    record("delete", "payment", f"#{p.id} {p.amount:.0f} ({p.date})")
    db.session.delete(p)
    db.session.commit()
    flash("🗑 To'lov o'chirildi", "success")
    return _safe_back(month)
