"""Phase N — Strict cartoon 2D prompt template migration verification.

Verifies the 5 visual-stage prompt_templates rows in MongoDB:
  * have an active version
  * contain the canonical phrase 'STRICT STYLE — soft pastel 2D'
  * contain a FORBIDDEN/anti-realism guard

Plus checks that POST /api/admin/prompt-templates is the established admin pattern
for editing them.
"""
import os
import asyncio
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@gheras.com"
ADMIN_PASSWORD = "Admin@1234"

STAGES = [
    "child_character_i2i",
    "extra_character_i2i",
    "scene_image_generation",
    "book_page_image_generation",
    "video_generation",
]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    body = r.json()
    return body.get("access_token") or body.get("token")


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _fetch_templates_for_stage(stage_key: str, headers: dict):
    r = requests.get(
        f"{BASE_URL}/api/admin/prompt-templates/stage/{stage_key}",
        headers=headers, timeout=15,
    )
    assert r.status_code == 200, f"{stage_key}: {r.status_code} {r.text}"
    return r.json()


def test_admin_can_list_all_prompt_templates(admin_headers):
    r = requests.get(
        f"{BASE_URL}/api/admin/prompt-templates",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) >= 5
    stage_set = {row["stage_key"] for row in rows}
    for stage in STAGES:
        assert stage in stage_set, f"missing stage {stage} in prompt_templates list"


@pytest.mark.parametrize("stage_key", STAGES)
def test_strict_2d_template_active_for_each_stage(stage_key, admin_headers):
    docs = _fetch_templates_for_stage(stage_key, admin_headers)
    assert isinstance(docs, list) and docs, f"{stage_key}: no templates"
    active = [d for d in docs if d.get("active")]
    assert len(active) == 1, f"{stage_key}: expected exactly 1 active template, got {len(active)}"
    tpl = active[0]
    text = tpl.get("template_text") or ""
    assert "STRICT STYLE — soft pastel 2D" in text, (
        f"{stage_key} v{tpl.get('version')}: missing canonical strict-2D phrase. "
        f"First 200 chars: {text[:200]!r}"
    )
    assert "FORBIDDEN" in text, (
        f"{stage_key} v{tpl.get('version')}: missing FORBIDDEN anti-realism guard"
    )


def test_strict_2d_summary_table(admin_headers):
    """Emit the canonical summary table the test report needs."""
    summary = []
    for stage in STAGES:
        docs = _fetch_templates_for_stage(stage, admin_headers)
        active = next((d for d in docs if d.get("active")), None)
        if not active:
            summary.append({"stage_key": stage, "version": None, "has_strict_phrase": False})
            continue
        text = active.get("template_text") or ""
        summary.append({
            "stage_key": stage,
            "version": active.get("version"),
            "has_strict_phrase": "STRICT STYLE — soft pastel 2D" in text,
            "has_forbidden_guard": "FORBIDDEN" in text,
        })
    print("\nSTRICT-2D PROMPT TEMPLATE SUMMARY:")
    for row in summary:
        print(f"  {row}")
    # Hard guarantee for the report: all 5 must satisfy both.
    assert all(r["has_strict_phrase"] and r["has_forbidden_guard"] for r in summary)


def test_post_new_prompt_template_creates_inactive_version(admin_headers):
    """POST /api/admin/prompt-templates is the editable path. Verify it works."""
    payload = {
        "stage_key": "video_generation",
        "name": "TEST_strict_v_probe",
        "template_text": "TEST probe — STRICT STYLE — soft pastel 2D — FORBIDDEN photorealism",
        "variables": ["scene_text"],
        "notes": "TEST_ — created by backend test, safe to ignore",
        "active": False,
    }
    r = requests.post(
        f"{BASE_URL}/api/admin/prompt-templates",
        json=payload, headers=admin_headers, timeout=15,
    )
    assert r.status_code in (200, 201), f"create prompt failed: {r.status_code} {r.text}"
    created = r.json()
    assert created["stage_key"] == "video_generation"
    assert created.get("active") is False, "new version must default to inactive (no auto-activation)"
    assert "id" in created and "version" in created
    # Persistence check
    docs = _fetch_templates_for_stage("video_generation", admin_headers)
    assert any(d["id"] == created["id"] for d in docs), "created template not persisted"
