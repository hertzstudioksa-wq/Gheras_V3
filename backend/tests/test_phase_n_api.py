"""Phase N — Live API e2e tests.

Requires REACT_APP_BACKEND_URL + admin seed (admin@gheras.com / Admin@1234).
Validates 11-stage matrix, 4 fal capability keys, graceful missing-key handling,
and no raw secret leakage.
"""
import os
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not BASE, reason="REACT_APP_BACKEND_URL not set")


EXPECTED = {
    "scenario_generation":        ("openai",    "gpt-5.4-mini",                            "OPENAI_API_KEY"),
    "production_planning":        ("openai",    "gpt-5.4",                                 "OPENAI_API_KEY"),
    "child_character_i2i":        ("openai",    "gpt-image-1.5-2025-12-16",                "OPENAI_API_KEY"),
    "extra_character_i2i":        ("openai",    "gpt-image-1.5-2025-12-16",                "OPENAI_API_KEY"),
    "scene_image_generation":     ("fal_image", "fal-ai/gemini-25-flash-image",            "FAL_KEY_SCENE"),
    "book_page_image_generation": ("fal_image", "fal-ai/gemini-25-flash-image",            "FAL_KEY_SCENE"),
    "narration_generation":       ("fal_tts",   "fal-ai/elevenlabs/tts/multilingual-v2",   "FAL_KEY_NARRATION"),
    "music_generation":           ("fal_music", "fal-ai/elevenlabs/music",                 "FAL_KEY_MUSIC"),
    "video_generation":           ("kling",     "fal-ai/kling-video/v3/pro/image-to-video","FAL_KEY_VIDEO"),
    "video_assembly":             ("ffmpeg",    "local-ffmpeg",                             None),
    "pdf_assembly":               ("reportlab", "local-reportlab",                          None),
}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": "admin@gheras.com", "password": "Admin@1234"},
                      timeout=15)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    return body.get("access_token") or body.get("token")


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def user_token():
    import uuid
    email = f"phase_n_user_{uuid.uuid4().hex[:8]}@test.com"
    r = requests.post(f"{BASE}/api/auth/register",
                      json={"email": email, "password": "Test@1234", "name": "PhaseN"},
                      timeout=15)
    if r.status_code not in (200, 201):
        pytest.skip(f"cannot create non-admin user: {r.status_code} {r.text[:120]}")
    return r.json().get("access_token") or r.json().get("token")


# --------------------------------------------------------------------------- matrix
def test_stage_control_state_matrix_matches_phase_n(admin_headers):
    r = requests.get(f"{BASE}/api/admin/stage-control/state",
                     headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    stages = data.get("stages") or data.get("stage_rows") or []
    assert isinstance(stages, list) and len(stages) >= 11
    rows = {s["stage_key"]: s for s in stages}
    for skey, (prov, model, env_key) in EXPECTED.items():
        row = rows.get(skey)
        assert row, f"stage missing: {skey}"
        assert row["provider"] == prov, f"{skey} provider={row['provider']}"
        assert row["model_name"] == model, f"{skey} model={row['model_name']}"
        assert row.get("env_key") == env_key, f"{skey} env_key={row.get('env_key')}"


def test_pipeline_readiness_11_stages_integrity(admin_headers):
    r = requests.get(f"{BASE}/api/admin/pipeline-readiness",
                     headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    stages = data.get("stages") or []
    assert len(stages) == 11, [s.get("stage_key") for s in stages]
    assert (data.get("integrity") or {}).get("ok") is True or data.get("integrity_ok") is True


# --------------------------------------------------------------------------- secrets status
def test_secrets_status_includes_four_new_fal_keys(admin_headers):
    r = requests.get(f"{BASE}/api/admin/secrets/status",
                     headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    items = data.get("items") or data.get("secrets") or data
    # Convert to env_key -> row
    by_key = {}
    if isinstance(items, list):
        for it in items:
            k = it.get("env_key") or it.get("key") or it.get("name")
            if k:
                by_key[k] = it
    elif isinstance(items, dict):
        by_key = items

    for k in ("FAL_KEY_SCENE", "FAL_KEY_NARRATION", "FAL_KEY_MUSIC", "FAL_KEY_VIDEO", "FAL_KEY"):
        assert k in by_key, f"missing {k} in /secrets/status; got {list(by_key.keys())[:12]}"
        row = by_key[k]
        assert "providers" in row and isinstance(row["providers"], list), f"{k} providers missing"
        assert "purpose" in row and isinstance(row["purpose"], str) and row["purpose"], f"{k} purpose empty"
        assert "source" in row, f"{k} source missing"
        assert "configured" in row, f"{k} configured missing"
        # No raw secret leakage
        for bad_field in ("value", "secret", "raw", "env_value"):
            val = row.get(bad_field)
            assert val in (None, "", False), f"{k} leaks {bad_field}={val!r}"


# --------------------------------------------------------------------------- provider test fn
@pytest.mark.parametrize("prov", ["fal_scene", "fal_narration", "fal_music", "fal_video"])
def test_secrets_test_endpoint_graceful_missing_key(admin_headers, prov):
    r = requests.post(f"{BASE}/api/admin/secrets/test/{prov}",
                      headers=admin_headers, json={}, timeout=20)
    # Must not 500 — endpoint should return a structured dict even when key missing.
    assert r.status_code in (200, 400), f"{prov} returned {r.status_code} {r.text[:200]}"
    data = r.json()
    # When keys are missing, must be graceful
    if not data.get("ok", False):
        src = data.get("secret_source") or data.get("source")
        assert src in ("missing", "not_configured", "env", "db"), f"{prov} unexpected secret_source={src!r}"


# --------------------------------------------------------------------------- RBAC
def test_stage_control_rejects_non_admin(user_token):
    r = requests.get(f"{BASE}/api/admin/stage-control/state",
                     headers={"Authorization": f"Bearer {user_token}"}, timeout=15)
    assert r.status_code in (401, 403), f"non-admin got {r.status_code}"


def test_secrets_status_rejects_unauth():
    r = requests.get(f"{BASE}/api/admin/secrets/status", timeout=15)
    assert r.status_code in (401, 403)
