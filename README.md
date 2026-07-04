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

## 5-bosqich — Moliya ERP (tayyor)
Google Sheets «Jalinga 2026» jadvali asosida to'liq moliya boshqaruvi
(Impulse moliya web uslubida):
- **📊 Moliya paneli** — hisoblar qoldig'i (РС, kartalar, naqd, $), oy
  tushum/xarajat/sof oqim KPI, 12 oylik grafik, xarajat strukturasi
- **📒 Tranzaksiyalar jurnali** — «ДДС данные» varag'i 1:1; filtr (oy,
  hisob, statya, yo'nalish, qidiruv) + qo'lda kirim/chiqim qo'shish
- **📈 Pul oqimi (ДДС)** — yillik hisobot oyma-oy: operatsion /
  investitsion / moliyaviy bo'limlar, ochilish-yopilish qoldiqlari
  (Sheets'dagi ДДС_2026 bilan tiyingacha mos — testda qotirilgan)
- **📅 To'lov kalendari** — oylik to'r + kunlik kassa bashorati:
  doimiy oylik to'lovlar (ijara, obunalar) + rejali bir martalik
  to'lov/tushumlar; qizil/sariq/yashil xavf darajalari va «likvidlik xavfi»
  ogohlantirishi (`CASH_SAFETY_BUFFER` buferi). Reja/doimiy to'lov
  «To'landi» bo'lganda jurnalga tushadi; o'sha oyда statya bo'yicha
  haqiqiy chiqim bo'lsa ikki marta sanalmaydi (reconciliation).
- **📊 Tahlil** — yillik statya kesimi (xarajat/tushum ulush foizi +
  donut) va kontragentlar reytingi (kim bo'yicha kirim/chiqim/sof)
- **📉 Yig'ma qoldiq grafigi** — panelда oy oxiri kassa qoldig'i chizig'i
- **🤝 Qarzlar** — DOLG varag'i: kimga, qancha, qaytish foizi
- **👑 Dividendlar** — ta'sischi to'lovlari tarixi
- **⚙️ Dastur-native** — moliya to'liq dastur ichida yuritiladi (Google
  Sheets bog'liqligi yo'q). Sozlamalar sahifasida hisoblar (ochilish
  qoldig'i) va ДДС statyalarini boshqarasiz; tranzaksiyalarni qo'sh/tahrir/
  o'chirasiz; qarzlarni to'liq yuritasiz (qo'shish/qaytarish/o'chirish).
  Jadvaldan olingan tarix (yanvar–iyun) endi to'liq tahrirlanadi.
  `data/finance_snapshot.json` faqat birinchi ishga tushishда boshlang'ich
  ma'lumot uchun (keyin ishlatilmaydi).
- **🔗 Studiya to'lovi → moliya** — mijoz to'lovi «To'landi» deb
  tasdiqlanганda moliya jurnalida avtomatik «Поступление от клиента (запись)»
  kirim paydo bo'ladi (bekor/o'chirilса — yo'qoladi). Studiya operatsiyalari
  va moliya bitta ДДС manzarasida birlashadi.
- **🔐 Faqat rahbar** — butun Moliya bo'limi `admin` rolli foydalanuvchi
  uchun (operator ko'rmaydi, nav'da ham chiqmaydi).

## 6-bosqich — Telefon ilovasi (PWA, tayyor)
Butun panel telefonga o'rnatiladigan ilovaga aylantirildi (native app kerak
emas, App Store/Play Market ham):
- **📲 Bosh ekranga qo'shish** — rahbar telefonда «Ilovani o'rnatish»
  tugmasini bosadi (Android/Chrome) yoki iOS Safari'да «Ulashish → Bosh
  ekranga qo'shish». Ilova to'liq ekranда, o'z ikonкаsi bilan, brauzer
  paneliсiz ochiladi.
- **⚡ Service worker** — sahifalar tez yuklanadi (kesh + navigation
  preload), oflaynда «ulanish yo'q» sahifasi, ulanish tiklansa
  avto-yangilanadi.
- **🎨 Ikonlar** — `static/icons/` (192/512 + maskable + apple-touch);
  logotipdan generatsiya qilingan, to'q premium fon.
- **✨ Native-his UX** — iOS splash ekranlari (oq ekran o'rniga logotipli
  to'q splash, 6 o'lcham), sahifalar orasida silliq o'tish
  (view-transitions), navigatsiya progress-bar, pull-to-refresh
  (faqat o'rnatilgan ilovada), pastki nav haptik, notch/status-bar
  safe-area, ikonка bosilganда dublikat oyna ochilmaydi
  (launch_handler: navigate-existing).
- **Manzil**: `/manifest.webmanifest`, `/sw.js`, `/offline` — HTTPS
  (Railway) ostida installability talablariga to'liq javob beradi.

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
| `FINANCE_SPREADSHEET_ID` | Google Sheets ID (default: Jalinga 2026 jadvali) |
| `USD_RATE` | $ kassa uchun so'm kursi (default: 12000) |
| `CASH_SAFETY_BUFFER` | To'lov kalendari minimal kassa zaxirasi (default: 20 mln) |

## Test
```bash
python -m pytest tests/ -q
```

## ⚠️ Ma'lumot xavfsizligi (MUHIM)
**Productionда doimiy PostgreSQL ulang** — aks holda ma'lumot yo'qoladi.
Railway (va shunga o'xshash platformalar) konteyneri fayl tizimi
**vaqtinchalik**: agar `DATABASE_URL` o'rnatilmasa, ilova `sqlite:///jalinga.db`
faylga yozadi va **har deploy/restart'да butun baza (mijozlar, bronlar,
to'lovlar, moliya) o'chib ketadi**.

**Yechim (5 daqiqa):**
1. Railway → **New → Database → PostgreSQL** qo'shing.
2. Railway `DATABASE_URL`ni avtomatik ulaydi — qo'shimcha sozlash shart emas
   (kod `postgres://` → `postgresql://` ni o'zi to'g'rilaydi, `psycopg2`
   drayveri `requirements.txt`да bor).
3. Deploy'дан keyin ilova Postgres'ga yozadi; jadvallar avto-yaraladi.

Himoyalar:
- Production + SQLite aniqlansa — startда **CRITICAL log** va panelда rahbarга
  **qizil ogohlantirish banneri** chiqadi.
- **Zaxira nusxa**: Jamoa sahifasida «Butun bazani yuklab olish (.json)» —
  rahbar istagan payt hamma ma'lumotni faylga saqlaydi (off-platforma backup,
  SQLite→Postgres ko'chirishда ham asqotadi).
- Baza sxemasi hech qachon o'chirilmaydi: `create_all` faqat yangi jadval
  yaratadi, migratsiya faqat ustun qo'shadi — kod ma'lumotni o'chirmaydi.

## Deploy (Railway)
`railway.json` + `Procfile` tayyor — repo'ni ulasangiz avto-deploy bo'ladi.
Majburiy env'lar: `SECRET_KEY`, `ADMIN_CODE`, va **`DATABASE_URL` (PostgreSQL)**.

---
Arxitektura Impulse ERP'da sinalgan yondashuvga asoslangan:
Flask + SQLAlchemy (yengil avto-migratsiya) + Jinja2, modul-blueprint tuzilishi.
