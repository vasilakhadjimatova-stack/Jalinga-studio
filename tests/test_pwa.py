"""PWA — manifest, service worker, offline sahifa va meta-teglar."""
import json


def test_manifest(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert "manifest" in r.mimetype
    m = json.loads(r.data)
    assert m["display"] == "standalone"
    assert m["start_url"].startswith("/")
    assert m["id"] == "/"
    # Ikonка bosilganда mavjud oyna ochilsin (dublikat emas)
    assert m["launch_handler"]["client_mode"] == "navigate-existing"
    # 192 va 512 ikonlar (installability talabi) + maskable
    sizes = {i["sizes"] for i in m["icons"]}
    assert "192x192" in sizes and "512x512" in sizes
    assert any(i.get("purpose") == "maskable" for i in m["icons"])


def test_service_worker(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.mimetype
    assert r.headers.get("Service-Worker-Allowed") == "/"
    # SW keshlanmasligi kerak (yangilanish darhol yetsin)
    assert "no-cache" in r.headers.get("Cache-Control", "")
    assert b"addEventListener" in r.data and b"fetch" in r.data
    # Navigation preload — tezroq sahifa yuklanishi
    assert b"navigationPreload" in r.data and b"preloadResponse" in r.data


def test_native_feel_assets(admin_client):
    """iOS splash, view-transition, pull-to-refresh va progress-bar mavjud."""
    r = admin_client.get("/")
    assert b"apple-touch-startup-image" in r.data
    assert b"@view-transition" in r.data
    assert b"navprog" in r.data      # navigatsiya progress-bar
    assert b"ptr" in r.data          # pull-to-refresh
    # Splash fayllari real mavjud
    assert admin_client.get(
        "/static/splash/splash-390x844-3x.png").status_code == 200


def test_offline_page(client):
    r = client.get("/offline")
    assert r.status_code == 200
    assert "Ulanish yo'q".encode() in r.data


def test_pwa_meta_in_pages(admin_client):
    """Barcha sahifalarда manifest linki, apple-touch va SW registratsiyasi."""
    r = admin_client.get("/")
    assert b"manifest.webmanifest" in r.data
    assert b"apple-touch-icon" in r.data
    assert b"serviceWorker" in r.data
    assert b'name="theme-color"' in r.data


def test_pwa_routes_public(client):
    """Manifest/SW/offline login talab qilmaydi (o'rnatishдан oldin kerak)."""
    for url in ("/manifest.webmanifest", "/sw.js", "/offline"):
        assert client.get(url).status_code == 200


def test_sw_does_not_cache_html(client):
    """CSRF bug tuzatilgan: SW HTML sahifalarni keshlamaydi (network-only)."""
    sw = client.get("/sw.js").get_data(as_text=True)
    assert "jalinga-v" in sw          # versiya bo'lsa bo'ldi (v3, v4, ...)
    nav = sw.split("navigate")[1].split("static")[0]
    assert "c.put(req" not in nav          # navigatsiyada keshga yozilmaydi
    assert "await fetch(req)" in nav        # to'g'ridan-to'g'ri tarmoq
