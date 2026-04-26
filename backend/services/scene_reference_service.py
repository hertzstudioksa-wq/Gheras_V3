"""Scene Reference Service — Phase E.

Resolves which existing reference assets (child portrait, extra characters,
toy/object) are RELEVANT to a given scene and assembles them into a structured
package that the scene_image_generation step can consume.

Caps (per scene):
  child: 1, extras: 2, toy: 1   → max 4 reference images per scene call.

Granular `skipped_reasons` codes:
  scene_not_relevant            — character/toy is not in this scene
  missing_asset                 — no generated_image_url to attach
  too_many_references_trimmed   — extras over the cap dropped
  reference_fetch_failed        — present at resolve time but bytes failed (filled by orchestrator)
  provider_no_reference_support — provider does not accept image inputs (filled by image service)

Backward compatibility:
  * If no references exist for the order, returns an "empty" package and the
    caller proceeds with the legacy text-only prompt path.
  * The package surfaces `available_*` so the storyboard can show "had it
    but didn't inject" with a clear `skipped_reasons` array.
"""
from __future__ import annotations
import logging
from db import db

logger = logging.getLogger("scene_reference_service")

MAX_EXTRA_REFS = 2
MAX_TOY_REFS   = 1


def _name_in(haystack: str, needle: str) -> bool:
    if not haystack or not needle:
        return False
    n = (needle or "").strip().lower()
    return bool(n) and n in (haystack or "").lower()


async def _load_child_asset(order_id: str) -> dict | None:
    return await db.child_character_assets.find_one(
        {"order_id": order_id, "generated_image_url": {"$ne": None}},
        {"_id": 0},
        sort=[("created_at", -1)],
    )


async def _load_extra_assets(order_id: str) -> list[dict]:
    rows = await db.extra_character_assets.find(
        {"order_id": order_id, "generated_image_url": {"$ne": None}},
        {"_id": 0},
    ).to_list(20)
    return rows


async def _load_character_profiles(order_id: str, plan_id: str | None) -> dict[str, dict]:
    """Return character_profiles keyed by id (only for the active plan)."""
    q = {"order_id": order_id, "is_archived": False}
    if plan_id:
        q["production_plan_id"] = plan_id
    rows = await db.character_profiles.find(q, {"_id": 0}).to_list(50)
    return {r["id"]: r for r in rows if r.get("id")}


def _scene_text_blob(scene: dict) -> str:
    """All searchable text on the scene, lowercased once at call sites."""
    img_prompt = scene.get("image_prompt") or {}
    return " ".join(filter(None, [
        scene.get("title"), scene.get("scene_goal"),
        scene.get("narration_text"), scene.get("book_text"),
        scene.get("visual_description"), scene.get("background_setting"),
        img_prompt.get("prompt_text") if isinstance(img_prompt, dict) else "",
    ]))


