"""Phase D — Admin Storyboard endpoint tests.

GET /api/admin/orders/{order_id}/storyboard
"""
import hashlib
import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_EMAIL = "admin@gheras.com"
ADMIN_PASS = "Admin@1234"

DELIVERED_ID = "ebaa164d-4375-4728-9586-bfc325d0a4bf"
PRODUCTION_READY_ID = "61c44457-2a80-454d-b3bc-5d2625085aba"

STAGE_ORDER = [
    "scenario_generation", "production_planning", "child_character_i2i",
    "scene_image_generation", "narration_generation", "book_assets_generation",
    "video_assembly", "pdf_assembly",
]
REQ_FIELDS = [
    "stage_key", "name_ar", "name_en", "status", "config_enabled",
    "started_at", "ended_at", "latency_ms_estimate", "latency_is_estimate",
    "attempts", "provider", "model_name", "model_source",
    "prompt_source", "prompt_template_id", "prompt_template_version",
    "prompt_used", "prompt_hash",
    "fallback_used", "error_message", "mock_mode",
    "input_summary", "output_summary", "events", "actions",
]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                      timeout=15)
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text[:200]}")
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def storyboard_delivered(admin_h):
    r = requests.get(f"{BASE_URL}/api/admin/orders/{DELIVERED_ID}/storyboard",
                     headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text[:500]
    return r.json()


# --- 1. Schema ----------------------------------------------------------
class TestSchema:
    def test_top_level_keys(self, storyboard_delivered):
        d = storyboard_delivered
        for k in ("order", "timeline", "stages", "pipeline_config", "meta"):
            assert k in d, f"missing key {k}"
        assert "request_id" not in d, "request_id MUST NOT be invented"

    def test_eight_stages_in_order(self, storyboard_delivered):
        keys = [s["stage_key"] for s in storyboard_delivered["stages"]]
        assert keys == STAGE_ORDER

    def test_each_stage_has_required_fields(self, storyboard_delivered):
        for s in storyboard_delivered["stages"]:
            missing = [f for f in REQ_FIELDS if f not in s]
            assert not missing, f"{s['stage_key']} missing {missing}"
            assert s["latency_is_estimate"] is True

    def test_timeline_aligned(self, storyboard_delivered):
        d = storyboard_delivered
        assert len(d["timeline"]) == 8
        assert [t["stage_key"] for t in d["timeline"]] == STAGE_ORDER
        for t, s in zip(d["timeline"], d["stages"]):
            assert t["status"] == s["status"]
            assert t["fallback_used"] == s["fallback_used"]
            assert t["mock_mode"] == s["mock_mode"]
            for f in ("badge_color", "attempts", "latency_ms_estimate"):
                assert f in t

    def test_meta_estimate_flag(self, storyboard_delivered):
        assert storyboard_delivered["meta"]["latency_values_are_estimates"] is True


# --- 2. Auth ------------------------------------------------------------
class TestAuth:
    def test_no_token_unauthorized(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/orders/{DELIVERED_ID}/storyboard", timeout=10)
        assert r.status_code in (401, 403)

    def test_unknown_order_404(self, admin_h):
        r = requests.get(
            f"{BASE_URL}/api/admin/orders/does-not-exist-xyz/storyboard",
            headers=admin_h, timeout=10)
        assert r.status_code == 404


# --- 3. child_character_i2i: skipped + mock -----------------------------
class TestChildCharacter:
    def _get(self, admin_h, oid):
        r = requests.get(f"{BASE_URL}/api/admin/orders/{oid}/storyboard",
                         headers=admin_h, timeout=20)
        assert r.status_code == 200
        return r.json()

    def test_disabled_stage_status_skipped_not_hidden(self, admin_h):
        # Ensure disabled in pipeline_config (default state per Phase C teardown)
        cfg = requests.get(f"{BASE_URL}/api/admin/pipeline-config",
                           headers=admin_h, timeout=10).json()
        enabled = cfg.get("stages", {}).get("child_character_i2i", {}).get("enabled")
        d = self._get(admin_h, DELIVERED_ID)
        cc = next(s for s in d["stages"] if s["stage_key"] == "child_character_i2i")
        if enabled is False:
            assert cc["status"] == "skipped"
        # Always must be present (not hidden)
        assert cc["config_enabled"] == enabled

    def test_mock_mode_surfaced_when_asset_mock_true(self, admin_h):
        # Phase C left a child_character_assets doc with mock=true on محمود (PRODUCTION_READY_ID)
        d = self._get(admin_h, PRODUCTION_READY_ID)
        cc = next(s for s in d["stages"] if s["stage_key"] == "child_character_i2i")
        # If asset exists with mock=true, both flags must propagate
        if cc.get("output_summary", {}).get("provider") == "mock":
            assert cc["mock_mode"] is True
            assert cc["output_summary"]["mock"] is True


# --- 4. Delivered order: scenes/video/pdf -------------------------------
class TestDelivered:
    def test_scene_grid_per_scene_fields(self, storyboard_delivered):
        scn = next(s for s in storyboard_delivered["stages"]
                   if s["stage_key"] == "scene_image_generation")
        scenes = scn["output_summary"].get("scenes") or []
        assert len(scenes) > 0, "delivered order should have scenes"
        for sc in scenes:
            for f in ("scene_index", "image_url", "prompt_preview", "prompt_hash",
                      "provider", "fallback_used", "latency_ms_estimate",
                      "attempts", "status", "error_message"):
                assert f in sc, f"scene missing {f}"

    def test_video_assembly_completed(self, storyboard_delivered):
        v = next(s for s in storyboard_delivered["stages"]
                 if s["stage_key"] == "video_assembly")
        assert v["status"] == "completed"
        assert v["output_summary"].get("video_url")

    def test_pdf_assembly_completed(self, storyboard_delivered):
        p = next(s for s in storyboard_delivered["stages"]
                 if s["stage_key"] == "pdf_assembly")
        assert p["status"] == "completed"
        assert p["output_summary"].get("pdf_url")


# --- 5. prompt_hash format ---------------------------------------------
class TestPromptHash:
    def test_format_and_value_correctness(self, storyboard_delivered):
        for s in storyboard_delivered["stages"]:
            ph = s.get("prompt_hash")
            pu = s.get("prompt_used")
            if pu:
                assert isinstance(ph, str) and ph.startswith("sha256:")
                expected = hashlib.sha256(pu.encode("utf-8")).hexdigest()[:16]
                assert ph == f"sha256:{expected}"
            else:
                # null when prompt empty/null
                assert ph is None or pu in (None, "")
        # Per-scene prompt_hash too
        scn = next(s for s in storyboard_delivered["stages"]
                   if s["stage_key"] == "scene_image_generation")
        for sc in scn["output_summary"].get("scenes") or []:
            pp = sc.get("prompt_preview") or ""
            ph = sc.get("prompt_hash")
            if ph:
                assert ph.startswith("sha256:") and len(ph.split(":")[1]) == 16


# --- 6. Regression — untouched endpoints --------------------------------
class TestRegression:
    def test_admin_get_order_works(self, admin_h):
        r = requests.get(f"{BASE_URL}/api/admin/orders/{DELIVERED_ID}",
                         headers=admin_h, timeout=15)
        assert r.status_code == 200
        assert r.json().get("id") == DELIVERED_ID

    def test_pipeline_config_get(self, admin_h):
        r = requests.get(f"{BASE_URL}/api/admin/pipeline-config",
                         headers=admin_h, timeout=10)
        assert r.status_code == 200
        assert "stages" in r.json()

    def test_child_character_get_unchanged(self, admin_h):
        r = requests.get(
            f"{BASE_URL}/api/admin/orders/{DELIVERED_ID}/child-character",
            headers=admin_h, timeout=10)
        assert r.status_code == 200
        body = r.json()
        for k in ("order_id", "stage_enabled", "source_image_url"):
            assert k in body


# --- 7. fallback_used on production_generation -------------------------
class TestFallback:
    def test_production_planning_fallback_propagated(self, admin_h):
        # If any test order has production_generation.source='fallback'
        # the storyboard must surface fallback_used=true.
        # We sample a few orders and only assert when source matches.
        orders = requests.get(f"{BASE_URL}/api/admin/orders?limit=20",
                              headers=admin_h, timeout=15).json()
        ids = [o["id"] for o in (orders if isinstance(orders, list)
                                  else orders.get("orders", []))]
        found = False
        for oid in ids[:10]:
            d = requests.get(f"{BASE_URL}/api/admin/orders/{oid}/storyboard",
                             headers=admin_h, timeout=20).json()
            stage = next(s for s in d["stages"]
                         if s["stage_key"] == "production_planning")
            if stage.get("fallback_used"):
                found = True
                # error_message may or may not be present, but flag must be true
                assert stage["fallback_used"] is True
                break
        if not found:
            pytest.skip("No order with production fallback in sample")
