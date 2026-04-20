"""Gheras Phase 2 backend tests (pytest) — structured orders, uploads, drafts, admin."""
import os
import struct
import uuid
import zlib

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@gheras.com"
ADMIN_PASSWORD = "Admin@1234"
RUN_TAG = uuid.uuid4().hex[:6]
PARENT_EMAIL = f"parent_{RUN_TAG}@test.com"
PARENT2_EMAIL = f"parent2_{RUN_TAG}@test.com"
PARENT_PASSWORD = "test123"


def _tiny_png_bytes() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_chunk = struct.pack(">I", 13) + ihdr + struct.pack(">I", zlib.crc32(ihdr) & 0xffffffff)
    raw = b"\x00\xff\x00\x00"
    comp = zlib.compress(raw)
    idat = b"IDAT" + comp
    idat_chunk = struct.pack(">I", len(comp)) + idat + struct.pack(">I", zlib.crc32(idat) & 0xffffffff)
    iend = b"IEND"
    iend_chunk = struct.pack(">I", 0) + iend + struct.pack(">I", zlib.crc32(iend) & 0xffffffff)
    return sig + ihdr_chunk + idat_chunk + iend_chunk


@pytest.fixture(scope="session")
def session():
    return requests.Session()


@pytest.fixture(scope="session")
def admin_token(session):
    r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data["user"]["role"] == "admin"
    return data["access_token"]


@pytest.fixture(scope="session")
def parent_token(session):
    r = session.post(f"{API}/auth/register", json={
        "email": PARENT_EMAIL, "password": PARENT_PASSWORD, "full_name": "Parent Test"
    })
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    tok = r.json()["access_token"]
    r2 = session.post(f"{API}/auth/login", json={"email": PARENT_EMAIL, "password": PARENT_PASSWORD})
    assert r2.status_code == 200
    return tok


@pytest.fixture(scope="session")
def parent2_token(session):
    r = session.post(f"{API}/auth/register", json={
        "email": PARENT2_EMAIL, "password": PARENT_PASSWORD, "full_name": "Parent Two"
    })
    assert r.status_code == 200
    return r.json()["access_token"]


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------- Health + Public ----------
def test_health(session):
    r = session.get(f"{API}/")
    assert r.status_code == 200
    d = r.json()
    assert d.get("ok") is True
    assert str(d.get("version")) == "2"


def test_public_categories(session):
    r = session.get(f"{API}/public/categories")
    assert r.status_code == 200
    cats = r.json()
    assert len(cats) == 8, f"expected 8 got {len(cats)}"
    for c in cats:
        assert "_id" not in c and isinstance(c.get("subcategories"), list)
    assert any(len(c["subcategories"]) > 0 for c in cats)


def test_public_story_options(session):
    r = session.get(f"{API}/public/story-options")
    assert r.status_code == 200
    g = r.json()
    assert set(g.keys()) == {"type", "tone", "setting", "language", "voice"}
    assert len(g["type"]) == 5 and len(g["tone"]) == 4 and len(g["setting"]) == 5
    assert len(g["language"]) == 3 and len(g["voice"]) == 3


def test_public_settings(session):
    r = session.get(f"{API}/public/settings")
    assert r.status_code == 200
    s = r.json()
    assert "characters.max_count" in s and "upload.max_mb" in s


def test_auth(admin_token, parent_token):
    assert admin_token and parent_token


# ---------- Uploads ----------
@pytest.fixture(scope="session")
def uploaded_child_file(session, parent_token):
    png = _tiny_png_bytes()
    r = session.post(f"{API}/uploads/image", headers=H(parent_token),
                     files={"file": ("t.png", png, "image/png")},
                     data={"scope": "child"})
    assert r.status_code == 200, f"upload failed: {r.status_code} {r.text}"
    j = r.json()
    assert j["url"].startswith("/api/uploads/file/")
    return j


def test_upload_happy_path(uploaded_child_file):
    assert uploaded_child_file["id"]


def test_download_with_bearer(session, parent_token, uploaded_child_file):
    r = session.get(f"{API}/uploads/file/{uploaded_child_file['id']}", headers=H(parent_token))
    assert r.status_code == 200 and len(r.content) > 0