async def resolve_scene_references(order: dict, plan: dict, scene: dict) -> dict:
    """Compute which references should be attached to this scene's image call.

    Returns:
      {
        "child_ref":        {"url", "name", "type"} | None,
        "extra_char_refs":  [ {"url","name","type","character_id","character_index"} ... ]   (≤ 2),
        "toy_ref":          {"url","name","description"} | None,
        "injected_count":   int,
        "available": {
            "child":  bool,
            "extras": [ {"character_id","character_index","name","type"} ... ],
            "toy":    bool,
        },
        "skipped_reasons": [ {"kind","id","name","reason"} ... ],
        "prompt_augmentation": "...string to APPEND to the text prompt..."
      }
    """
    order_id = order["id"]
    plan_id = (plan or {}).get("id") or order.get("production_plan_id")

    out: dict = {
        "child_ref": None,
        "extra_char_refs": [],
        "toy_ref": None,
        "injected_count": 0,
        "available": {"child": False, "extras": [], "toy": False},
        "skipped_reasons": [],
        "prompt_augmentation": "",
    }

    data = order.get("data") or {}
    child = data.get("child") or {}
    pers  = data.get("personalization") or {}
    chars = data.get("characters") or []
    child_name = (child.get("name") or "").strip()

    # Scene shape — characters_in_scene is a list of {character_profile_id, role_in_scene}.
    chars_in_scene_raw = scene.get("characters_in_scene") or []
    scene_role_types: list[str] = []   # e.g., ["child", "mother", "friend"]
    scene_profile_ids: list[str] = []
    for entry in chars_in_scene_raw:
        if isinstance(entry, dict):
            if entry.get("role_in_scene"):
                scene_role_types.append(str(entry["role_in_scene"]).strip().lower())
            if entry.get("character_profile_id"):
                scene_profile_ids.append(entry["character_profile_id"])
        elif isinstance(entry, str):
            scene_role_types.append(entry.strip().lower())

    scene_objects = [str(x).strip() for x in (scene.get("key_objects") or []) if x]
    scene_text_blob = _scene_text_blob(scene)

    # ---- Child reference ----------------------------------------------------
    child_asset = await _load_child_asset(order_id)
    out["available"]["child"] = bool(child_asset and child_asset.get("generated_image_url"))
    if child_asset and child_asset.get("generated_image_url"):
        # Child is relevant when:
        #   a) "child" appears in scene_role_types, OR
        #   b) child name appears in scene text (defensive), OR
        #   c) scene has no characters_in_scene at all (no signal → assume protagonist)
        scene_has_child = (
            "child" in scene_role_types or
            (child_name and _name_in(scene_text_blob, child_name)) or
            (not scene_role_types)
        )
        if scene_has_child:
            out["child_ref"] = {
                "url":  child_asset["generated_image_url"],
                "name": child_name or "child",
                "type": "child",
            }
            out["injected_count"] += 1
        else:
            out["skipped_reasons"].append({
                "kind": "child", "id": None, "name": child_name or "child",
                "reason": "scene_not_relevant",
            })
    else:
        # Asset not generated yet — silent (don't pollute storyboard with noise).
        pass

    # ---- Extra-character references -----------------------------------------
    profiles_by_id = await _load_character_profiles(order_id, plan_id)

    extra_assets = await _load_extra_assets(order_id)

    # Surface availability summary regardless of relevance.
    for a in extra_assets:
        out["available"]["extras"].append({
            "character_index": a.get("character_index"),
            "character_id":    None,  # filled below if matched to a profile
            "name":            a.get("character_name") or "",
            "type":            a.get("character_type") or "",
        })

    relevant: list[dict] = []
    seen_keys: set[str] = set()

    # Index into data.characters by position (character_index aligns with order).
    chars_by_index = {i: c for i, c in enumerate(chars)}

    # Index profiles by lowercased type (first profile per type wins, mirrors build_docs).
    profiles_by_type: dict[str, dict] = {}
    for p in profiles_by_id.values():
        t = (p.get("type") or "").strip().lower()
        if t and t not in profiles_by_type:
            profiles_by_type[t] = p

    for asset in extra_assets:
        idx = asset.get("character_index")
        ctype = (asset.get("character_type") or "").strip().lower()
        cname = (asset.get("character_name") or "").strip()
        char_meta = chars_by_index.get(idx) or {}

        # Match strategy:
        #   * by character type (most reliable — production planner stores `role_in_scene` = type)
        #   * by character name (fallback — only when scene text mentions name)
        type_match = bool(ctype) and ctype in scene_role_types
        # exclude "child" — that's handled separately above
        if ctype == "child":
            type_match = False
        name_match = bool(cname) and _name_in(scene_text_blob, cname)
        is_present = type_match or name_match

        # Resolve character_id for storyboard linking
        prof = profiles_by_type.get(ctype) if ctype else None
        char_id = (prof or {}).get("id")

        if not is_present:
            out["skipped_reasons"].append({
                "kind": "extra",
                "id": char_id,
                "character_index": idx,
                "name": cname or ctype or f"#{idx}",
                "reason": "scene_not_relevant",
            })
            continue

        if not asset.get("generated_image_url"):
            out["skipped_reasons"].append({
                "kind": "extra",
                "id": char_id,
                "character_index": idx,
                "name": cname or ctype or f"#{idx}",
                "reason": "missing_asset",
            })
            continue

        key = char_id or f"idx:{idx}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        relevant.append({
            "url":              asset["generated_image_url"],
            "name":             cname or (char_meta.get("name") or ctype),
            "type":             ctype,
            "character_id":     char_id,
            "character_index":  idx,
        })

    # Apply MAX_EXTRA_REFS cap with a granular reason.
    if len(relevant) > MAX_EXTRA_REFS:
        for trimmed in relevant[MAX_EXTRA_REFS:]:
            out["skipped_reasons"].append({
                "kind": "extra",
                "id": trimmed.get("character_id"),
                "character_index": trimmed.get("character_index"),
                "name": trimmed.get("name"),
                "reason": "too_many_references_trimmed",
            })
        relevant = relevant[:MAX_EXTRA_REFS]

    out["extra_char_refs"] = relevant
    out["injected_count"] += len(relevant)

    # ---- Toy / object reference ---------------------------------------------
    toy_url   = pers.get("toy_image_url") or ""
    toy_desc  = pers.get("toy_description_auto") or ""
    toy_name  = (((pers.get("favorites") or {}).get("toy") or {}).get("name") or "").strip()
    out["available"]["toy"] = bool(toy_url)
    if toy_url:
        toy_relevant = (
            (toy_name and any(_name_in(o, toy_name) for o in scene_objects)) or
            (toy_name and _name_in(scene_text_blob, toy_name)) or
            # No toy name supplied — accept when scene declares any key_objects.
            (not toy_name and bool(scene_objects))
        )
        if toy_relevant:
            out["toy_ref"] = {
                "url":         toy_url,
                "name":        toy_name or "object",
                "description": toy_desc,
            }
            out["injected_count"] += 1
        else:
            out["skipped_reasons"].append({
                "kind": "toy",
                "id": None,
                "name": toy_name or "toy",
                "reason": "scene_not_relevant",
            })

    # ---- Text augmentation (used for all providers as a baseline) -----------
    aug_lines: list[str] = []
    if out["child_ref"]:
        aug_lines.append(
            f"CHILD reference (image attached): keep {out['child_ref']['name']}'s face, "
            "hair and outfit consistent across scenes."
        )
    if out["extra_char_refs"]:
        names = ", ".join(c["name"] or c.get("type") or "" for c in out["extra_char_refs"])
        aug_lines.append(
            f"EXTRA CHARACTER reference(s) attached for: {names}. "
            "Keep their faces and outfits consistent."
        )
    if out["toy_ref"]:
        toy = out["toy_ref"]
        bits = [f"TOY/OBJECT reference (image attached) — {toy['name']}"]
        if toy.get("description"):
            bits.append(f"described as: {toy['description']}")
        bits.append("show this exact object whenever the scene calls for it.")
        aug_lines.append(". ".join(bits) + ".")
    out["prompt_augmentation"] = " ".join(aug_lines)

    return out
