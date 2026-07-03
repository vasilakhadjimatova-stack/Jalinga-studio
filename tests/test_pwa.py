"""PWA — manifest, service worker, offline sahifa va meta-teglar."""
import json


def test_manifest(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert "manifest" in r.mimetype
    m = json.loads(r.data)
    assert m["display"] == "standalone"
    assert m["start_url"].startswith("/")
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
