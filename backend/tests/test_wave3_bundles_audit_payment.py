"""Wave 3 — bundles + audit + payment unit tests."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.bundle_service import (  # noqa: E402
    SEEDED_BUNDLES, ALLOWED_OUTPUT_TYPES,
)
from services.audit_service import (  # noqa: E402
    ENTITY_TYPES, ACTIONS, _trim_snapshot,
)
from services.payment_service import (  # noqa: E402
    DEFAULT_PAYMENT_SETTINGS, is_payment_active, stripe_secret,
)
from services.pricing_service import _payment_source  # noqa: E402


# ---------------------------------------------------------------------------
# Bundles — seed shape
# ---------------------------------------------------------------------------
def test_seeded_bundles_count_and_shape():
    assert len(SEEDED_BUNDLES) == 3
    for b in SEEDED_BUNDLES:
        assert b["output_type"] in ALLOWED_OUTPUT_TYPES
        assert b["currency"] == "SAR"
        assert b["quantity"] >= 1
        assert b["validity_days"] >= 1
        assert b["price"] > 0
        assert b["is_seeded"] is True


def test_bundle_output_types_constant():
    assert set(ALLOWED_OUTPUT_TYPES) == {"video", "pdf", "both"}


# ---------------------------------------------------------------------------
# Audit — config constants
# ---------------------------------------------------------------------------
def test_audit_entity_types():
    expected = {
        "pricing_config", "model_registry", "pipeline_config",
        "prompt_template", "bundle", "bundle_purchase",
        "payment_settings", "payment",
    }
    assert set(ENTITY_TYPES) == expected


def test_audit_actions_include_lifecycle():
    for a in ("grant", "reserve", "consume", "refund", "expire"):
        assert a in ACTIONS


def test_audit_trim_snapshot_drops_id():
    out = _trim_snapshot({"_id": "abc", "name": "x"})
    assert "_id" not in out
    assert out["name"] == "x"


def test_audit_trim_snapshot_truncates_long_strings():
    out = _trim_snapshot({"big": "x" * 5000})
    # Default max_chars = 4000, threshold = 400, truncated to 400 + suffix.
    assert out["big"].endswith("...[truncated]")
    assert len(out["big"]) <= 4000


# ---------------------------------------------------------------------------
# Payment — settings + provider flag
# ---------------------------------------------------------------------------
def test_default_payment_settings_safe_shape():
    assert DEFAULT_PAYMENT_SETTINGS["supported_currencies"] == ["SAR"]
    # Apple Pay rides on `card` for Stripe — there is NO standalone apple_pay method.
    assert "card" in DEFAULT_PAYMENT_SETTINGS["supported_methods"]
    # Apple Pay must NEVER appear in payout label semantics.
    label = DEFAULT_PAYMENT_SETTINGS["payout_destination_label"]
    assert "Apple Pay" in label  # explicit clarification "ليس Apple Pay"
    assert "ليس" in label or "not" in label.lower()
    assert DEFAULT_PAYMENT_SETTINGS["apple_pay_domain_verified"] is False


def test_is_payment_active_reflects_env():
    """When STRIPE_API_KEY is in .env, the service is active."""
    sk = stripe_secret()
    assert (sk is not None) == is_payment_active()


# ---------------------------------------------------------------------------
# Pricing — payment_source classifier
# ---------------------------------------------------------------------------
def test_payment_source_pending_when_unpaid():
    assert _payment_source({}) == "pending"
    assert _payment_source({"id": "x"}) == "pending"


def test_payment_source_bundle_when_reserved():
    o = {"bundle_reservation": {"status": "reserved", "bundle_purchase_id": "b1"}}
    assert _payment_source(o) == "bundle"


def test_payment_source_bundle_when_consumed():
    o = {"bundle_reservation": {"status": "consumed", "bundle_purchase_id": "b1"}}
    assert _payment_source(o) == "bundle"


def test_payment_source_paid_when_payment_paid():
    o = {"payment": {"status": "paid"}}
    assert _payment_source(o) == "paid"


def test_payment_source_bundle_wins_over_payment():
    """If both are present, bundle wins (the order was actually fulfilled by a credit)."""
    o = {"bundle_reservation": {"status": "consumed"}, "payment": {"status": "paid"}}
    assert _payment_source(o) == "bundle"
