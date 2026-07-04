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

# SW versiyasi — o'zgarsa eski kesh tozalanadi (sw.js ichида ishlatiladi)
CACHE_VERSION = "jalinga-v2"


@bp.route("/manifest.webmanifest")
def manifest():
    data = {
        "id": "/",
        "name": f"{Config.COMPANY_NAME} — Boshqaruv",
        "short_name": "Jalinga",
        "description": "Jalinga Studio boshqaruv paneli: bron, mijozlar, "
                       "montaj, moliya.",
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
#  • navigatsiya (sahifa) so'rovlari — network-first, xato bo'lsa oflayn sahifa
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

  // Sahifa navigatsiyasi: preload/network-first → cache → oflayn
  if (req.mode === 'navigate') {
    e.respondWith((async () => {
      try {
        const preload = await e.preloadResponse;
        const res = preload || await fetch(req);
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      } catch (_) {
        const cached = await caches.match(req);
        return cached || caches.match('/offline');
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
