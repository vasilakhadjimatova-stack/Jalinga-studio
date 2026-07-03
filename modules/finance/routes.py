"""Moliya ERP — Google Sheets («Jalinga 2026») jurnali asosida.

Sahifalar: dashboard (hisoblar+KPI+grafiklar) · tranzaksiyalar jurnali ·
ДДС hisoboti (yillik pul oqimi) · qarzlar (DOLG) · dividendlar ·
studiya to'lovlari (eski jurnal). Sync: ochiq xlsx eksport orqali.
"""
import logging
from collections import defaultdict
from datetime import date

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash)

from config import Config
from core.auth import admin_required
from core.timeutils import current_month_iso
from database import db
from models.billing import Teacher, Payment
from models.finance import (FinWallet, FinCategory, FinTransaction,
                            FinDebt, FinSetting)
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
@admin_required
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

    return render_template(
        "finance.html", year=year, month=month, years=_years(),
        month_names=MONTH_NAMES,
        month_in=month_in, month_out=month_out,
        month_net=month_in - month_out,
        year_in=year_in, year_out=year_out,
        balances=balances, total_balance=total_balance,
        inc_series=[round(v) for v in inc[1:]],
        exp_series=[round(v) for v in exp[1:]],
        top_exp=top_exp, debt_out=debt_out, recent=recent,
        sync=_sync_info())


# ── Tranzaksiyalar jurnali ───────────────────────────────────────────────────

@bp.route("/finance/transactions")
@admin_required
def transactions():
    month = (request.args.get("month") or "").strip()[:7]   # YYYY-MM yoki ''
    wallet = (request.args.get("wallet") or "").strip()
    category = (request.args.get("category") or "").strip()
    dirf = (request.args.get("dir") or "").strip()
    q = (request.args.get("q") or "").strip()

    # Filtr berilmagan birinchi ochilishda — oxirgi faol oy
    if not month and not (wallet or category or dirf or q
                          or request.args.get("all")):
        y = _years()[-1]
        month = f"{y}-{_latest_month(y):02d}"

    qry = FinTransaction.query
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
@admin_required
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
    if len(d) != 10 or amount <= 0 or cat is None or not wallet:
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
    db.session.commit()
    flash("✅ Tranzaksiya qo'shildi", "success")
    return redirect(url_for("finance.transactions", month=d[:7]))


@bp.route("/finance/transactions/<int:tid>/delete", methods=["POST"])
@admin_required
def txn_delete(tid):
    t = FinTransaction.query.get_or_404(tid)
    if t.source == "sheet":
        flash("Sheets'dan kelgan yozuv o'chirilmaydi — Google Jadvalda "
              "o'zgartiring va sinxronlang", "error")
        return redirect(url_for("finance.transactions", month=t.date[:7]))
    if t.source == "studio":
        flash("Bu yozuv studiya to'loviга bog'langan — «Studiya to'lovlari» "
              "sahifasidan boshqaring", "error")
        return redirect(url_for("finance.transactions", month=t.date[:7]))
    month = t.date[:7]
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
@admin_required
def dds():
    year = _pick_year()
    report = build_dds(year)
    return render_template("finance_dds.html", r=report, year=year,
                           years=_years(), month_names=MONTH_NAMES,
                           sync=_sync_info())


# ── Qarzlar (DOLG) ───────────────────────────────────────────────────────────

@bp.route("/finance/debts")
@admin_required
def debts():
    rows = FinDebt.query.all()
    total = sum(d.amount or 0 for d in rows)
    repaid = sum(d.repaid or 0 for d in rows)
    return render_template("finance_debts.html", rows=rows, total=total,
                           repaid=repaid, outstanding=total - repaid,
                           sync=_sync_info())


# ── Dividendlar ──────────────────────────────────────────────────────────────

@bp.route("/finance/dividends")
@admin_required
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


# ── Sinxronizatsiya ──────────────────────────────────────────────────────────

@bp.route("/finance/sync", methods=["POST"])
@admin_required
def sync():
    from modules.finance.sheets_sync import sync_from_sheets
    try:
        stats = sync_from_sheets(Config.FINANCE_SPREADSHEET_ID,
                                 usd_rate=Config.USD_RATE)
        flash(f"✅ Sinxronlandi: {stats['transactions']} tranzaksiya, "
              f"{stats['wallets']} hisob, {stats['debts']} qarz", "success")
    except Exception as exc:
        logger.exception("Sheets sync xatosi")
        db.session.rollback()
        flash(f"Sync xatosi: {exc}", "error")
    return redirect(request.referrer or url_for("finance.index"))


# ── Studiya to'lovlari (eski jurnal — paket/soatbay tasdiqlash) ─────────────

def _safe_back(month=None):
    """Ochiq-yo'naltirishdan himoya: faqat ichki /finance sahifasiga."""
    return redirect(url_for("finance.payments", month=month))


@bp.route("/finance/payments")
@admin_required
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
    return render_template("finance_payments.html", items=items, month=month,
                           paid=paid, pending=pending)


@bp.route("/finance/<int:pid>/toggle", methods=["POST"])
@admin_required
def toggle(pid):
    from modules.finance.studio_link import sync_payment_to_finance
    p = Payment.query.get_or_404(pid)
    p.is_paid = not p.is_paid
    # Tasdiqlanganда moliya jurnaliga kirim tushadi (bekor bo'lsa yo'qoladi)
    t = Teacher.query.get(p.teacher_id)
    sync_payment_to_finance(p, teacher_name=t.name if t else None)
    db.session.commit()
    flash("✅ To'landi — moliya jurnaliga tushdi" if p.is_paid
          else "↩️ Kutilmoqda — moliyadan olib tashlandi", "success")
    return _safe_back(p.date[:7] if p.date else None)


@bp.route("/finance/<int:pid>/delete", methods=["POST"])
@admin_required
def delete(pid):
    from modules.finance.studio_link import unlink_payment_finance
    p = Payment.query.get_or_404(pid)
    month = p.date[:7] if p.date else None
    unlink_payment_finance(p.id)   # bog'langan moliya yozuvини ham o'chiramiz
    db.session.delete(p)
    db.session.commit()
    flash("🗑 To'lov o'chirildi", "success")
    return _safe_back(month)
