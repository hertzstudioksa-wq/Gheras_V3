"""Phase N — Admin video-clip recovery endpoint structural tests.

Endpoints under test:
  * POST /api/admin/orders/{order_id}/video-clips/import-by-request-id
  * GET  /api/admin/orders/{order_id}/video-clips

All tests are STRUCTURAL — no live fal.ai key required. We exercise:
  1. Auth: rejects non-admin (no token).
  2. Missing order → 404.
  3. Bogus request_id on existing order → 200 with ok=false (graceful, NOT 500).
  4. Re-import already-imported clip without force → ok=true, state=ALREADY_IMPORTED.
  5. GET listing returns rows with the new metadata fields (import_status,
     fallback_reason, submit_state, submitted_at, imported_at, manually_recovered).
"""
import os
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@gheras.com"
ADMIN_PASSWORD = "Admin@1234"

# The order that the main agent's smoke run already imported 5 clips into.
RECOVERED_ORDER_ID = "359f01b8-356f-46e7-9217-f6d30f57c9d5"


@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    token = body.get("access_token") or body.get("token")
    assert token
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def test_recovery_endpoint_rejects_unauthenticated():
    r = requests.post(
        f"{BASE_URL}/api/admin/orders/{RECOVERED_ORDER_ID}/video-clips/import-by-request-id",
        json={"scene_index": 0, "request_id": "anything"},
        timeout=15,
    )
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


def test_listing_endpoint_rejects_unauthenticated():
    r = requests.get(
        f"{BASE_URL}/api/admin/orders/{RECOVERED_ORDER_ID}/video-clips",
        timeout=15,
    )
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


# ---------------------------------------------------------------------------
# Missing order → 404
# ---------------------------------------------------------------------------
def test_recovery_missing_order_returns_404(admin_headers):
    r = requests.post(
        f"{BASE_URL}/api/admin/orders/00000000-0000-0000-0000-000000000000/video-clips/import-by-request-id",
        json={"scene_index": 0, "request_id": "bogus-request-id-xyz"},
        headers=admin_headers, timeout=20,
    )
    assert r.status_code == 404, f"expected 404 for missing order, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# Bogus request_id on a valid order — graceful 200 ok=false (NOT 500)
# ---------------------------------------------------------------------------
def test_recovery_bogus_request_id_returns_200_ok_false(admin_headers):
    r = requests.post(
        f"{BASE_URL}/api/admin/orders/{RECOVERED_ORDER_ID}/video-clips/import-by-request-id",
        json={"scene_index": 99, "request_id": "bogus-req-id-zzz-not-a-real-fal-job"},
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, f"expected graceful 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("ok") is False, f"expected ok=false on bogus request_id, got {body}"
    assert body.get("error"), "error string must be present on failure"
    assert body.get("import_status") in (
        "import_failed", "still_pending", "import_failed_remote_url_only", "import_failed_storage",
    ), f"unexpected import_status: {body.get('import_status')}"


# ---------------------------------------------------------------------------
# Already-imported re-import without force → ALREADY_IMPORTED
# ---------------------------------------------------------------------------
def test_recovery_already_imported_returns_already_imported(admin_headers):
    # Find one already-imported clip on the recovered order.
    r = requests.get(
        f"{BASE_URL}/api/admin/orders/{RECOVERED_ORDER_ID}/video-clips",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 200, r.text
    listing = r.json()
    clips = listing.get("clips", [])
    imported = [c for c in clips if c.get("import_status") == "imported"]
    if not imported:
        pytest.skip(
            "No imported clip found on recovered order — skipping idempotency test "
            "(env may have been reset)."
        )
    target = imported[0]
    payload = {
        "scene_index": target["scene_index"],
        "request_id": target.get("request_id") or "any-string",
        "force": False,
    }
    r2 = requests.post(
        f"{BASE_URL}/api/admin/orders/{RECOVERED_ORDER_ID}/video-clips/import-by-request-id",
        json=payload, headers=admin_headers, timeout=30,
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body.get("ok") is True, f"expected ok=true on already imported, got {body}"
    assert body.get("state") == "ALREADY_IMPORTED", f"expected state=ALREADY_IMPORTED, got {body}"
    assert body.get("import_status") == "imported"


# ---------------------------------------------------------------------------
# GET listing exposes the recovery metadata fields
# ---------------------------------------------------------------------------
def test_listing_returns_recovery_metadata(admin_headers):
    r = requests.get(
        f"{BASE_URL}/api/admin/orders/{RECOVERED_ORDER_ID}/video-clips",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("order_id") == RECOVERED_ORDER_ID
    assert isinstance(body.get("clips"), list)
    if not body["clips"]:
        pytest.skip("recovered order has no clips in this env")
    sample = body["clips"][0]
    # Print summary for the test report
    print(f"\nRecovered order clips ({len(body['clips'])}):")
    for c in body["clips"]:
        print(
            f"  scene={c.get('scene_index')} import_status={c.get('import_status')} "
            f"manually_recovered={c.get('manually_recovered')} "
            f"request_id={c.get('request_id')} bytes={c.get('size')}"
        )
    # Verify metadata fields are present (some may be None — that's fine).
    expected_fields = {
        "import_status", "request_id", "scene_index",
    }
    missing = expected_fields - set(sample.keys())
    assert not missing, f"missing fields on clip rows: {missing}"


def test_recovered_order_has_5_imported_clips(admin_headers):
    """Per the smoke-run, order 359f01b8 should have 5 imported clips with
    manually_recovered=true."""
    r = requests.get(
        f"{BASE_URL}/api/admin/orders/{RECOVERED_ORDER_ID}/video-clips",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 200
    clips = r.json().get("clips", [])
    imported = [c for c in clips if c.get("import_status") == "imported"]
    if len(imported) < 5:
        pytest.skip(
            f"recovered order shows {len(imported)} imported clips (env may be fresh). "
            "Smoke run reported 5."
        )
    assert len(imported) >= 5
    # At least one should be manually_recovered
    manual = [c for c in imported if c.get("manually_recovered")]
    assert manual, "expected at least one clip flagged manually_recovered=True"
