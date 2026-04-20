"""Comprehensive backend tests for Gheras AI Storytelling platform."""
import os
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://girasai-create.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@gheras.com"
ADMIN_PASSWORD = "Admin@1234"


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(http):
    r = http.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data["user"]["role"] == "admin"
    return data["access_token"]


@pytest.fixture(scope="session")
def user_creds():
    suffix = uuid.uuid4().hex[:8]
    return {
        "email": f"TEST_user_{suffix}@gherastest.com",
        "password": "Passw0rd!",
        "full_name": "TEST User",
    }


@pytest.fixture(scope="session")
def user_token(http, user_creds):
    r = http.post(f"{API}/auth/register", json=user_creds)
    assert r.status_code == 200, f"Register failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _admin_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _user_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- Health ----------
class TestHealth:
    def test_root_health(self, http):
        r = http.get(f"{API}/")
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "healthy"
        assert body.get("ok") is True


# ---------- Public endpoints / seed verification ----------
class TestPublicSeed:
    def test_categories_seeded(self, http):
        r = http.get(f"{API}/public/categories")
        assert r.status_code == 200
        cats = r.json()
        assert isinstance(cats, list)
        assert len(cats) == 8, f"expected 8 categories, got {len(cats)}"
        for c in cats:
            assert "_id" not in c
            assert "id" in c and "name_ar" in c and "slug" in c
            assert "subcategories" in c and isinstance(c["subcategories"], list)
        # spot-check a known seeded category having subcategories
        emotions = next((c for c in cats if c["slug"] == "emotions"), None)
        assert emotions and len(emotions["subcategories"]) >= 1

    def test_styles_seeded(self, http):
        r = http.get(f"{API}/public/styles")
        assert r.status_code == 200
        styles = r.json()
        assert len(styles) == 5
        assert all("_id" not in s for s in styles)

    def test_content_has_hero_title(self, http):
        r = http.get(f"{API}/public/content")
        assert r.status_code == 200
        content = r.json()
        assert isinstance(content, dict)
        assert "hero.title" in content
        assert isinstance(content["hero.title"], str) and len(content["hero.title"]) > 0

    def test_plans_seeded(self, http):
        r = http.get(f"{API}/public/plans")
        assert r.status_code == 200
        plans = r.json()
        assert len(plans) == 3
        assert all("_id" not in p for p in plans)

    def test_settings_returns_dict(self, http):
        r = http.get(f"{API}/public/settings")
        assert r.status_code == 200
        s = r.json()
        assert isinstance(s, dict)
        assert "site.name" in s


# ---------- Auth ----------
class TestAuth:
    def test_register_new_user(self, http, user_token, user_creds):
        # token created via fixture; verify by hitting /me
        r = http.get(f"{API}/auth/me", headers=_user_headers(user_token))
        assert r.status_code == 200
        u = r.json()
        assert u["email"] == user_creds["email"].lower()
        assert u["role"] == "user"
        assert "_id" not in u

    def test_register_duplicate_email(self, http, user_creds):
        r = http.post(f"{API}/auth/register", json=user_creds)
        assert r.status_code == 400

    def test_login_admin(self, http, admin_token):
        # admin_token fixture already verifies login; now verify /me reports admin
        r = http.get(f"{API}/auth/me", headers=_admin_headers(admin_token))
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_login_wrong_password(self, http):
        r = http.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "WrongPass!"})
        assert r.status_code == 401

    def test_me_without_token(self, http):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code in (401, 403)

    def test_change_password_wrong_current(self, http, user_token):
        r = http.post(
            f"{API}/auth/change-password",
            headers=_user_headers(user_token),
            json={"current_password": "WRONG", "new_password": "NewPassw0rd!"},
        )
        assert r.status_code == 400

    def test_change_password_success_then_revert(self, http, user_token, user_creds):
        # change to new password
        r = http.post(
            f"{API}/auth/change-password",
            headers=_user_headers(user_token),
            json={"current_password": user_creds["password"], "new_password": "NewPassw0rd!"},
        )
        assert r.status_code == 200
        # login with new password
        r2 = http.post(f"{API}/auth/login", json={"email": user_creds["email"], "password": "NewPassw0rd!"})
        assert r2.status_code == 200
        new_tok = r2.json()["access_token"]
        # revert back so subsequent fixtures still work
        r3 = http.post(
            f"{API}/auth/change-password",
            headers=_user_headers(new_tok),
            json={"current_password": "NewPassw0rd!", "new_password": user_creds["password"]},
        )
        assert r3.status_code == 200