def test_download_with_query_auth(session, parent_token, uploaded_child_file):
    r = session.get(f"{API}/uploads/file/{uploaded_child_file['id']}?auth={parent_token}")
    assert r.status_code == 200


def test_download_other_user_forbidden(session, parent2_token, uploaded_child_file):
    r = session.get(f"{API}/uploads/file/{uploaded_child_file['id']}", headers=H(parent2_token))
    assert r.status_code == 403


def test_download_no_auth_401(session, uploaded_child_file):
    r = session.get(f"{API}/uploads/file/{uploaded_child_file['id']}")
    assert r.status_code == 401


def test_admin_can_access_any_file(session, admin_token, uploaded_child_file):
    r = session.get(f"{API}/uploads/file/{uploaded_child_file['id']}", headers=H(admin_token))
    assert r.status_code == 200


def test_upload_wrong_ext(session, parent_token):
    r = session.post(f"{API}/uploads/image", headers=H(parent_token),
                     files={"file": ("bad.txt", b"hello", "text/plain")},
                     data={"scope": "child"})
    assert r.status_code == 400


def test_upload_invalid_scope(session, parent_token):
    r = session.post(f"{API}/uploads/image", headers=H(parent_token),
                     files={"file": ("t.png", _tiny_png_bytes(), "image/png")},
                     data={"scope": "evil"})
    assert r.status_code == 400


# ---------- Drafts ----------
def test_drafts_lifecycle(session, parent_token):
    r = session.get(f"{API}/drafts/current", headers=H(parent_token))
    assert r.status_code == 200
    r = session.put(f"{API}/drafts/current", headers=H(parent_token),
                    json={"current_step": 3, "data": {"x": 1}})
    assert r.status_code == 200
    r = session.get(f"{API}/drafts/current", headers=H(parent_token))
    assert r.json().get("current_step") == 3
    r = session.delete(f"{API}/drafts/current", headers=H(parent_token))
    assert r.status_code == 200


# ---------- Orders ----------
def _build_data(session, url, n=2):
    cats = session.get(f"{API}/public/categories").json()
    opts = session.get(f"{API}/public/story-options").json()
    cat = cats[0]
    sub = cat["subcategories"][0] if cat["subcategories"] else None
    chars = [
        {"type": "mother", "name": "سارة", "role": "visible"},
        {"type": "friend", "name": "أحمد", "role": "mentioned"},
        {"type": "teacher", "name": "يوسف", "role": "visible"},
        {"type": "sibling", "name": "لمى", "role": "visible"},
    ][:n]
    return {
        "goal": {"category_id": cat["id"],
                 "subcategory_id": sub["id"] if sub else None,
                 "context": "موقف حقيقي: رفض ترتيب ألعابه."},
        "child": {"name": "ريان", "age": 6, "gender": "male",
                  "image_url": url, "appearance_notes": "شعر أسود", "hijab": False},
        "characters": chars,
        "personalization": {"favorites": {"toy": {"selected": True, "name": "دبدوب"}},
                            "custom_notes": "يحب النجوم"},
        "style": {"type_id": opts["type"][0]["id"], "tone_id": opts["tone"][0]["id"],
                  "setting_id": opts["setting"][0]["id"],
                  "language_id": opts["language"][0]["id"],
                  "voice_id": opts["voice"][0]["id"]},
    }, cat, sub


@pytest.fixture(scope="session")
def created_order(session, parent_token, uploaded_child_file):
    session.put(f"{API}/drafts/current", headers=H(parent_token),
                json={"current_step": 6, "data": {"marker": "pre"}})
    data, cat, sub = _build_data(session, uploaded_child_file["url"], 2)
    r = session.post(f"{API}/orders", headers=H(parent_token), json={"data": data})
    assert r.status_code == 200, f"order create: {r.status_code} {r.text}"
    o = r.json()
    assert "ريان" in o["ai_prompt_snapshot"]
    assert cat["name_ar"] in o["ai_prompt_snapshot"]
    if sub:
        assert sub["name_ar"] in o["ai_prompt_snapshot"]
    assert "موقف حقيقي" in o["ai_prompt_snapshot"]
    return o


def test_order_create(created_order):
    assert created_order["status"] == "pending" and created_order["prompt_edited"] is False


