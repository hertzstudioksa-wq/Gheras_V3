"""Phase L — fal.ai Kling video adapter end-to-end API tests."""
import os
import requests
import pytest

BASE_URL = "https://girasai-create.preview.emergentagent.com"
ADMIN_EMAIL = "admin@gheras.com"
ADMIN_PASSWORD = "Admin@1234"


@pytest.fixture(scope="module")
def admin_token():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text}")
    data = r.json()
    tok = data.get("token") or data.get("access_token") or (data.get("data") or {}).get("token")
    if not tok:
        pytest.skip(f"no token in login response: {data}")
    return tok


@pytest.fixture(scope="module")
def auth_client(admin_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"})
    return s


# ---------- /api/admin/stage-control/state ----------------------------------
def test_stage_control_state_video_defaults(auth_client):
    r = auth_client.get(f"{BASE_URL}/api/admin/stage-control/state", timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("video_real_call_available") is False
    vd = body.get("video_defaults") or {}
    assert vd.get("env_key") == "FAL_KEY_VIDEO"
    assert vd.get("strategy") == "hybrid_i2v_then_t2v"
    assert vd.get("model", "").startswith("fal-ai/kling-video/")
    remaining = body.get("stages_remaining_to_wire") or []
    assert "video_generation" not in remaining
    # Phase M: music_generation also moved out of not-yet-wired.
    assert "music_generation" not in remaining


def test_stage_control_state_video_row(auth_client):
    r = auth_client.get(f"{BASE_URL}/api/admin/stage-control/state", timeout=30)
    body = r.json()
    rows = body.get("stages") or body.get("rows") or []
    video_row = next((row for row in rows if row.get("stage_key") == "video_generation"), None)
    assert video_row is not None
    assert video_row.get("provider") == "kling"
    assert video_row.get("model_name", "").startswith("fal-ai/kling-video/")
    assert video_row.get("env_key") == "FAL_KEY_VIDEO"
    assert video_row.get("secret_source") == "missing"
    assert video_row.get("executor_status") == "real-call-when-keyed"
    assert video_row.get("executor_callable") is False
    assert video_row.get("is_real_call_stage") is True
    choices = video_row.get("provider_choices") or []
    for p in ("kling", "sora", "luma", "ffmpeg"):
        assert p in choices, f"missing {p} in {choices}"


# ---------- /api/admin/secrets/status ---------------------------------------
def test_secrets_status_includes_fal_key(auth_client):
    r = auth_client.get(f"{BASE_URL}/api/admin/secrets/status", timeout=30)
    assert r.status_code == 200, r.text
    items = r.json().get("items") or []
    fal = next((i for i in items if i.get("key") == "FAL_KEY"), None)
    assert fal is not None, f"FAL_KEY missing in {[i.get('key') for i in items]}"
    assert fal.get("test_provider_key") == "fal"
    label = (fal.get("label") or "").lower()
    assert "fal" in label
    providers = fal.get("providers") or []
    assert "kling" in providers
    # ELEVENLABS still present
    assert any(i.get("key") == "ELEVENLABS_API_KEY" for i in items)
    assert fal.get("source") == "missing"


# ---------- /api/admin/secrets/test/fal -------------------------------------
def test_secrets_test_fal_no_key(auth_client):
    r = auth_client.post(f"{BASE_URL}/api/admin/secrets/test/fal", json={}, timeout=30)
    # Must not 500
    assert r.status_code in (200, 400), f"unexpected {r.status_code} {r.text}"
    body = r.json()
    assert body.get("ok") is False
    assert body.get("auth_ok") is False
    assert body.get("secret_source") == "missing"
    err = (body.get("error") or "").upper()
    assert "FAL_KEY" in err or "fal" in (body.get("error") or "").lower()


# ---------- PATCH/RESET round-trip ------------------------------------------
def test_patch_video_then_reset(auth_client):
    new_model = "fal-ai/kling-video/v3/pro/image-to-video"
    try:
        r = auth_client.patch(
            f"{BASE_URL}/api/admin/stage-control/video_generation",
            json={"provider": "kling", "model_name": new_model},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        # Verify state reflects it
        s = auth_client.get(f"{BASE_URL}/api/admin/stage-control/state", timeout=30).json()
        rows = s.get("stages") or s.get("rows") or []
        row = next((x for x in rows if x.get("stage_key") == "video_generation"), {})
        assert row.get("model_name") == new_model
        assert row.get("provider") == "kling"
    finally:
        rr = auth_client.post(
            f"{BASE_URL}/api/admin/stage-control/video_generation/reset",
            json={}, timeout=30,
        )
        assert rr.status_code == 200, rr.text
        body = rr.json()
        # Reset should bring back kling default
        s2 = auth_client.get(f"{BASE_URL}/api/admin/stage-control/state", timeout=30).json()
        rows = s2.get("stages") or s2.get("rows") or []
        row = next((x for x in rows if x.get("stage_key") == "video_generation"), {})
        assert row.get("provider") == "kling"
        assert row.get("model_name") == "fal-ai/kling-video/v3/pro/image-to-video"


# ---------- LAB run ---------------------------------------------------------
def test_lab_run_video_requires_cost_ack(auth_client):
    r = auth_client.post(
        f"{BASE_URL}/api/admin/lab/run",
        json={"stage_key": "video_generation", "inputs": {"video_prompt": "a cat plays piano"}},
        timeout=120,
    )
    assert r.status_code == 400, f"expected 400 cost-ack gate, got {r.status_code}: {r.text}"


def test_lab_run_video_with_ack_falls_back_to_mock(auth_client):
    r = auth_client.post(
        f"{BASE_URL}/api/admin/lab/run",
        json={
            "stage_key": "video_generation",
            "acknowledged_cost": True,
            "inputs": {"video_prompt": "a cat plays piano", "duration": 5},
        },
        timeout=180,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "success", body
    op = body.get("output_preview") or {}
    assert op.get("real_call") is False
    assert op.get("fallback_to_mock") is True
    # error must NOT be a 500-like, but key-missing is fine; absence is also fine.


# ---------- pipeline-readiness ----------------------------------------------
def test_pipeline_readiness_video_flags(auth_client):
    r = auth_client.get(f"{BASE_URL}/api/admin/pipeline-readiness", timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body.get("stages") or body.get("rows") or []
    row = next((x for x in rows if x.get("stage_key") == "video_generation"), None)
    assert row is not None
    assert row.get("executor_status") == "real-call-when-keyed"
    assert row.get("is_real_call_stage") is True
    assert "executor_callable" in row
    assert "prompt_editable" in row


# ---------- pricing ---------------------------------------------------------
def test_pricing_video_per_model(auth_client):
    r = auth_client.get(f"{BASE_URL}/api/admin/pricing/config", timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    psc = body.get("per_stage_costs") or {}
    assert psc.get("video_generation", 0) > 0
    overrides = body.get("video_generation_per_model") or {}
    assert "fal-ai/kling-video/v3/pro/image-to-video" in overrides
    assert "fal-ai/kling-video/v3/pro/image-to-video" in overrides


# ---------- regression / smoke ---------------------------------------------
def test_admin_routes_load(auth_client):
    paths = [
        "/api/admin/stage-control/state",
        "/api/admin/secrets/status",
        "/api/admin/pipeline-readiness",
        "/api/admin/pricing/config",
        "/api/admin/lab/stages",
    ]
    for p in paths:
        r = auth_client.get(f"{BASE_URL}{p}", timeout=30)
        assert r.status_code == 200, f"{p} -> {r.status_code} {r.text[:200]}"