# ---------- Orders (user) ----------
@pytest.fixture(scope="session")
def seed_refs(http):
    cats = http.get(f"{API}/public/categories").json()
    styles = http.get(f"{API}/public/styles").json()
    cat = next(c for c in cats if c["subcategories"])
    return {
        "category_id": cat["id"],
        "subcategory_id": cat["subcategories"][0]["id"],
        "style_id": styles[0]["id"],
    }


@pytest.fixture(scope="session")
def created_order(http, user_token, seed_refs):
    payload = {
        "category_id": seed_refs["category_id"],
        "subcategory_id": seed_refs["subcategory_id"],
        "child": {
            "name": "سلمى",
            "age": 6,
            "gender": "female",
            "personality": "هادئة وفضولية",
            "interests": "الرسم والقراءة",
        },
        "style_id": seed_refs["style_id"],
        "notes": "TEST notes",
    }
    r = http.post(f"{API}/orders", headers=_user_headers(user_token), json=payload)
    assert r.status_code == 200, f"create order failed: {r.status_code} {r.text}"
    return r.json()


class TestOrders:
    def test_create_order_has_ai_prompt_with_child_name(self, created_order):
        assert "_id" not in created_order
        assert created_order["status"] == "pending"
        assert created_order["child_snapshot"]["name"] == "سلمى"
        assert created_order["child_snapshot"]["age"] == 6
        assert created_order["child_snapshot"]["personality"] == "هادئة وفضولية"
        snap = created_order.get("ai_prompt_snapshot") or ""
        assert "سلمى" in snap, f"ai_prompt_snapshot missing child name: {snap!r}"

    def test_list_my_orders_enriched(self, http, user_token, created_order):
        r = http.get(f"{API}/orders", headers=_user_headers(user_token))
        assert r.status_code == 200
        orders = r.json()
        assert any(o["id"] == created_order["id"] for o in orders)
        first = orders[0]
        assert "category_name" in first
        assert "style_name" in first
        assert "status_ar" in first
        assert all("_id" not in o for o in orders)

    def test_get_order_detail_owner(self, http, user_token, created_order):
        r = http.get(f"{API}/orders/{created_order['id']}", headers=_user_headers(user_token))
        assert r.status_code == 200
        assert r.json()["id"] == created_order["id"]

    def test_get_order_detail_other_user_404(self, http, created_order):
        suffix = uuid.uuid4().hex[:8]
        other = {"email": f"TEST_other_{suffix}@gherastest.com", "password": "Passw0rd!", "full_name": "Other"}
        reg = http.post(f"{API}/auth/register", json=other)
        assert reg.status_code == 200
        tok = reg.json()["access_token"]
        r = http.get(f"{API}/orders/{created_order['id']}", headers=_user_headers(tok))
        assert r.status_code == 404


# ---------- Admin guard ----------
class TestAdminGuard:
    def test_user_forbidden_on_admin(self, http, user_token):
        r = http.get(f"{API}/admin/stats", headers=_user_headers(user_token))
        assert r.status_code == 403

    def test_admin_stats_ok(self, http, admin_token):
        r = http.get(f"{API}/admin/stats", headers=_admin_headers(admin_token))
        assert r.status_code == 200
        d = r.json()
        for k in ["users_count", "orders_count", "pending_count", "in_review_count",
                  "completed_count", "categories_count", "recent_orders"]:
            assert k in d
        assert isinstance(d["recent_orders"], list)
        for o in d["recent_orders"]:
            assert "_id" not in o


