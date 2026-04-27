"""Phase E — API-level smoke tests against the live preview backend.

Covers the 6 review items: storyboard scene_image_generation references fields,
backward compat for legacy delivered orders, lab dry-run with/without order_id,
pricing snapshot scene_reference_injection rule, and stages-list regression.

These tests are read-only / dry-run only — no media regeneration.
"""
import os
import json
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "https://girasai-create.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "admin@gheras.com"
ADMIN_PASSWORD = "Admin@1234"

ORDER_REF = "61c44457-2a80-454d-b3bc-5d2625085aba"     # has child reference asset
ORDER_LEGACY = "4c357bfc-3092-4eb6-8c2a-105a6662766b"  # delivered, no scene_reference_log


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
               timeout=20)
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text[:200]}")
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"no token in login response: {r.json()}"
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


# ---------------------------------------------------------------- helpers
def _scene_stage(storyboard):
    for s in storyboard.get("stages", []):
        if s.get("stage_key") == "scene_image_generation":
            return s
    raise AssertionError("scene_image_generation stage missing")


def _ref_keys():
    return {"available", "child_used", "extra_ids_used", "extra_indexes_used",
            "toy_used", "injected_count", "attempted", "used",
            "fallback_path", "fallback_reason", "skipped_reasons"}


# ===================== 1. Storyboard new fields ==========================
class TestStoryboardSceneReferences:

    def test_legacy_order_storyboard_200(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/orders/{ORDER_LEGACY}/storyboard",
                             timeout=30)
        assert r.status_code == 200, r.text[:300]

    def test_legacy_order_aggregate_fields_present(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/orders/{ORDER_LEGACY}/storyboard")
        stage = _scene_stage(r.json())
        os_ = stage.get("output_summary") or {}
        assert "references_total_injected" in os_
        assert "references_used_scene_count" in os_
        assert "references_skipped_total" in os_
        # legacy → all zero
        assert os_["references_total_injected"] == 0
        assert os_["references_used_scene_count"] == 0
        assert os_["references_skipped_total"] == 0

    def test_legacy_per_scene_references_defaults(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/orders/{ORDER_LEGACY}/storyboard")
        stage = _scene_stage(r.json())
        scenes = (stage.get("output_summary") or {}).get("scenes") or []
        assert len(scenes) > 0, "legacy delivered order should have generated scenes"
        for sc in scenes:
            refs = sc.get("references")
            assert refs is not None, f"scene missing references: {sc.get('scene_index')}"
            missing = _ref_keys() - set(refs.keys())
            assert not missing, f"missing keys in references: {missing}"
            # legacy defaults
            assert refs["child_used"] is False
            assert refs["toy_used"] is False
            assert refs["used"] is False
            assert refs["attempted"] is False
            assert refs["injected_count"] == 0
            assert refs["extra_ids_used"] == []
            assert refs["extra_indexes_used"] == []
            assert refs["fallback_path"] is None
            assert refs["fallback_reason"] is None
            assert refs["skipped_reasons"] == []

    def test_ref_order_storyboard_200_and_aggregate(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/orders/{ORDER_REF}/storyboard")
        assert r.status_code == 200
        stage = _scene_stage(r.json())
        os_ = stage.get("output_summary") or {}
        # New aggregate fields must always be present (even if 0)
        assert "references_total_injected" in os_
        assert "references_used_scene_count" in os_
        assert "references_skipped_total" in os_


# ===================== 2. Lab dry-run ==================================
class TestLabSceneImageDryRun:

    def test_dry_run_with_order_returns_reference_dry_run(self, admin_client):
        r = admin_client.post(f"{BASE_URL}/api/admin/lab/run", json={
            "stage_key": "scene_image_generation",
            "inputs": {"order_id": ORDER_REF, "scene_index": 1},
        }, timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("status") == "preview-only"
        assert d.get("error_message") is None
        op = d.get("output_preview") or {}
        assert "rendered_prompt_preview" in op
        rd = op.get("reference_dry_run")
        assert rd is not None, f"reference_dry_run missing: {op}"
        for k in ("available", "child_ref", "extra_char_refs", "toy_ref",
                  "skipped_reasons", "injected_count", "prompt_augmentation"):
            assert k in rd, f"reference_dry_run missing key {k}: {rd}"
        # ORDER_REF has a child asset
        assert rd["available"]["child"] is True
        assert rd["injected_count"] >= 1
        assert "CHILD reference" in rd["prompt_augmentation"]

    def test_dry_run_without_order_id_no_reference_dry_run(self, admin_client):
        r = admin_client.post(f"{BASE_URL}/api/admin/lab/run", json={
            "stage_key": "scene_image_generation",
            "inputs": {},
        }, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d.get("status") == "preview-only"
        assert d.get("error_message") is None
        op = d.get("output_preview") or {}
        assert "rendered_prompt_preview" in op
        assert "reference_dry_run" not in op


# ===================== 3. Pricing line-item rule =======================
class TestPricingSceneReferenceInjection:

    def _post_actual(self, admin_client, order_id):
        r = admin_client.post(
            f"{BASE_URL}/api/admin/orders/{order_id}/pricing/snapshot?kind=actual",
            timeout=30)
        assert r.status_code == 200, r.text[:300]
        return r.json()

    def test_legacy_actual_no_scene_reference_injection(self, admin_client):
        d = self._post_actual(admin_client, ORDER_LEGACY)
        items = ((d.get("snapshot") or {}).get("breakdown") or {}).get("items") or []
        stages = [it.get("stage") for it in items]
        assert "scene_reference_injection" not in stages, (
            f"line item must NOT appear for order without references_used: {stages}"
        )

    def test_pricing_get_returns_snapshot_actual_after_post(self, admin_client):
        # GET should now include the snapshot we just created
        r = admin_client.get(f"{BASE_URL}/api/admin/orders/{ORDER_LEGACY}/pricing")
        assert r.status_code == 200
        d = r.json()
        snap = (d.get("snapshots") or {}).get("actual")
        assert snap is not None, "actual snapshot should be present after POST"
        items = (snap.get("breakdown") or {}).get("items") or []
        stages = [it.get("stage") for it in items]
        assert "scene_reference_injection" not in stages


# ===================== 4. Regression =====================================
class TestRegression:

    def test_lab_stages_returns_seven(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/lab/stages")
        assert r.status_code == 200
        keys = [s["stage_key"] for s in r.json().get("stages", [])]
        # Phase G expanded SUPPORTED_STAGES from 7 → 11 (added extra_character_i2i,
        # book_page_image_generation, video_assembly, pdf_assembly).
        assert len(keys) == 11, keys
        assert "scene_image_generation" in keys

    def test_storyboard_has_nine_stages(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/orders/{ORDER_LEGACY}/storyboard")
        assert r.status_code == 200
        stages = r.json().get("stages", [])
        assert len(stages) == 9, [s.get("stage_key") for s in stages]

    @pytest.mark.parametrize("stage_key", [
        "video_generation", "music_generation",
    ])
    def test_other_preview_only_stages_unchanged(self, admin_client, stage_key):
        r = admin_client.post(f"{BASE_URL}/api/admin/lab/run", json={
            "stage_key": stage_key, "inputs": {},
        }, timeout=20)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert d.get("status") == "preview-only"
        op = d.get("output_preview") or {}
        assert "rendered_prompt_preview" in op
        assert "reference_dry_run" not in op  # only scene_image_generation gets it
