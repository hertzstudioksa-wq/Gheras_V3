"""Stabilization pass tests: user-data sanitization, unified progress, retry, Arabic PDF, video assembly."""
import io
import json
import os
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@gheras.com"
ADMIN_PASSWORD = "Admin@1234"
DELIVERED_ORDER_ID = "4c357bfc-3092-4eb6-8c2a-105a6662766b"

INTERNAL_ORDER_KEYS = {
    "ai_prompt_snapshot", "prompt_edited", "scenarios_generation", "production_generation",
    "status_history", "admin_note", "asset_generation_run_id", "final_assembly_run_id",
    "production_plan_id", "current_scenario_batch_id", "selected_scenario_batch_id",
    "asset_generation_started_at", "asset_generation_completed_at",
    "final_assembly_started_at", "final_assembly_completed_at",
}
INTERNAL_DEEP_KEYS = {
    "prompt_used", "image_prompt", "animation_prompt", "visual_description",
    "ai_plan_snapshot_json", "ai_plan_snapshot",
}


def _deep_find(obj, keys):
    """Return set of banned keys found anywhere inside the JSON object."""
    found = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in keys:
                    found.add(k)
                walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)

    walk(obj)
    return found


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------------- (1) Order detail sanitization ----------------
def test_order_detail_no_internal_keys(h):
    r = requests.get(f"{BASE_URL}/api/orders/{DELIVERED_ORDER_ID}", headers=h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    leaked_top = INTERNAL_ORDER_KEYS & set(body.keys())
    assert not leaked_top, f"Top-level internal keys leaked: {leaked_top}"
    deep = _deep_find(body, INTERNAL_DEEP_KEYS)
    assert not deep, f"Deep banned keys leaked in order detail: {deep}"


# ---------------- (2) Production summary ----------------
def test_production_summary_shape_and_progress(h):
    r = requests.get(f"{BASE_URL}/api/orders/{DELIVERED_ORDER_ID}/production-summary",
                     headers=h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    # Progress must exist with required keys
    assert "progress" in body, body.keys()
    p = body["progress"]
    for k in ("stage", "stage_ar", "percent", "message_ar"):
        assert k in p, f"missing progress.{k}: {p}"
    assert isinstance(p["percent"], int) and 0 <= p["percent"] <= 100
    # No leakage
    deep = _deep_find(body, INTERNAL_DEEP_KEYS | {"source"})
    # "source" may appear in admin paths — here must not
    assert "source" not in deep, "source leaked in user production-summary"
    # delivered order → progress.percent should be 100
    if body.get("raw_status") == "delivered":
        assert p["percent"] == 100


# ---------------- (3) Scenarios allow-list ----------------
ALLOWED_SCEN_KEYS = {"id", "scenario_index", "title", "short_summary", "emotional_angle",
                     "learning_goal", "visual_style_hint", "estimated_scene_count",
                     "why_this_fits", "is_selected"}


def test_scenarios_allow_list(h):
    r = requests.get(f"{BASE_URL}/api/orders/{DELIVERED_ORDER_ID}/scenarios",
                     headers=h, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    # Top level must not carry a generation block
    assert "generation" not in body
    assert "current_scenario_batch_id" not in body
    for s in body.get("scenarios", []):
        extras = set(s.keys()) - ALLOWED_SCEN_KEYS
        assert not extras, f"scenario exposes forbidden keys: {extras}"


# ---------------- (4) Media status unified progress ----------------
def test_media_status_unified_progress(h):
    r = requests.get(f"{BASE_URL}/api/orders/{DELIVERED_ORDER_ID}/media-status",
                     headers=h, timeout=30)
    assert r.status_code == 200, r.text
    b = r.json()
    assert "progress" in b and "progress_percent" in b
    p = b["progress"]
    for k in ("stage", "stage_ar", "percent", "message_ar"):
        assert k in p
    # consistency
    assert b["progress_percent"] == p["percent"]
    # No internal keys
    assert not _deep_find(b, INTERNAL_DEEP_KEYS)


# ---------------- (5) Delivery endpoint ----------------
def test_delivery_payload(h):
    r = requests.get(f"{BASE_URL}/api/orders/{DELIVERED_ORDER_ID}/delivery",
                     headers=h, timeout=30)
    assert r.status_code == 200, r.text
    b = r.json()
    assert "progress_percent" in b
    # For delivered, percent should be 100
    if b.get("status") == "delivered":
        assert b["progress_percent"] == 100
    # video and pdf block presence (may be null if assembly not run)
    assert "video" in b and "pdf" in b


# ---------------- (6) Retry-delivery endpoint exists ----------------
def test_retry_delivery_endpoint_exists(h):
    r = requests.post(f"{BASE_URL}/api/orders/{DELIVERED_ORDER_ID}/retry-delivery",
                      headers=h, timeout=30)
    # Delivered order — production_approved=True so it should accept. It either
    # returns 200 or (rarely) 400; must NOT be 404.
    assert r.status_code in (200, 400), f"unexpected {r.status_code}: {r.text}"
    if r.status_code == 200:
        assert r.json().get("ok") is True


def test_retry_delivery_requires_auth():
    r = requests.post(f"{BASE_URL}/api/orders/{DELIVERED_ORDER_ID}/retry-delivery", timeout=30)
    assert r.status_code in (401, 403), r.status_code


# ---------------- (7) Video assembly regenerate + placeholders ----------------
def test_admin_delivery_regenerate_produces_video(h):
    # Kick off regeneration
    r = requests.post(f"{BASE_URL}/api/admin/orders/{DELIVERED_ORDER_ID}/delivery/regenerate",
                      headers=h, timeout=30)
    assert r.status_code == 200, r.text
    # Poll admin delivery until video_url appears (up to ~90s)
    deadline = time.time() + 180
    video = None
    while time.time() < deadline:
        try:
            g = requests.get(f"{BASE_URL}/api/admin/orders/{DELIVERED_ORDER_ID}/delivery",
                             headers=h, timeout=60).json()
        except Exception:
            time.sleep(5)
            continue
        video = g.get("video")
        status = g.get("status")
        if video and video.get("video_url") and status in ("delivered",):
            break
        time.sleep(5)
    assert video and video.get("video_url"), f"no video_url after regenerate: {video}"
    meta = video.get("assembly_metadata") or {}
    assert "placeholder_frames" in meta, f"assembly_metadata missing placeholder_frames: {meta}"


# ---------------- (8) PDF Amiri font check ----------------
def test_pdf_uses_amiri_and_arabic_shaping(h):
    g = requests.get(f"{BASE_URL}/api/admin/orders/{DELIVERED_ORDER_ID}/delivery",
                     headers=h, timeout=60).json()
    pdf = g.get("pdf") or {}
    pdf_url = pdf.get("pdf_url")
    assert pdf_url, "no pdf_url on delivered order"
    # Make absolute if relative
    if pdf_url.startswith("/"):
        pdf_url = f"{BASE_URL}{pdf_url}"
    # Fetch PDF bytes
    pr = requests.get(pdf_url, headers=h, timeout=120)
    assert pr.status_code == 200
    content = pr.content
    assert content[:4] == b"%PDF", "not a PDF"
    # Check font is Amiri (embedded)
    has_amiri = b"Amiri" in content
    # Extract text
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        text = "".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:
        pytest.fail(f"pypdf failed: {e}")
    # Count arabic chars (U+0600..U+06FF) or presentation forms (FB50..FEFF)
    arabic = sum(1 for c in text if "\u0600" <= c <= "\u06FF" or "\uFB50" <= c <= "\uFEFF")
    assert arabic > 10, f"too few Arabic glyphs in PDF text (got {arabic}); Amiri embed? {has_amiri}"
    assert has_amiri, "Amiri font not embedded in PDF"