# ---------- Admin orders + status workflow ----------
class TestAdminOrders:
    def test_list_orders_enriched(self, http, admin_token, created_order):
        r = http.get(f"{API}/admin/orders", headers=_admin_headers(admin_token))
        assert r.status_code == 200
        orders = r.json()
        target = next((o for o in orders if o["id"] == created_order["id"]), None)
        assert target is not None
        assert "user_email" in target and target["user_email"]
        assert "category_name" in target
        assert "status_ar" in target
        assert all("_id" not in o for o in orders)

    @pytest.mark.parametrize("status", ["pending", "in_review", "ready_for_ai", "generating", "completed"])
    def test_status_workflow(self, http, admin_token, created_order, status):
        r = http.patch(
            f"{API}/admin/orders/{created_order['id']}/status",
            headers=_admin_headers(admin_token),
            json={"status": status, "admin_note": f"moved to {status}"},
        )
        assert r.status_code == 200
        # Verify persisted
        d = http.get(f"{API}/admin/orders/{created_order['id']}", headers=_admin_headers(admin_token))
        assert d.status_code == 200
        assert d.json()["status"] == status


# ---------- Admin CRUD ----------
class TestAdminCategoriesCRUD:
    def test_full_cycle_and_slug_uniqueness(self, http, admin_token):
        slug = f"test-cat-{uuid.uuid4().hex[:6]}"
        payload = {"name_ar": "تصنيف اختبار", "slug": slug, "description": "TEST",
                   "icon": "sun", "color": "#abcdef", "sort_order": 99, "is_active": True}
        r = http.post(f"{API}/admin/categories", headers=_admin_headers(admin_token), json=payload)
        assert r.status_code == 200
        cat = r.json()
        assert "_id" not in cat
        cid = cat["id"]
        # duplicate slug should 400
        dup = http.post(f"{API}/admin/categories", headers=_admin_headers(admin_token), json=payload)
        assert dup.status_code == 400
        # patch
        payload2 = {**payload, "name_ar": "محدّث"}
        p = http.patch(f"{API}/admin/categories/{cid}", headers=_admin_headers(admin_token), json=payload2)
        assert p.status_code == 200
        # verify via public
        cats = http.get(f"{API}/public/categories").json()
        updated = next((c for c in cats if c["id"] == cid), None)
        assert updated and updated["name_ar"] == "محدّث"
        # delete
        d = http.delete(f"{API}/admin/categories/{cid}", headers=_admin_headers(admin_token))
        assert d.status_code == 200


class TestAdminSubcategoriesCRUD:
    def test_full_cycle(self, http, admin_token, seed_refs):
        payload = {"category_id": seed_refs["category_id"], "name_ar": "TEST sub",
                   "description": None, "sort_order": 50, "is_active": True}
        r = http.post(f"{API}/admin/subcategories", headers=_admin_headers(admin_token), json=payload)
        assert r.status_code == 200
        sid = r.json()["id"]
        p = http.patch(f"{API}/admin/subcategories/{sid}", headers=_admin_headers(admin_token),
                       json={**payload, "name_ar": "TEST sub 2"})
        assert p.status_code == 200
        d = http.delete(f"{API}/admin/subcategories/{sid}", headers=_admin_headers(admin_token))
        assert d.status_code == 200


class TestAdminStylesCRUD:
    def test_full_cycle(self, http, admin_token):
        payload = {"name_ar": "TEST style", "description": "x", "image_url": None,
                   "sort_order": 99, "is_active": True}
        r = http.post(f"{API}/admin/styles", headers=_admin_headers(admin_token), json=payload)
        assert r.status_code == 200
        sid = r.json()["id"]
        p = http.patch(f"{API}/admin/styles/{sid}", headers=_admin_headers(admin_token),
                       json={**payload, "name_ar": "TEST style 2"})
        assert p.status_code == 200
        d = http.delete(f"{API}/admin/styles/{sid}", headers=_admin_headers(admin_token))
        assert d.status_code == 200


