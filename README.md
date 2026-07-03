# 🎬 Jalinga Studio ERP

Interaktiv video studiya boshqaruvi — ustozlar darslarini yozadigan studiya
uchun: bron, kalendar, ustozlar bazasi, paket/soatbay to'lovlar, boshliq paneli.

## MVP 1-bosqich (hozirgi)
- **📅 Kalendar** — kunlik ko'rinish, studiya bo'yicha; vaqt ustma-ust tushishi bloklanadi
- **👨‍🏫 Ustozlar** — mini-CRM: profil, paket sotish, soat balansi, yozuvlar tarixi
- **📦 Paket dvigateli** — N soatlik paket → balansdan avto-yechish; balans yetmasa bron bloklanadi; bekor bo'lsa soat qaytadi
- **💵 Soatbay** — bronda avtomatik to'lov (kutilmoqda) → Moliyada 1 tugma bilan tasdiqlanadi
- **📊 Boshliq paneli** — bugungi yozuvlar, oy tushumi, haftalik bandlik %, paketi tugayotgan ustozlar
- **🔐 Kirish** — 6 xonali shaxsiy kod (parolsiz, tez)

## 2-bosqich (tayyor)
- **🔗 Ustoz kabineti** — maxfiy havola (`/my/<token>`, parolsiz): balans, kelgusi yozuvlar, tarix
- **🟢 Online bron** — ustoz o'zi bo'sh vaqtga bron qiladi (konflikt/balans/o'tgan-vaqt himoyasi)
- **✕ Bekor qilish siyosati** — darsdan ≥24 soat oldin (paket soatlari qaytadi)
- **✈️ Telegram bot** — `/start <token>` bilan ulanish, bron tasdig'i, dars oldidan ~2 soat qolganda eslatma

## 3-bosqich (tayyor)
- **✂️ Montaj kanban** — yozildi → montajda → tekshiruvda → topshirildi; yozuv «done» bo'lgach karta avto-yaraladi
- **⏳ SLA nazorati** — default 3 kun; kechikkanlar qizil, tepada
- **👥 Jamoa ish yuki** — montajchiga biriktirish + ochiq kartalar soni
- **🎉 Topshirilganda** ustozga Telegram xabar (video havolasi bilan)

## 4-bosqich (tayyor)
- **🔥 Bandlik heatmap** — hafta kuni × soat (30 kun); bo'sh soatlarga chegirma strategiyasi uchun
- **📡 Churn radar** — 30+ kun yozilmagan ustozlar ro'yxati (qayta faollashtirish)
- **🏆 Top ustozlar** — 90 kunda eng ko'p soat yozganlar
- **🎁 Bonus soatlar** — referral/aksiya uchun pulisiz paket (faqat rahbar)

## Keyingi (ixtiyoriy)
- Onlayn to'lov (Payme/Click) — merchant hisob ochilgach ulanadi

## Ishga tushirish
```bash
pip install -r requirements.txt
ADMIN_CODE=123456 python app.py        # http://localhost:5060
```

### Muhit o'zgaruvchilari
| Nomi | Tavsif |
|------|--------|
| `SECRET_KEY` | Sessiya kaliti (prod'da majburiy) |
| `DATABASE_URL` | Postgres/SQLite (default: `sqlite:///jalinga.db`) |
| `ADMIN_CODE` | Birinchi admin kirish kodi (default: 111111 — o'zgartiring!) |
| `TELEGRAM_BOT_TOKEN` | Bot tokeni (@BotFather) — bo'lmasa bot jim o'chiq |

## Test
```bash
python -m pytest tests/ -q
```

## Deploy (Railway)
`railway.json` + `Procfile` tayyor — repo'ni ulasangiz avto-deploy bo'ladi.
`SECRET_KEY` va `ADMIN_CODE` env'larini qo'ying.

---
Arxitektura Impulse ERP'da sinalgan yondashuvga asoslangan:
Flask + SQLAlchemy (yengil avto-migratsiya) + Jinja2, modul-blueprint tuzilishi.
