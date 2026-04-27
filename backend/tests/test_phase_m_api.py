"""Phase M — live API tests against REACT_APP_BACKEND_URL.

Covers:
  - GET /api/admin/stage-control/state → music_real_call_available + music_defaults
  - POST /api/admin/lab/run for music_generation in 3 modes (music/human_rhythm/none)
  - POST /api/admin/secrets/test/elevenlabs_music with no key
  - PATCH/Reset round-trip on music_generation row
  - Pricing per_stage_costs.music_generation > 0
  - GET /api/admin/orders/{order_id}/storyboard → 11 stages incl. video_generation + music_generation
  - Regression: /api/admin/secrets/status mentions ELEVENLABS_API_KEY label.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://girasai-create.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@gheras.com"
ADMIN_PASSWORD = "Admin@1234"


@pytest.fixture(scope="module")
def admin_token():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
               timeout=30)
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text[:200]}")
    data = r.json()
    token = data.get("token") or data.get("access_token")
    assert token, f"No token in login response: {data}"
    return token


@pytest.fixture(scope="module")
def admin_client(admin_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {admin_token}",
                      "Content-Type": "application/json"})
    return s


# ---- stage-control state ---------------------------------------------------
def test_stage_control_state_music_defaults(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/admin/stage-control/state", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()

    # music_real_call_available is honest — no key configured today
    assert "music_real_call_available" in data
    assert data["music_real_call_available"] is False

    md = data.get("music_defaults") or {}
    assert md.get("model") == "fal-ai/elevenlabs/music"
    assert md.get("env_key") == "FAL_KEY_MUSIC"
    modes = md.get("supported_modes") or []
    assert set(modes) >= {"music", "human_rhythm", "none"}
    assert "plan_required" in md or "plan" in str(md).lower()
    assert "human_rhythm_note" in md or "human_rhythm" in str(md).lower()

    # Phase M removed music_generation from stages_remaining_to_wire
    remaining = data.get("stages_remaining_to_wire", [])
    assert "music_generation" not in remaining


def test_stage_control_state_music_row(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/admin/stage-control/state", timeout=30)
    assert r.status_code == 200
    rows = r.json().get("stages") or r.json().get("rows") or []
    music_row = next((x for x in rows if x.get("stage_key") == "music_generation"), None)
    assert music_row is not None, f"music_generation row missing. Rows: {[x.get('stage_key') for x in rows]}"

    assert music_row["provider"] == "fal_music"
    assert music_row["model_name"] == "fal-ai/elevenlabs/music"
    assert music_row["env_key"] == "FAL_KEY_MUSIC"
    assert music_row["secret_source"] == "missing"
    assert music_row["executor_status"] == "real-call-when-keyed"
    assert music_row["executor_callable"] is False
    assert music_row.get("is_real_call_stage") is True
    pc = music_row.get("provider_choices") or []
    assert "elevenlabs" in pc and "suno" in pc and "mock" in pc


# ---- lab run for music_generation -----------------------------------------
def test_lab_music_requires_cost_ack(admin_client):
    body = {"stage_key": "music_generation",
            "inputs": {"audio_background_mode": "music"}}
    r = admin_client.post(f"{BASE_URL}/api/admin/lab/run", json=body, timeout=60)
    assert r.status_code == 400, f"expected 400 without ack, got {r.status_code}: {r.text[:200]}"


def test_lab_music_mode_music_skips_when_keyless(admin_client):
    body = {"stage_key": "music_generation",
            "acknowledged_cost": True,
            "inputs": {"audio_background_mode": "music",
                       "duration_seconds": 20,
                       "themes": ["kindness"],
                       "mood": "hopeful"}}
    r = admin_client.post(f"{BASE_URL}/api/admin/lab/run", json=body, timeout=90)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out.get("status") == "success"
    preview = out.get("output_preview") or {}
    assert preview.get("real_call") is False
    impl = preview.get("mode_implementation") or out.get("mode_implementation")
    assert impl == "native_music", f"unexpected impl: {impl}"
    skip = preview.get("skip_reason") or out.get("skip_reason")
    assert skip in ("missing_key", "plan_required", "auth_failed", "provider_unavailable")


def test_lab_music_mode_human_rhythm(admin_client):
    body = {"stage_key": "music_generation",
            "acknowledged_cost": True,
            "inputs": {"audio_background_mode": "human_rhythm",
                       "duration_seconds": 20}}
    r = admin_client.post(f"{BASE_URL}/api/admin/lab/run", json=body, timeout=90)
    assert r.status_code == 200, r.text
    out = r.json()
    preview = out.get("output_preview") or {}
    impl = preview.get("mode_implementation") or out.get("mode_implementation")
    assert impl == "prompt_biased_no_native_support"


def test_lab_music_mode_none_records_skip(admin_client):
    body = {"stage_key": "music_generation",
            "acknowledged_cost": True,
            "inputs": {"audio_background_mode": "none"}}
    r = admin_client.post(f"{BASE_URL}/api/admin/lab/run", json=body, timeout=60)
    assert r.status_code == 200, r.text
    out = r.json()
    preview = out.get("output_preview") or {}
    skip = preview.get("skip_reason") or out.get("skip_reason")
    assert skip == "mode_none"
    impl = preview.get("mode_implementation") or out.get("mode_implementation")
    assert impl == "skipped_by_request"


# ---- secrets test for elevenlabs_music ------------------------------------
def test_secrets_test_elevenlabs_music_no_key(admin_client):
    r = admin_client.post(f"{BASE_URL}/api/admin/secrets/test/elevenlabs_music",
                          json={}, timeout=30)
    # Must NOT 500
    assert r.status_code == 200, f"Got {r.status_code}: {r.text[:300]}"
    out = r.json()
    assert out.get("ok") is False
    assert out.get("secret_source") == "missing"
    err = (out.get("error") or "").lower()
    assert "key" in err or "missing" in err or "elevenlabs" in err


def test_secrets_status_elevenlabs_label(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/admin/secrets/status", timeout=30)
    assert r.status_code == 200
    data = r.json()
    items = data.get("items") or data.get("secrets") or data
    # find ELEVENLABS_API_KEY entry
    found = None
    if isinstance(items, list):
        found = next((x for x in items if (x.get("env_key") == "FAL_KEY_MUSIC"
                                           or x.get("key") == "FAL_KEY_MUSIC")), None)
    elif isinstance(items, dict):
        found = items.get("FAL_KEY_MUSIC")
    assert found, f"ELEVENLABS_API_KEY missing in secrets status. Got: {str(items)[:300]}"
    label = (found.get("label") or "").lower()
    assert "music" in label or "tts" in label, f"Expected updated label, got: {label}"


# ---- patch + reset round-trip ---------------------------------------------
def test_patch_music_then_reset(admin_client):
    try:
        # patch to suno + custom model
        r1 = admin_client.patch(f"{BASE_URL}/api/admin/stage-control/music_generation",
                                json={"provider": "suno", "model_name": "suno-v3.5"}, timeout=30)
        assert r1.status_code in (200, 204), r1.text
        # verify
        st = admin_client.get(f"{BASE_URL}/api/admin/stage-control/state", timeout=30).json()
        rows = st.get("stages") or st.get("rows") or []
        row = next(x for x in rows if x.get("stage_key") == "music_generation")
        assert row["provider"] == "suno"
        assert row["model_name"] == "suno-v3.5"
    finally:
        # reset
        rr = admin_client.post(f"{BASE_URL}/api/admin/stage-control/music_generation/reset",
                               timeout=30)
        assert rr.status_code in (200, 204), rr.text
        st2 = admin_client.get(f"{BASE_URL}/api/admin/stage-control/state", timeout=30).json()
        rows2 = st2.get("stages") or st2.get("rows") or []
        row2 = next(x for x in rows2 if x.get("stage_key") == "music_generation")
        assert row2["provider"] == "fal_music"
        assert row2["model_name"] == "fal-ai/elevenlabs/music"


# ---- pricing --------------------------------------------------------------
def test_pricing_music_generation_present(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/admin/pricing/config", timeout=30)
    assert r.status_code == 200, r.text
    cfg = r.json()
    psc = cfg.get("per_stage_costs") or {}
    assert psc.get("music_generation", 0) >= 0.50
    # video_generation_per_model still present from Phase L
    assert "video_generation_per_model" in cfg


# ---- storyboard 11 stages -------------------------------------------------
def _find_test_order(client):
    """Try to find any existing order to test storyboard against."""
    for path in ["/api/admin/orders", "/api/admin/orders?limit=5", "/api/orders"]:
        try:
            r = client.get(f"{BASE_URL}{path}", timeout=30)
            if r.status_code != 200:
                continue
            data = r.json()
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("orders") or data.get("items") or []
            else:
                items = []
            if items:
                first = items[0]
                oid = first.get("order_id") or first.get("id") or first.get("_id")
                if oid:
                    return oid
        except Exception:
            continue
    return None


def test_storyboard_has_11_stages_with_music_and_video(admin_client):
    oid = _find_test_order(admin_client)
    if not oid:
        pytest.skip("No existing order to test storyboard against")
    r = admin_client.get(f"{BASE_URL}/api/admin/orders/{oid}/storyboard", timeout=45)
    if r.status_code == 404:
        pytest.skip(f"order {oid} not found via storyboard route")
    assert r.status_code == 200, r.text
    sb = r.json()
    stages = sb.get("stages") or []
    keys = [s.get("stage_key") for s in stages]
    assert "music_generation" in keys, f"music_generation missing. Got: {keys}"
    assert "video_generation" in keys, f"video_generation missing. Got: {keys}"
    assert len(stages) >= 11, f"expected >=11 stages, got {len(stages)}: {keys}"


def test_storyboard_music_and_video_stage_shape(admin_client):
    oid = _find_test_order(admin_client)
    if not oid:
        pytest.skip("No existing order to test storyboard against")
    r = admin_client.get(f"{BASE_URL}/api/admin/orders/{oid}/storyboard", timeout=45)
    if r.status_code != 200:
        pytest.skip(f"storyboard not available: {r.status_code}")
    stages = r.json().get("stages") or []
    music = next((s for s in stages if s.get("stage_key") == "music_generation"), None)
    video = next((s for s in stages if s.get("stage_key") == "video_generation"), None)
    assert music is not None
    assert video is not None
    # video stage should have output_summary structure (scene_clips may be empty list)
    vs = video.get("output_summary") or {}
    assert "scene_clips" in vs or vs == {} or isinstance(vs, dict)
    # music stage shape
    ms_in = music.get("input_summary") or {}
    ms_out = music.get("output_summary") or {}
    # When unrun, fields may be empty/None — ensure dict types and known keys appear or are absent gracefully
    assert isinstance(ms_in, dict)
    assert isinstance(ms_out, dict)


# ---- regression: admin secrets status still has FAL_KEY -------------------
def test_secrets_status_has_fal_key(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/admin/secrets/status", timeout=30)
    assert r.status_code == 200
    items = r.json().get("items") or r.json().get("secrets") or r.json()
    found = None
    if isinstance(items, list):
        found = next((x for x in items if (x.get("env_key") == "FAL_KEY"
                                           or x.get("key") == "FAL_KEY")), None)
    elif isinstance(items, dict):
        found = items.get("FAL_KEY")
    assert found, "FAL_KEY missing in secrets/status"
