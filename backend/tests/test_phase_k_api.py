"""Phase K — API-level e2e tests against live preview backend.

Covers:
  * /api/admin/stage-control/state — 11 stages w/ new flags
  * PATCH /api/admin/stage-control/{stage_key} — persists + 400 on bad provider
  * POST /api/admin/stage-control/{stage_key}/reset — returns to defaults
  * POST /api/admin/lab/run for narration_generation — cost-ack gate + mock fallback
  * /api/admin/pipeline-readiness — new flags exposed
  * /api/admin/lab/stages — narration shows real-call-when-keyed
  * /api/admin/secrets/status — ELEVENLABS_API_KEY entry intact
  * /api/admin/pricing/config — narration_generation cost set
"""
import os
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://girasai-create.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@gheras.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@1234")

EXPECTED_STAGES = {
    "scenario_generation",
    "production_planning",
    "child_character_i2i",
    "scene_image_generation",
    "narration_generation",
    "extra_character_i2i",
    "book_page_image_generation",
    "music_generation",
    "video_generation",
    "video_assembly",
    "pdf_assembly",
}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text[:200]}")
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ---------- /admin/stage-control/state ------------------------------------
def test_stage_control_state_returns_11_stages(auth_headers):
    r = requests.get(f"{BASE_URL}/api/admin/stage-control/state", headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("supported_stages_count") == 11, body.get("supported_stages_count")
    stages = body.get("stages") or []
    assert len(stages) == 11
    keys = {s["stage_key"] for s in stages}
    assert keys == EXPECTED_STAGES, keys.symmetric_difference(EXPECTED_STAGES)
    # New fields present on every stage
    required_fields = {
        "executor_callable", "prompt_editable", "is_real_call_stage",
        "provider_choices", "default_provider", "default_model", "env_label",
    }
    for s in stages:
        missing = required_fields - set(s.keys())
        assert not missing, f"{s['stage_key']} missing {missing}"
        assert isinstance(s["provider_choices"], list)
    # narration_real_call_available is False (no key configured in this pod)
    assert body.get("narration_real_call_available") is False
    remaining = body.get("stages_remaining_to_wire") or []
    assert set(remaining) == {"music_generation", "video_generation"}, remaining


# ---------- PATCH /admin/stage-control/{stage_key} ------------------------
def test_patch_narration_persists(auth_headers):
    payload = {
        "provider": "elevenlabs",
        "model_name": "eleven_multilingual_v2",
        "env_key": "ELEVENLABS_API_KEY",
    }
    r = requests.patch(
        f"{BASE_URL}/api/admin/stage-control/narration_generation",
        headers=auth_headers,
        json=payload,
        timeout=20,
    )
    assert r.status_code == 200, r.text
    # re-fetch and verify
    state = requests.get(f"{BASE_URL}/api/admin/stage-control/state", headers=auth_headers, timeout=20).json()
    narr = next(s for s in state["stages"] if s["stage_key"] == "narration_generation")
    assert narr.get("provider") == "elevenlabs"
    # field is named `model_name` in the response (legacy registry shape)
    assert narr.get("model_name") == "eleven_multilingual_v2", narr.get("model_name")
    assert narr.get("env_key") == "ELEVENLABS_API_KEY"


def test_patch_invalid_provider_returns_400(auth_headers):
    r = requests.patch(
        f"{BASE_URL}/api/admin/stage-control/narration_generation",
        headers=auth_headers,
        json={"provider": "definitely_not_a_provider", "model": "x", "env_key": "Y"},
        timeout=20,
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


# ---------- POST /admin/stage-control/{stage_key}/reset -------------------
def test_reset_narration_returns_defaults(auth_headers):
    r = requests.post(
        f"{BASE_URL}/api/admin/stage-control/narration_generation/reset",
        headers=auth_headers,
        timeout=20,
    )
    assert r.status_code == 200, r.text
    state = requests.get(f"{BASE_URL}/api/admin/stage-control/state", headers=auth_headers, timeout=20).json()
    narr = next(s for s in state["stages"] if s["stage_key"] == "narration_generation")
    # After reset the provider/model/env_key should match the *default_* fields.
    assert narr["provider"] == narr["default_provider"]
    assert narr["model_name"] == narr["default_model"]


# ---------- POST /admin/lab/run for narration_generation ------------------
def test_lab_run_narration_requires_cost_ack(auth_headers):
    r = requests.post(
        f"{BASE_URL}/api/admin/lab/run",
        headers=auth_headers,
        json={
            "stage_key": "narration_generation",
            "inputs": {"narration_text": "مرحباً يا أصدقائي، هذه قصة قصيرة."},
        },
        timeout=30,
    )
    assert r.status_code == 400, f"expected 400 cost-ack gate, got {r.status_code}: {r.text[:300]}"


def test_lab_run_narration_with_ack_succeeds_with_mock_fallback(auth_headers):
    # Make sure the narration row points at elevenlabs so the executor *attempts*
    # the real call, hits the missing-key path, and falls back to mock with
    # fallback_to_mock=True. (If the row is left at provider=mock, the path is
    # mock-by-design and fallback_to_mock=False — also valid but doesn't
    # exercise the Phase K real-call wiring.)
    requests.patch(
        f"{BASE_URL}/api/admin/stage-control/narration_generation",
        headers=auth_headers,
        json={"provider": "elevenlabs", "model_name": "eleven_multilingual_v2", "env_key": "ELEVENLABS_API_KEY"},
        timeout=20,
    )
    try:
        r = requests.post(
            f"{BASE_URL}/api/admin/lab/run",
            headers=auth_headers,
            json={
                "stage_key": "narration_generation",
                "acknowledged_cost": True,
                "inputs": {"narration_text": "مرحباً يا أصدقائي، هذه قصة قصيرة."},
            },
            timeout=60,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:400]}"
        body = r.json()
        assert body.get("status") == "success", body
        op = body.get("output_preview") or {}
        assert op.get("real_call") is False, op
        assert op.get("fallback_to_mock") is True, op
        dur = op.get("duration_seconds")
        assert isinstance(dur, (int, float)), op
        # provider should be elevenlabs (active model_registry provider) — the
        # adapter records elevenlabs even on fallback so admins can see what
        # was attempted.
        assert (body.get("provider") or op.get("provider")) in {"elevenlabs", "mock"}
    finally:
        # Reset to defaults for repeatability
        requests.post(
            f"{BASE_URL}/api/admin/stage-control/narration_generation/reset",
            headers=auth_headers, timeout=20,
        )


# ---------- /admin/pipeline-readiness -------------------------------------
def test_pipeline_readiness_exposes_new_flags(auth_headers):
    r = requests.get(f"{BASE_URL}/api/admin/pipeline-readiness", headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    stages = body.get("stages") or body.get("rows") or []
    assert stages, body
    narr = next((s for s in stages if s.get("stage_key") == "narration_generation"), None)
    assert narr is not None, "narration_generation row missing"
    for f in ("executor_callable", "prompt_editable", "is_real_call_stage"):
        assert f in narr, f"missing flag {f} in narration row: {narr.keys()}"
    assert narr.get("executor_status") == "real-call-when-keyed", narr.get("executor_status")


# ---------- /admin/lab/stages ---------------------------------------------
def test_lab_stages_narration_executor_status_promoted(auth_headers):
    r = requests.get(f"{BASE_URL}/api/admin/lab/stages", headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    rows = r.json().get("stages") or r.json()
    narr = next((s for s in rows if s.get("stage_key") == "narration_generation"), None)
    assert narr is not None
    assert narr.get("executor_status") == "real-call-when-keyed"


# ---------- /admin/secrets/status -----------------------------------------
def test_secrets_status_has_elevenlabs_entry(auth_headers):
    r = requests.get(f"{BASE_URL}/api/admin/secrets/status", headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    items = body.get("items") if isinstance(body, dict) else body
    assert items, body
    found = next(
        (s for s in items if s.get("key") == "ELEVENLABS_API_KEY"
                       or s.get("env_key") == "ELEVENLABS_API_KEY"),
        None,
    )
    assert found is not None, items
    providers = found.get("providers") or [found.get("provider")]
    assert any((p or "").lower() == "elevenlabs" for p in providers), providers


# ---------- /admin/pricing/config -----------------------------------------
def test_pricing_config_narration_and_video_music(auth_headers):
    r = requests.get(f"{BASE_URL}/api/admin/pricing/config", headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    cfg = r.json()
    costs = cfg.get("per_stage_costs") or cfg.get("config", {}).get("per_stage_costs")
    assert costs, cfg
    assert costs.get("narration_generation", 0) >= 0.10
    assert costs.get("narration_audio") == costs.get("narration_generation")
    assert costs.get("video_generation", 0) > 0
    assert costs.get("music_generation", 0) > 0