class TestAdminContent:
    def test_upsert_reflects_in_public(self, http, admin_token):
        key = f"test.block.{uuid.uuid4().hex[:6]}"
        val = "hello world"
        r = http.put(f"{API}/admin/content", headers=_admin_headers(admin_token),
                     json={"key": key, "value": val, "section": "test"})
        assert r.status_code == 200
        public = http.get(f"{API}/public/content").json()
        assert public.get(key) == val
        # cleanup
        d = http.delete(f"{API}/admin/content/{key}", headers=_admin_headers(admin_token))
        assert d.status_code == 200


class TestAdminPromptsCRUD:
    def test_full_cycle_with_uniqueness(self, http, admin_token):
        key = f"test.prompt.{uuid.uuid4().hex[:6]}"
        payload = {"key": key, "title_ar": "TEST", "description": None,
                   "template": "hello {x}", "variables": ["x"], "is_active": True}
        r = http.post(f"{API}/admin/prompts", headers=_admin_headers(admin_token), json=payload)
        assert r.status_code == 200
        pid = r.json()["id"]
        dup = http.post(f"{API}/admin/prompts", headers=_admin_headers(admin_token), json=payload)
        assert dup.status_code == 400
        p = http.patch(f"{API}/admin/prompts/{pid}", headers=_admin_headers(admin_token),
                       json={**payload, "title_ar": "TEST 2"})
        assert p.status_code == 200
        d = http.delete(f"{API}/admin/prompts/{pid}", headers=_admin_headers(admin_token))
        assert d.status_code == 200


class TestAdminPlansCRUD:
    def test_full_cycle(self, http, admin_token):
        payload = {"name_ar": "TEST plan", "price": 1.0, "currency": "SAR",
                   "story_limit": 1, "features": ["a"], "is_active": True, "sort_order": 99}
        r = http.post(f"{API}/admin/plans", headers=_admin_headers(admin_token), json=payload)
        assert r.status_code == 200
        pid = r.json()["id"]
        p = http.patch(f"{API}/admin/plans/{pid}", headers=_admin_headers(admin_token),
                       json={**payload, "price": 2.0})
        assert p.status_code == 200
        d = http.delete(f"{API}/admin/plans/{pid}", headers=_admin_headers(admin_token))
        assert d.status_code == 200


class TestAdminSettings:
    def test_upsert_reflects_in_public(self, http, admin_token):
        key = f"test.setting.{uuid.uuid4().hex[:6]}"
        r = http.put(f"{API}/admin/settings", headers=_admin_headers(admin_token),
                     json={"key": key, "value": 42})
        assert r.status_code == 200
        s = http.get(f"{API}/public/settings").json()
        assert s.get(key) == 42


# ---------- Admin users ----------
class TestAdminUsers:
    def test_toggle_is_active_and_role(self, http, admin_token):
        suffix = uuid.uuid4().hex[:8]
        creds = {"email": f"TEST_admgmt_{suffix}@gherastest.com", "password": "Passw0rd!", "full_name": "TEST AdmGmt"}
        reg = http.post(f"{API}/auth/register", json=creds)
        assert reg.status_code == 200
        uid = reg.json()["user"]["id"]
        # toggle is_active = False
        r = http.patch(f"{API}/admin/users/{uid}", headers=_admin_headers(admin_token),
                       json={"is_active": False, "role": "admin"})
        assert r.status_code == 200
        # verify by listing admin/users
        users = http.get(f"{API}/admin/users", headers=_admin_headers(admin_token)).json()
        assert all("_id" not in u for u in users)
        target = next((u for u in users if u["id"] == uid), None)
        assert target is not None
        assert target["is_active"] is False
        assert target["role"] == "admin"
        # login should now be 403 (inactive)
        r2 = http.post(f"{API}/auth/login", json={"email": creds["email"], "password": creds["password"]})
        assert r2.status_code == 403
