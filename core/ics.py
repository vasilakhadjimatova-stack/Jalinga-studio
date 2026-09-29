"""iCalendar (RFC 5545) lentasi — bronlar telefon kalendarida.

Jahon amaliyoti (Calendly, Acuity, Mindbody): mijoz yoki xodim bir marta
«kalendarga ulash» qiladi — keyin Google/Apple/Outlook kalendari lentani
o'zi yangilab turadi. Ilova ochish shart emas, eslatma telefonning o'zidan.

Vaqt UTC'da yoziladi (Toshkent = UTC+5, yozgi vaqt yo'q) — VTIMEZONE
blokisiz ham har qanday kalendar to'g'ri ko'rsatadi.
"""
from datetime import datetime, timedelta

from core.timeutils import now_tashkent

_TZ_OFFSET = timedelta(hours=5)


def _esc(s):
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r", "").replace("\n", "\\n"))


def _fold(line):
    """75 oktetdan uzun qatorlarni RFC 5545 bo'yicha bukish (UTF-8 xavfsiz)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def _utc(date_s, hhmm):
    local = datetime.strptime(f"{date_s} {hhmm}", "%Y-%m-%d %H:%M")
    return (local - _TZ_OFFSET).strftime("%Y%m%dT%H%M%SZ")


def build_calendar(name, events, alarm_minutes=None):
    """events: [{uid, date, start, end, summary, description, location}]."""
    stamp = (now_tashkent() - _TZ_OFFSET).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0",
           "PRODID:-//Jalinga Studio//Bronlar//UZ", "CALSCALE:GREGORIAN",
           "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(name)}",
           "X-WR-TIMEZONE:Asia/Tashkent",
           "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
           "X-PUBLISHED-TTL:PT1H"]
    for e in events:
        try:
            dtstart, dtend = _utc(e["date"], e["start"]), _utc(e["date"], e["end"])
        except (ValueError, KeyError):
            continue
        out += ["BEGIN:VEVENT", f"UID:{e['uid']}", f"DTSTAMP:{stamp}",
                f"DTSTART:{dtstart}", f"DTEND:{dtend}",
                f"SUMMARY:{_esc(e.get('summary'))}", "STATUS:CONFIRMED"]
        if e.get("description"):
            out.append(f"DESCRIPTION:{_esc(e['description'])}")
        if e.get("location"):
            out.append(f"LOCATION:{_esc(e['location'])}")
        if alarm_minutes:
            out += ["BEGIN:VALARM", "ACTION:DISPLAY",
                    f"DESCRIPTION:{_esc(e.get('summary'))}",
                    f"TRIGGER:-PT{int(alarm_minutes)}M", "END:VALARM"]
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in out) + "\r\n"


def feed_window():
    """Lentaga kiradigan davr: o'tgan 30 kun … kelgusi 180 kun."""
    d0 = now_tashkent().date()
    return ((d0 - timedelta(days=30)).strftime("%Y-%m-%d"),
            (d0 + timedelta(days=180)).strftime("%Y-%m-%d"))
