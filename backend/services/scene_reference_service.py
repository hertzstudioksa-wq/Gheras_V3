"""Scene Reference Service — Phase E.

Resolves which existing reference assets (child portrait, extra characters,
toy/object) are RELEVANT to a given scene and assembles them into a structured
package that the scene_image_generation step can consume.

Relevance rules (Phase E):
  * child reference        → injected if available in EVERY scene where the
    child's name is referenced OR scene's `present_characters` includes a
    child marker. Falls back to "always inject when child reference exists"
    if neither hint is present.
  * extra-character refs   → injected for scenes whose `present_characters`
    explicitly names that character. Cap: max 2 per scene.
  * toy / object reference → injected when the toy name appears in the
    scene's `key_objects` array OR in narration_text/image_prompt. Cap: 1.

Caps (per scene):
  child: 1, extras: 2, toy: 1   → max 4 reference images per scene call.

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


def _name_in(text: str, name: str) -> bool:
    if not text or not name:
        return False
    n = name.strip().lower()
    return bool(n) and n in (text or "").lower()


async def _load_child_asset(order_id: str) -> dict | None:
    return await db.child_character_assets.find_one(
        {"order_id": order_id, "is_active": {"$ne": False}, "generated_image_url": {"$ne": None}},
        {"_id": 0},
        sort=[("created_at", -1)],
    )


async def _load_extra_assets(order_id: str) -> list[dict]:
    rows = await db.extra_character_assets.find(
        {"order_id": order_id, "generated_image_url": {"$ne": None}},
        {"_id": 0},
    ).to_list(20)
    return rows


async def resolve_scene_references(order: dict, plan: dict, scene: dict) -> dict:
    """Compute which references should be attached to this scene's image call.

    Returns:
        {
          "child_ref":        {"url", "name"} | None,
          "extra_char_refs":  [{"url", "name", "character_id"} ...]   (≤ 2),
          "toy_ref":          {"url", "name", "description"} | None,
          "injected_count":   int,
          "available": {
              "child":   bool,
              "extras":  [character_id ...],
              "toy":     bool,
          },
          "skipped_reasons": [{"kind", "id", "reason"} ...],
          "prompt_augmentation": "...string to APPEND to the text prompt..."
        }
    """
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

    scene_present  = [str(x).strip() for x in (scene.get("present_characters") or [])]
    scene_objects  = [str(x).strip() for x in (scene.get("key_objects") or [])]
    scene_text_blob = " ".join(filter(None, [
        scene.get("image_prompt"), scene.get("narration_text"),
        scene.get("book_text"),   scene.get("scene_summary"),
    ]))

    # ---- Child reference -----------------------------------------------------
    child_asset = await _load_child_asset(order["id"])
    out["available"]["child"] = bool(child_asset)
    if child_asset:
        scene_has_child = (
            any(_name_in(p, child_name) for p in scene_present) or
            _name_in(scene_text_blob, child_name) or
            (not scene_present)  # missing hint → assume child appears
        )
        if scene_has_child:
            out["child_ref"] = {"url": child_asset["generated_image_url"], "name": child_name or "child"}
            out["injected_count"] += 1
        else:
            out["skipped_reasons"].append({"kind": "child", "reason": "child not present in this scene"})

    # ---- Extra-character references ----------------------------------------
    extra_assets = await _load_extra_assets(order["id"])
    by_char_id   = {a.get("character_id"): a for a in extra_assets}
    out["available"]["extras"] = list(by_char_id.keys())

    char_meta = {c.get("id"): c for c in chars if c.get("id")}
    relevant: list[tuple[dict, dict]] = []   # (char, asset)
    for cid, asset in by_char_id.items():
        meta = char_meta.get(cid) or {}
        cname = (meta.get("name") or asset.get("character_name") or "").strip()
        if not cname:
            continue
        present = (
            any(_name_in(p, cname) for p in scene_present) or
            _name_in(scene_text_blob, cname)
        )
        if present:
            relevant.append((meta, asset))
        else:
            out["skipped_reasons"].append({"kind": "extra", "id": cid,
                                            "reason": f"'{cname}' not present in this scene"})

    # Apply MAX_EXTRA_REFS cap.
    if len(relevant) > MAX_EXTRA_REFS:
        for meta, asset in relevant[MAX_EXTRA_REFS:]:
            out["skipped_reasons"].append({
                "kind": "extra", "id": meta.get("id"),
                "reason": f"capped (only {MAX_EXTRA_REFS} extras per scene)",
            })
        relevant = relevant[:MAX_EXTRA_REFS]

    for meta, asset in relevant:
        out["extra_char_refs"].append({
            "url":          asset["generated_image_url"],
            "name":         meta.get("name") or asset.get("character_name"),
            "character_id": meta.get("id"),
        })
    out["injected_count"] += len(out["extra_char_refs"])

    # ---- Toy / object reference ---------------------------------------------
    toy_url   = pers.get("toy_image_url") or ""
    toy_desc  = pers.get("toy_description_auto") or ""
    toy_name  = (((pers.get("favorites") or {}).get("toy") or {}).get("name") or "").strip()
    out["available"]["toy"] = bool(toy_url)
    if toy_url:
        toy_relevant = (
            (toy_name and any(_name_in(o, toy_name) for o in scene_objects)) or
            (toy_name and _name_in(scene_text_blob, toy_name)) or
            # If no name was supplied at all, accept the toy as relevant when
            # the scene mentions an object cue ("توي", "لعبة") OR has any
            # key_objects at all.
            (not toy_name and bool(scene_objects))
        )
        if toy_relevant and out["injected_count"] - len(out["extra_char_refs"]) < MAX_TOY_REFS:
            # MAX_TOY_REFS already 1; we keep the inequality for clarity.
            out["toy_ref"] = {"url": toy_url, "name": toy_name or "object", "description": toy_desc}
            out["injected_count"] += 1
        else:
            out["skipped_reasons"].append({
                "kind": "toy",
                "reason": "toy not present in this scene's key_objects" if not toy_relevant else "toy cap reached",
            })

    # ---- Text augmentation (used for all providers as a baseline) -----------
    aug_lines: list[str] = []
    if out["child_ref"]:
        aug_lines.append(f"CHILD reference (image attached): keep {out['child_ref']['name']}'s face, hair and outfit consistent across scenes.")
    if out["extra_char_refs"]:
        names = ", ".join(c["name"] for c in out["extra_char_refs"])
        aug_lines.append(f"EXTRA CHARACTER reference(s) attached for: {names}. Keep their faces and outfits consistent.")
    if out["toy_ref"]:
        toy = out["toy_ref"]
        bits = [f"TOY/OBJECT reference (image attached) — {toy['name']}"]
        if toy.get("description"):
            bits.append(f"described as: {toy['description']}")
        bits.append("show this exact object whenever the scene calls for it.")
        aug_lines.append(". ".join(bits) + ".")
    out["prompt_augmentation"] = " ".join(aug_lines)

    return out
