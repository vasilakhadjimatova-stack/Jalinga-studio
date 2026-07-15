"""PWA — telefonga o'rnatiladigan ilova (manifest + service worker + offline).

Railway HTTPS ostida ishlaydi: rahbar telefonда «Bosh ekranга qo'shish» bilan
ilovani o'rnatadi, u to'liq ekranда (brauzer paneliсiz) ochiladi. Service
worker asosiy oqimni tezlashtiradi va oflaynда «ulanish yo'q» sahifasini
ko'rsatadi. Barcha ma'lumot serverдан kelgani uchun to'liq oflayn ishlash
maqsad emas — installability + tezkor yuklanish + oflayn fallback.
"""
import json

from flask import Blueprint, Response, redirect, render_template, url_for

from config import Config

bp = Blueprint("pwa", __name__)

# SW versiyasi — o'zgarsa eski kesh tozalanadi (sw.js ichида ishlatiladi).
# v3: HTML sahifalar keshdan chiqarildi (CSRF token xato bug'ini tuzatadi).
CACHE_VERSION = "jalinga-v4"


@bp.route("/manifest.webmanifest")
def manifest():
    data = {
        "id": "/",
        "name": f"{Config.COMPANY_NAME} — Boshqaruv",
        "short_name": "Jalinga",
        "description": "Jalinga Studio boshqaruv paneli: bron, mijozlar, "
                       "studiya, moliya.",
        "lang": "uz",
        "dir": "ltr",
        "start_url": "/?src=pwa",
        "scope": "/",
        "display": "standalone",
        "display_override": ["standalone", "minimal-ui"],
        "orientation": "portrait-primary",
        "background_color": "#0B0C11",
        "theme_color": "#0B0C11",
        # Ikonка bosilganда yangi oyna emas — mavjud ilova oynasi ochiladi
        "launch_handler": {"client_mode": "navigate-existing"},
        "prefer_related_applications": False,
        "categories": ["business", "productivity", "finance"],
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/maskable-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "maskable"},
            {"src": "/static/icons/maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Kalendar / Bron", "url": "/calendar",
             "icons": [{"src": "/static/icons/icon-192.png",
                        "sizes": "192x192"}]},
            {"name": "Moliya", "url": "/finance",
             "icons": [{"src": "/static/icons/icon-192.png",
                        "sizes": "192x192"}]},
        ],
    }
    return Response(json.dumps(data, ensure_ascii=False),
                    mimetype="application/manifest+json")


@bp.route("/sw.js")
def service_worker():
    """Service worker — root scope (butun ilovani boshqaradi)."""
    js = _SW_JS.replace("__VERSION__", CACHE_VERSION)
    resp = Response(js, mimetype="application/javascript")
    # SW faylining o'zi keshlanmasin (yangilanish darhol yetib borsin)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@bp.route("/offline")
def offline():
    return render_template("offline.html")


@bp.route("/healthz")
def healthz():
    """Liveness/readiness — monitoring va Railway uchun. Baza ulanishini
    tekshiradi; DB yiqilsa 503 qaytaradi (sabab bilan)."""
    from sqlalchemy import text
    from database import db
    try:
        db.session.execute(text("SELECT 1"))
        # Sabab/dvigatel/flaglar OSHKOR QILINMAYDI — bu login-siz endpoint;
        # DB turi va xato matni (DSN/host tafsilotlarини o'z ichiga olishi
        # mumkin) begonaga ko'rinmasin. Tafsilot faqat serverда log qilinadi.
        return {"status": "ok"}, 200
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("healthz DB tekshiruvi xato: %s",
                                             exc)
        return {"status": "error"}, 503


# iOS/qurilmalar ba'zan ildizдаги ikonни avtomatik qidiradi (link teg bo'lsa
# ham). Static faylga yo'naltiramiz — ikonка har doim topiladi.
@bp.route("/apple-touch-icon.png")
@bp.route("/apple-touch-icon-precomposed.png")
@bp.route("/apple-touch-icon-120x120.png")
@bp.route("/apple-touch-icon-120x120-precomposed.png")
def apple_touch_icon():
    return redirect(url_for("static", filename="icons/apple-touch-icon.png"))


# ── Service worker manbasi ───────────────────────────────────────────────────
# Strategiya:
#  • navigatsiya (HTML sahifa) — FAQAT tarmoq (network-only), xato bo'lsa
#    oflayn sahifa. HTML KESHLANMAYDI: har sahifada sessiyaga bog'liq CSRF
#    tokeni bor — keshlangan eski token «CSRF token xato» (400) beradi.
#    Shuning uchun sahifalar doim serverdan yangi olinadi.
#  • /static/ resurslari — cache-first (tez, kam trafik)
#  • boshqa GET (shriftlar, CDN) — network, imkoni bo'lsa keshga oladi
#  • faqat GET keshlanadi; POST/boshqalar to'g'ridan-to'g'ri tarmoqqa
_SW_JS = r"""
const CACHE = '__VERSION__';
const PRECACHE = [
  '/offline',
  '/manifest.webmanifest',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/logo.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).catch(() => {})
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(Promise.all([
    caches.keys().then((keys) => Promise.all(
      keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))
    )),
    // Navigation preload — sahifa so'rovi SW ishga tushishini kutmaydi (tezroq)
    self.registration.navigationPreload ?
      self.registration.navigationPreload.enable() : Promise.resolve(),
  ]).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;                    // faqat GET
  const url = new URL(req.url);

  // Sahifa navigatsiyasi: FAQAT tarmoq (HTML hech qachon keshlanmaydi —
  // CSRF tokeni har sessiyada yangi). Tarmoq yo'q bo'lsagina oflayn sahifa.
  if (req.mode === 'navigate') {
    e.respondWith((async () => {
      try {
        const preload = await e.preloadResponse;
        return preload || await fetch(req);
      } catch (_) {
        return (await caches.match('/offline')) || Response.error();
      }
    })());
    return;
  }

  // Bir xil-manba statik resurslar: cache-first
  if (url.origin === self.location.origin && url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(req).then((cached) => cached || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      }))
    );
    return;
  }

  // Qolganlari (shriftlar, CDN): network, imkoni bo'lsa keshга nusxa
  e.respondWith(
    fetch(req).then((res) => {
      if (res && res.status === 200) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
      }
      return res;
    }).catch(() => caches.match(req))
  );
});
"""
