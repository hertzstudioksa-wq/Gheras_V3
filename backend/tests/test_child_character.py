"""Phase C — child_character_i2i (MOCK-only) backend tests.

Covers:
  * GET /api/admin/orders/{id}/child-character schema
  * POST /api/admin/orders/{id}/child-character/regenerate idempotent
  * stage disabled → no completed asset created
  * stage enabled  → asset doc created with provider=mock, model=dry-run
  * regression: GET /api/admin/orders/{id}/media still returns expected keys
  * regression: GET /api/admin/pipeline-config still includes child_character_i2i
  * default-restoration teardown: stage_enabled returned to False
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@gheras.com"
ADMIN_PASSWORD = "Admin@1234"


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"admin login failed {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"no token in response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def some_order_id(admin_headers):
    """Pick an existing order — prefer one in delivered/assets_ready state."""
    r = requests.get(f"{BASE_URL}/api/admin/orders", headers=admin_headers, timeout=30)
    assert r.status_code == 200, f"admin/orders failed: {r.status_code}"
    body = r.json()
    items = body.get("items") if isinstance(body, dict) else body
    assert items, "no orders to test against"
    # Prefer delivered/assets_ready first
    preferred = [o for o in items if o.get("status") in ("delivered", "assets_ready")]
    chosen = preferred[0] if preferred else items[0]
    return chosen["id"]


# ---------------- pipeline-config restore ----------------
@pytest.fixture(scope="module", autouse=True)
def restore_pipeline_default(admin_headers):
    """Always leave child_character_i2i.enabled=False after the module runs."""
    yield
    try:
        requests.patch(
            f"{BASE_URL}/api/admin/pipeline-config",
            headers=admin_headers,
            json={"stages": {"child_character_i2i": {"enabled": False}}},
            timeout=15,
        )
    except Exception:
        pass


# ---------------- helpers ----------------
def _set_stage_enabled(admin_headers, enabled: bool):
    r = requests.patch(
        f"{BASE_URL}/api/admin/pipeline-config",
        headers=admin_headers,
        json={"stages": {"child_character_i2i": {"enabled": enabled}}},
        timeout=15,
    )
    assert r.status_code == 200, f"PATCH pipeline-config failed: {r.status_code} {r.text}"
    return r.json()


# ---------------- regression: pipeline-config ----------------
class TestPipelineConfigRegression:
    def test_pipeline_config_lists_child_character_i2i(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/pipeline-config", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        cfg = r.json()
        stages = cfg.get("stages") or {}
        assert "child_character_i2i" in stages, f"stage missing. keys={list(stages.keys())}"
        # Default is False
        # NOTE: another concurrent test could flip this; we only check key presence here.

    def test_pipeline_toggle_persists(self, admin_headers):
        # toggle on
        _set_stage_enabled(admin_headers, True)
        r = requests.get(f"{BASE_URL}/api/admin/pipeline-config", headers=admin_headers, timeout=15)
        assert r.json()["stages"]["child_character_i2i"]["enabled"] is True
        # toggle off
        _set_stage_enabled(admin_headers, False)
        r = requests.get(f"{BASE_URL}/api/admin/pipeline-config", headers=admin_headers, timeout=15)
        assert r.json()["stages"]["child_character_i2i"]["enabled"] is False


# ---------------- new endpoints ----------------
class TestChildCharacterEndpoints:
    def test_get_child_character_schema(self, admin_headers, some_order_id):
        r = requests.get(
            f"{BASE_URL}/api/admin/orders/{some_order_id}/child-character",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("order_id", "stage_enabled", "stage_config",
                  "source_image_url", "child_name", "asset"):
            assert k in body, f"missing key {k} in {list(body.keys())}"
        assert body["order_id"] == some_order_id
        assert isinstance(body["stage_enabled"], bool)
        assert isinstance(body["stage_config"], dict)

    def test_get_child_character_404_for_unknown_order(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/orders/does-not-exist-id/child-character",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 404

    def test_regenerate_returns_ok_queued_when_disabled(self, admin_headers, some_order_id):
        _set_stage_enabled(admin_headers, False)
        # Capture asset prior
        prior = requests.get(
            f"{BASE_URL}/api/admin/orders/{some_order_id}/child-character",
            headers=admin_headers, timeout=15,
        ).json().get("asset")

        r = requests.post(
            f"{BASE_URL}/api/admin/orders/{some_order_id}/child-character/regenerate",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("queued") is True

        # Wait for background task to settle
        time.sleep(2.0)

        after = requests.get(
            f"{BASE_URL}/api/admin/orders/{some_order_id}/child-character",
            headers=admin_headers, timeout=15,
        ).json().get("asset")
        # Should not have been promoted to completed by this disabled run.
        # If asset was None before, it stays None. If existed, status must NOT
        # have been freshly set to 'completed' by THIS call (we can't perfectly
        # verify without timestamps, but at minimum: if prior was None, after
        # must still be None).
        if prior is None:
            assert after is None, f"expected asset to remain None when disabled, got {after}"

    def test_regenerate_creates_completed_asset_when_enabled(self, admin_headers, some_order_id):
        # Need a child image_url for the asset to actually be produced.
        info = requests.get(
            f"{BASE_URL}/api/admin/orders/{some_order_id}/child-character",
            headers=admin_headers, timeout=15,
        ).json()
        if not info.get("source_image_url"):
            pytest.skip(f"order {some_order_id} has no child image_url — cannot test enabled path")

        _set_stage_enabled(admin_headers, True)
        r = requests.post(
            f"{BASE_URL}/api/admin/orders/{some_order_id}/child-character/regenerate",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True

        # Background task — poll up to ~10s for completion
        asset = None
        for _ in range(20):
            time.sleep(0.5)
            asset = requests.get(
                f"{BASE_URL}/api/admin/orders/{some_order_id}/child-character",
                headers=admin_headers, timeout=15,
            ).json().get("asset")
            if asset and asset.get("status") == "completed":
                break

        assert asset is not None, "asset never created"
        assert asset.get("status") == "completed", f"status={asset.get('status')}"
        assert asset.get("provider") == "mock"
        assert asset.get("model_name") == "dry-run"
        assert asset.get("mock") is True
        assert asset.get("prompt_used"), "prompt_used must be non-empty"
        assert asset.get("generated_image_url") == info["source_image_url"], \
            "mock provider should mirror source image url"

    def test_regenerate_idempotent(self, admin_headers, some_order_id):
        # Two consecutive calls (stage flag wherever it is) must both return ok.
        for _ in range(2):
            r = requests.post(
                f"{BASE_URL}/api/admin/orders/{some_order_id}/child-character/regenerate",
                headers=admin_headers, timeout=15,
            )
            assert r.status_code == 200
            assert r.json().get("ok") is True
            assert r.json().get("queued") is True


# ---------------- regression: media endpoint ----------------
class TestMediaRegression:
    def test_media_endpoint_unaffected(self, admin_headers, some_order_id):
        r = requests.get(
            f"{BASE_URL}/api/admin/orders/{some_order_id}/media",
            headers=admin_headers, timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("order_id", "scene_images", "narration_assets",
                  "book_assets", "counts", "jobs"):
            assert k in body, f"missing key {k} in media response"
        assert isinstance(body["counts"], dict)
        assert isinstance(body["jobs"], list)