def test_order_clears_draft(session, parent_token, created_order):
    d = session.get(f"{API}/drafts/current", headers=H(parent_token)).json()
    assert d.get("data", {}).get("marker") != "pre"


def test_orders_list(session, parent_token, created_order):
    items = session.get(f"{API}/orders", headers=H(parent_token)).json()
    it = next(i for i in items if i["id"] == created_order["id"])
    assert it["child_name"] == "ريان" and it["category_name"] and it["status_ar"]
    assert "ai_prompt_snapshot" not in it


def test_order_detail(session, parent_token, created_order):
    o = session.get(f"{API}/orders/{created_order['id']}", headers=H(parent_token)).json()
    assert "data" in o and o["ai_prompt_snapshot"]


def test_order_detail_other_user_404(session, parent2_token, created_order):
    r = session.get(f"{API}/orders/{created_order['id']}", headers=H(parent2_token))
    assert r.status_code == 404


def test_order_too_many_chars(session, parent_token, uploaded_child_file):
    data, _, _ = _build_data(session, uploaded_child_file["url"], 4)
    r = session.post(f"{API}/orders", headers=H(parent_token), json={"data": data})
    assert r.status_code == 400


def test_order_invalid_category(session, parent_token, uploaded_child_file):
    data, _, _ = _build_data(session, uploaded_child_file["url"], 1)
    data["goal"]["category_id"] = "bad-id"
    r = session.post(f"{API}/orders", headers=H(parent_token), json={"data": data})
    assert r.status_code == 400


# ---------- Admin orders ----------
def test_admin_orders_list(session, admin_token, created_order):
    items = session.get(f"{API}/admin/orders", headers=H(admin_token)).json()
    it = next((i for i in items if i["id"] == created_order["id"]), None)
    assert it and it["user_email"] == PARENT_EMAIL and it["child_name"] == "ريان"


def test_admin_order_detail(session, admin_token, created_order):
    o = session.get(f"{API}/admin/orders/{created_order['id']}", headers=H(admin_token)).json()
    assert o["ai_prompt_snapshot"] and o["user_email"] == PARENT_EMAIL


def test_admin_status_transitions(session, admin_token, created_order):
    oid = created_order["id"]
    for st in ["in_review", "ready_for_ai", "generating", "completed", "pending"]:
        r = session.patch(f"{API}/admin/orders/{oid}/status",
                          headers=H(admin_token), json={"status": st})
        assert r.status_code == 200
        assert session.get(f"{API}/admin/orders/{oid}", headers=H(admin_token)).json()["status"] == st


def test_admin_edit_and_regenerate_prompt(session, admin_token, created_order):
    oid = created_order["id"]
    r = session.patch(f"{API}/admin/orders/{oid}/prompt",
                      headers=H(admin_token), json={"ai_prompt_snapshot": "محرر"})
    assert r.status_code == 200
    rd = session.get(f"{API}/admin/orders/{oid}", headers=H(admin_token)).json()
    assert rd["ai_prompt_snapshot"] == "محرر" and rd["prompt_edited"] is True
    r = session.post(f"{API}/admin/orders/{oid}/regenerate-prompt", headers=H(admin_token))
    assert r.status_code == 200
    rd = session.get(f"{API}/admin/orders/{oid}", headers=H(admin_token)).json()
    assert rd["prompt_edited"] is False and "ريان" in rd["ai_prompt_snapshot"]


# ---------- Admin story-options ----------
def test_admin_story_options_crud_and_hidden(session, admin_token):
    payload = {"kind": "type", "name_ar": "تجريبي", "value": f"t-{RUN_TAG}",
               "sort_order": 99, "is_active": True, "is_hidden": False}
    r = session.post(f"{API}/admin/story-options", headers=H(admin_token), json=payload)
    assert r.status_code == 200
    oid = r.json()["id"]
    pub = session.get(f"{API}/public/story-options").json()
    assert any(o["id"] == oid for o in pub["type"])
    payload["is_hidden"] = True
    r = session.patch(f"{API}/admin/story-options/{oid}", headers=H(admin_token), json=payload)
    assert r.status_code == 200
    pub = session.get(f"{API}/public/story-options").json()
    assert not any(o["id"] == oid for o in pub["type"])
    assert session.delete(f"{API}/admin/story-options/{oid}",
                          headers=H(admin_token)).status_code == 200


