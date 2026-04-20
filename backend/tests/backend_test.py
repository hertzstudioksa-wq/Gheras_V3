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
    # Phase 3: POST /orders returns immediately with status=scenarios_generating
    assert created_order["status"] in ("scenarios_generating", "scenarios_ready"), created_order["status"]
    assert created_order["prompt_edited"] is False
    # status_history must include pending->scenarios_generating
    sh = created_order.get("status_history") or []
    assert any(h.get("from") is None and h.get("to") == "pending" for h in sh)
    assert any(h.get("from") == "pending" and h.get("to") == "scenarios_generating" for h in sh)


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


# ============================================================
# ---------- Phase 3: Scenario generation & selection ----------
# ============================================================
import time

VALID_ANGLES = {"emotional", "educational", "adventure"}


def _wait_scenarios_ready(session, parent_token, order_id, timeout=40):
    """Poll until status becomes scenarios_ready (or fails) and 3 scenarios appear."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = session.get(f"{API}/orders/{order_id}/scenarios", headers=H(parent_token))
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        last = r.json()
        if last.get("status") == "scenarios_ready" and len(last.get("scenarios") or []) == 3:
            return last
        if last.get("status") == "failed":
            return last
        time.sleep(1.0)
    raise AssertionError(f"scenarios not ready in {timeout}s: {last}")


@pytest.fixture(scope="module")
def scen_order(session, parent_token, uploaded_child_file):
    """Fresh order specifically for scenario tests."""
    data, _, _ = _build_data(session, uploaded_child_file["url"], 2)
    r = session.post(f"{API}/orders", headers=H(parent_token), json={"data": data})
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    o = r.json()
    # immediate status assertions
    assert o["status"] == "scenarios_generating", o["status"]
    assert o.get("selected_scenario_id") is None
    assert o.get("scenarios_generation") in (None, {}) or isinstance(o.get("scenarios_generation"), dict)
    return o


def test_p3_create_returns_scenarios_generating(scen_order):
    sh = scen_order.get("status_history") or []
    assert any(h.get("to") == "pending" and h.get("by") == "user" for h in sh)
    assert any(h.get("from") == "pending" and h.get("to") == "scenarios_generating" and h.get("by") == "system" for h in sh)


def test_p3_polling_scenarios_ready(session, parent_token, scen_order):
    res = _wait_scenarios_ready(session, parent_token, scen_order["id"])
    assert res["status"] == "scenarios_ready"
    items = res["scenarios"]
    assert len(items) == 3
    indices = sorted(s["scenario_index"] for s in items)
    assert indices == [1, 2, 3]
    for s in items:
        assert s["id"] and s["order_id"] == scen_order["id"]
        assert s["title"] and s["short_summary"]
        assert s["emotional_angle"] in VALID_ANGLES, s["emotional_angle"]
        assert s["learning_goal"] and s["visual_style_hint"]
        assert isinstance(s["estimated_scene_count"], int)
        assert 4 <= s["estimated_scene_count"] <= 8
        assert s["is_selected"] is False
        assert s["created_at"]


def test_p3_generation_metadata(session, parent_token, scen_order):
    _wait_scenarios_ready(session, parent_token, scen_order["id"])
    o = session.get(f"{API}/orders/{scen_order['id']}", headers=H(parent_token)).json()
    gen = o.get("scenarios_generation")
    assert gen, "scenarios_generation missing"
    assert gen["source"] in ("ai", "fallback"), gen["source"]
    assert "completed_at" in gen
    # If ai, error should be None; if fallback, error should be a string
    if gen["source"] == "ai":
        assert gen.get("error") in (None, "")
    print(f"PHASE3 scenario source = {gen['source']}")


def test_p3_select_scenario_user(session, parent_token, scen_order):
    res = session.get(f"{API}/orders/{scen_order['id']}/scenarios", headers=H(parent_token)).json()
    sid = res["scenarios"][0]["id"]
    r = session.post(f"{API}/orders/{scen_order['id']}/scenarios/{sid}/select", headers=H(parent_token))
    assert r.status_code == 200, r.text
    res2 = session.get(f"{API}/orders/{scen_order['id']}/scenarios", headers=H(parent_token)).json()
    sels = [s for s in res2["scenarios"] if s["is_selected"]]
    assert len(sels) == 1 and sels[0]["id"] == sid
    o = session.get(f"{API}/orders/{scen_order['id']}", headers=H(parent_token)).json()
    assert o["selected_scenario_id"] == sid
    assert o["selected_scenario_snapshot"]["id"] == sid
    assert o["status"] == "ready_for_ai"
    sh = o["status_history"]
    # last two entries should be scenario_selected then ready_for_ai
    last_to = [h["to"] for h in sh[-2:]]
    assert last_to == ["scenario_selected", "ready_for_ai"], last_to


def test_p3_select_other_user_404(session, parent2_token, scen_order):
    res = requests.get(f"{API}/orders/{scen_order['id']}/scenarios", headers=H(parent2_token))
    assert res.status_code == 404
    # try to select with parent2 — must 404
    # use any random sid we know exists from selected snapshot — fetch via admin path? we'll fabricate
    fake = "00000000-0000-0000-0000-000000000000"
    r = requests.post(f"{API}/orders/{scen_order['id']}/scenarios/{fake}/select", headers=H(parent2_token))
    assert r.status_code == 404


def test_p3_reselection_swaps(session, parent_token, scen_order):
    res = session.get(f"{API}/orders/{scen_order['id']}/scenarios", headers=H(parent_token)).json()
    other = next(s for s in res["scenarios"] if not s["is_selected"])
    r = session.post(f"{API}/orders/{scen_order['id']}/scenarios/{other['id']}/select", headers=H(parent_token))
    assert r.status_code == 200
    res2 = session.get(f"{API}/orders/{scen_order['id']}/scenarios", headers=H(parent_token)).json()
    sels = [s for s in res2["scenarios"] if s["is_selected"]]
    assert len(sels) == 1 and sels[0]["id"] == other["id"]


def test_p3_select_blocked_when_generating(session, admin_token, parent_token, scen_order):
    oid = scen_order["id"]
    # admin patches order to generating
    r = session.patch(f"{API}/admin/orders/{oid}/status", headers=H(admin_token), json={"status": "generating"})
    assert r.status_code == 200
    res = session.get(f"{API}/orders/{oid}/scenarios", headers=H(parent_token)).json()
    sid = res["scenarios"][0]["id"]
    r2 = session.post(f"{API}/orders/{oid}/scenarios/{sid}/select", headers=H(parent_token))
    assert r2.status_code == 400, r2.status_code
    # restore to ready_for_ai for downstream tests
    session.patch(f"{API}/admin/orders/{oid}/status", headers=H(admin_token), json={"status": "ready_for_ai"})


def test_p3_regenerate_user(session, parent_token, scen_order):
    oid = scen_order["id"]
    before = session.get(f"{API}/orders/{oid}/scenarios", headers=H(parent_token)).json()
    before_ids = sorted(s["id"] for s in before["scenarios"])
    r = session.post(f"{API}/orders/{oid}/scenarios/regenerate", headers=H(parent_token))
    assert r.status_code == 200, r.text
    # status flipped
    immediate = session.get(f"{API}/orders/{oid}/scenarios", headers=H(parent_token)).json()
    assert immediate["status"] in ("scenarios_generating", "scenarios_ready")
    res = _wait_scenarios_ready(session, parent_token, oid)
    after_ids = sorted(s["id"] for s in res["scenarios"])
    assert after_ids != before_ids, "ids should have changed after regenerate"
    o = session.get(f"{API}/orders/{oid}", headers=H(parent_token)).json()
    assert o.get("selected_scenario_id") is None


def test_p3_regenerate_blocked_when_generating(session, admin_token, parent_token, scen_order):
    oid = scen_order["id"]
    session.patch(f"{API}/admin/orders/{oid}/status", headers=H(admin_token), json={"status": "generating"})
    r = session.post(f"{API}/orders/{oid}/scenarios/regenerate", headers=H(parent_token))
    assert r.status_code == 400, r.status_code
    # restore
    session.patch(f"{API}/admin/orders/{oid}/status", headers=H(admin_token), json={"status": "scenarios_ready"})


def test_p3_status_history_shape(session, parent_token, scen_order):
    o = session.get(f"{API}/orders/{scen_order['id']}", headers=H(parent_token)).json()
    sh = o["status_history"]
    assert len(sh) > 1
    for h in sh:
        for k in ["from", "to", "at", "by"]:
            assert k in h, f"missing key {k} in {h}"
        assert h["by"] in ("user", "system", "admin"), h["by"]


def test_p3_admin_scenarios(session, admin_token, scen_order):
    r = session.get(f"{API}/admin/orders/{scen_order['id']}/scenarios", headers=H(admin_token))
    assert r.status_code == 200
    j = r.json()
    assert "scenarios" in j and "generation" in j and "selected_scenario_id" in j
    assert '"_id"' not in r.text


def test_p3_admin_regenerate(session, admin_token, parent_token, scen_order):
    oid = scen_order["id"]
    r = session.post(f"{API}/admin/orders/{oid}/scenarios/regenerate", headers=H(admin_token))
    assert r.status_code == 200
    res = _wait_scenarios_ready(session, parent_token, oid)
    assert len(res["scenarios"]) == 3
    o = session.get(f"{API}/admin/orders/{oid}", headers=H(admin_token)).json()
    assert any(h.get("by") == "admin" and h.get("to") == "scenarios_generating" for h in o["status_history"])


def test_p3_admin_select_on_behalf(session, admin_token, parent_token, scen_order):
    oid = scen_order["id"]
    res = session.get(f"{API}/admin/orders/{oid}/scenarios", headers=H(admin_token)).json()
    sid = res["scenarios"][1]["id"]
    r = session.post(f"{API}/admin/orders/{oid}/scenarios/{sid}/select", headers=H(admin_token))
    assert r.status_code == 200
    o = session.get(f"{API}/admin/orders/{oid}", headers=H(admin_token)).json()
    assert o["selected_scenario_id"] == sid
    assert o["status"] == "ready_for_ai"
    sh = o["status_history"]
    last_two = sh[-2:]
    assert last_two[0]["to"] == "scenario_selected" and last_two[0]["by"] == "admin"
    assert last_two[1]["to"] == "ready_for_ai" and last_two[1]["by"] == "system"


def test_p3_admin_status_in_review_then_back(session, admin_token, scen_order):
    oid = scen_order["id"]
    r = session.patch(f"{API}/admin/orders/{oid}/status", headers=H(admin_token), json={"status": "in_review", "admin_note": "manual review"})
    assert r.status_code == 200
    o = session.get(f"{API}/admin/orders/{oid}", headers=H(admin_token)).json()
    assert o["status"] == "in_review"
    assert any(h.get("by") == "admin" and h.get("to") == "in_review" for h in o["status_history"])
    r2 = session.patch(f"{API}/admin/orders/{oid}/status", headers=H(admin_token), json={"status": "ready_for_ai"})
    assert r2.status_code == 200
    o2 = session.get(f"{API}/admin/orders/{oid}", headers=H(admin_token)).json()
    assert o2["status"] == "ready_for_ai"


def test_p3_admin_delete_scenarios(session, admin_token, parent_token, uploaded_child_file):
    """Use a fresh order to safely delete scenarios."""
    data, _, _ = _build_data(session, uploaded_child_file["url"], 1)
    r = session.post(f"{API}/orders", headers=H(parent_token), json={"data": data})
    oid = r.json()["id"]
    _wait_scenarios_ready(session, parent_token, oid)
    r2 = session.delete(f"{API}/admin/orders/{oid}/scenarios", headers=H(admin_token))
    assert r2.status_code == 200
    res = session.get(f"{API}/admin/orders/{oid}/scenarios", headers=H(admin_token)).json()
    assert res["scenarios"] == []
    assert res["selected_scenario_id"] is None


def test_p3_orders_list_includes_selected_scenario_id(session, parent_token, scen_order):
    items = session.get(f"{API}/orders", headers=H(parent_token)).json()
    it = next(i for i in items if i["id"] == scen_order["id"])
    assert "selected_scenario_id" in it


def test_p3_order_full_returns_snapshot(session, parent_token, scen_order):
    o = session.get(f"{API}/orders/{scen_order['id']}", headers=H(parent_token)).json()
    if o.get("selected_scenario_id"):
        assert o.get("selected_scenario_snapshot")
        assert o["selected_scenario_snapshot"]["id"] == o["selected_scenario_id"]


def test_p3_rbac_admin_scenario_endpoints(session, parent_token, scen_order):
    oid = scen_order["id"]
    for path, method in [
        (f"/admin/orders/{oid}/scenarios", "GET"),
        (f"/admin/orders/{oid}/scenarios/regenerate", "POST"),
        (f"/admin/orders/{oid}/scenarios", "DELETE"),
        (f"/admin/orders/{oid}/scenarios/x/select", "POST"),
    ]:
        r = session.request(method, f"{API}{path}", headers=H(parent_token))
        assert r.status_code == 403, f"{method} {path} -> {r.status_code}"


def test_p3_no_mongo_id_in_scenario_endpoints(session, parent_token, admin_token, scen_order):
    oid = scen_order["id"]
    for ep, tok in [
        (f"/orders/{oid}/scenarios", parent_token),
        (f"/admin/orders/{oid}/scenarios", admin_token),
    ]:
        r = session.get(f"{API}{ep}", headers=H(tok))
        assert r.status_code == 200
        assert '"_id"' not in r.text
