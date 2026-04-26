"""Wave 4 — asset library + retention unit tests."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.asset_service import (  # noqa: E402
    DEFAULT_RETENTION_CONFIG, COLLS, _coll_for,
)


def test_default_retention_thresholds_are_safe():
    c = DEFAULT_RETENTION_CONFIG
    # Hard guard: recent deliveries are always protected.
    assert int(c["protect_recent_delivered_days"]) >= 30
    # Auto-archive only kicks in after the protection window.
    assert int(c["auto_archive_after_delivered_days"]) >= int(c["protect_recent_delivered_days"])
    # Auto-purge requires a long archived window.
    assert int(c["auto_purge_after_archived_days"]) >= 30
    # Active bundle protection on by default.
    assert c["protect_active_bundle_orders"] is True


def test_default_min_age_for_archive_30():
    assert DEFAULT_RETENTION_CONFIG["min_age_for_archive_days"] == 30


def test_default_min_archived_before_purge_30():
    assert DEFAULT_RETENTION_CONFIG["min_archived_days_before_purge"] == 30


def test_collection_map():
    assert dict([(t, c) for t, c, _u in COLLS]) == {"video": "final_videos", "pdf": "final_pdfs"}


def test_coll_for_known_types():
    assert _coll_for("video") == ("final_videos", "video_url")
    assert _coll_for("pdf") == ("final_pdfs", "pdf_url")


def test_coll_for_unknown_raises():
    try:
        _coll_for("garbage")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_lifecycle_states_documented():
    """The service docstring documents 3 lifecycle states + storage caveat."""
    from services import asset_service  # noqa: PLC0415
    doc = asset_service.__doc__ or ""
    for state in ("live", "archived", "purged"):
        assert state in doc
    # Honesty about object storage limitations is required.
    assert "no public delete" in doc.lower() or "may persist" in doc.lower()