# ---------- Admin content / settings / categories / plans / users ----------
def test_admin_content_upsert(session, admin_token):
    key = f"test.block.{RUN_TAG}"
    r = session.put(f"{API}/admin/content", headers=H(admin_token),
                    json={"key": key, "value": "قيمة", "section": "test"})
    assert r.status_code == 200
    assert session.get(f"{API}/public/content").json().get(key) == "قيمة"
    session.delete(f"{API}/admin/content/{key}", headers=H(admin_token))


def test_admin_settings_char_limit(session, admin_token, parent_token, uploaded_child_file):
    r = session.put(f"{API}/admin/settings", headers=H(admin_token),
                    json={"key": "characters.max_count", "value": 5})
    assert r.status_code == 200
    data, _, _ = _build_data(session, uploaded_child_file["url"], 4)
    r = session.post(f"{API}/orders", headers=H(parent_token), json={"data": data})
    assert r.status_code == 200, f"expected ok with 4 chars: {r.status_code} {r.text}"
    session.put(f"{API}/admin/settings", headers=H(admin_token),
                json={"key": "characters.max_count", "value": 3})


def test_admin_categories_crud(session, admin_token):
    slug = f"test-cat-{RUN_TAG}"
    r = session.post(f"{API}/admin/categories", headers=H(admin_token),
                     json={"name_ar": "تج", "slug": slug, "description": "d", "sort_order": 99})
    assert r.status_code == 200
    cid = r.json()["id"]
    r = session.post(f"{API}/admin/subcategories", headers=H(admin_token),
                     json={"category_id": cid, "name_ar": "فرعي", "sort_order": 1})
    assert r.status_code == 200
    sid = r.json()["id"]
    r = session.patch(f"{API}/admin/subcategories/{sid}", headers=H(admin_token),
                      json={"category_id": cid, "name_ar": "محدث", "sort_order": 2})
    assert r.status_code == 200
    assert session.delete(f"{API}/admin/categories/{cid}",
                          headers=H(admin_token)).status_code == 200


def test_admin_plans_crud(session, admin_token):
    r = session.post(f"{API}/admin/plans", headers=H(admin_token),
                     json={"name_ar": f"خطة {RUN_TAG}", "price": 1, "story_limit": 1,
                           "features": ["x"], "sort_order": 99})
    assert r.status_code == 200
    pid = r.json()["id"]
    r = session.patch(f"{API}/admin/plans/{pid}", headers=H(admin_token),
                      json={"name_ar": "v2", "price": 2, "story_limit": 2,
                            "features": ["y"], "sort_order": 100})
    assert r.status_code == 200
    assert session.delete(f"{API}/admin/plans/{pid}",
                          headers=H(admin_token)).status_code == 200


def test_admin_users_list(session, admin_token):
    users = session.get(f"{API}/admin/users", headers=H(admin_token)).json()
    assert any(u["email"] == ADMIN_EMAIL for u in users)
    for u in users:
        assert "hashed_password" not in u and "_id" not in u


def test_non_admin_forbidden(session, parent_token):
    for path in ["/admin/stats", "/admin/users", "/admin/orders", "/admin/story-options",
                 "/admin/settings", "/admin/plans", "/admin/content", "/admin/prompts",
                 "/admin/subcategories"]:
        r = session.get(f"{API}{path}", headers=H(parent_token))
        assert r.status_code == 403, f"{path} -> {r.status_code}"


def test_no_mongo_id_leakage(session, admin_token, parent_token, created_order):
    for ep in ["/public/categories", "/public/story-options", "/public/content",
               "/public/plans", "/public/settings", "/orders",
               f"/orders/{created_order['id']}", "/drafts/current"]:
        r = session.get(f"{API}{ep}", headers=H(parent_token))
        assert r.status_code == 200 and '"_id"' not in r.text, f"{ep}"
    for ep in ["/admin/stats", "/admin/users", "/admin/orders",
               f"/admin/orders/{created_order['id']}",
               "/admin/story-options", "/admin/content", "/admin/prompts",
               "/admin/plans", "/admin/settings", "/admin/subcategories"]:
        r = session.get(f"{API}{ep}", headers=H(admin_token))
        assert r.status_code == 200 and '"_id"' not in r.text, f"{ep}"
