"""House style, dialects and shot pacing for the shot-based video engine.

The values come from the M1 lab spike that the owner approved (the two sample
videos' look: a new animated 16:9 shot every ~5 s, one narration line per shot,
a warm native-dialect narrator). They live here until the admin "style presets"
and "dialect profiles" pages (M3) move them into the database.

Since M3 these are the code defaults: services/engine_config.py seeds them into
the database once and generation reads the admin-edited copies from there.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

# --- Visual style -------------------------------------------------------------
# The owner's approved look (2026-10-24): the soft cartoon of their GPT Image 1.5
# results, reproduced with GPT Image 2 + a neutral style reference image.
STYLE = (
    "Clearly CARTOON 2D children's storybook illustration — not semi-realistic, not a painted portrait, not a photo "
    "filter: simplified rounded shapes, big expressive eyes with simple highlights, small simplified noses, smooth "
    "simplified skin with no realistic texture, soft cute storybook proportions (adults keep natural body proportions, "
    "never big-head caricatures). Premium children's book animation look: clean elegant linework, soft simplified "
    "painterly shading, warm appealing colors, charming and hand-crafted."
)
FRAME_RULES = (
    "Full-bleed 16:9 cinematic frame filling the whole canvas edge to edge: no border, no white margin, "
    "no vignette, no text, no letters, no watermark."
)
SHEET_RULES = (
    "ONE single full-body standing view of the character only, centered, natural relaxed pose (front-facing or slight "
    "3/4 view), fully visible from head to toe including the feet, arms and hands clearly separated from the body, clean "
    "silhouette, nothing cropped. Plain pure white background (opaque white — not transparent, no checkerboard), no "
    "props, no scenery, no other characters, no text."
)
SHEET_SIZE = "1024x1536"  # one tall figure: the face gets the pixels it needs for likeness

# Image quality per stage. Shot keyframes went to medium on 2026-10-24 (it looked
# the same in a one-scene bake-off), but in the first full story the owner saw
# flatter faces and simpler eyes than the earlier high-quality story — and every
# Kling clip inherits its keyframe's faces — so keyframes are back at high
# (owner, 2026-10-25). Character sheets were always high.
IMAGE_QUALITY = {
    "scene_image_generation": "high",
    "book_page_image_generation": "medium",
}


def image_quality(stage: str, mapping: dict | None = None) -> str:
    return (mapping if mapping is not None else IMAGE_QUALITY).get(stage, "high")

# Neutral style reference: made-up characters drawn in the house style (never a
# customer's child). Character sheets get it as image 2 so every face in every
# story lands in the same style.
STYLE_REF_PATH = Path(__file__).resolve().parent.parent / "assets" / "styles" / "storybook_soft.png"
STYLE_REF_NOTE = ("The last reference image is a STYLE reference only: copy its art style, linework, shading, colors "
                  "and level of cartoon simplification exactly, but never its characters, faces, hair or clothes.")


@lru_cache(maxsize=1)
def style_reference() -> bytes | None:
    try:
        return STYLE_REF_PATH.read_bytes()
    except OSError:
        return None


_SAME_AS_PHOTO = ("same as photo", "same as in the photo", "as in the photo", "from the photo", "photo outfit")


def outfit_rule(outfit: str | None) -> str:
    """Keep the photo's outfit (what makes a child recognisable to their parents)
    unless the story needs specific clothes."""
    o = (outfit or "").strip()
    if not o or any(k in o.lower() for k in _SAME_AS_PHOTO):
        # Parents upload holiday and sports photos: the person's own clothes carry
        # over, the gear of the moment (life jacket, harness, helmet) doesn't.
        return ("dress the character in the person's own everyday clothes from the photo, with the same colors and "
                "details. If the photo shows formal or office wear (a suit, a blazer or a tie), draw simple casual "
                "clothes in similar colors instead, with no tie. Leave out activity and safety gear such as life "
                "jackets, harnesses, straps, helmets, goggles or ski wear, and anything the person is holding. If the "
                "feet are bare, add simple shoes that match the outfit")
    return f"dress the character in {o}"


# Photo → character rules for every sheet drawn from a real photo (parents upload
# all kinds of photos: black-and-white, filtered, cropped, group shots).
PHOTO_RULES = (
    "PHOTO: use only the main person (the largest, most central face). If the photo is black-and-white, sepia, tinted "
    "or filtered, draw everything in full natural color — a warm natural skin tone, natural hair color (dark hair stays "
    "dark), natural eye color, never gray. If the photo is cropped, complete the full body with natural proportions for "
    "the age. Ignore the background, props, stickers, filters and text."
)
IDENTITY_RULES = (
    "IDENTITY (most important): keep the exact face shape, the same hairstyle with the same hair volume, texture and "
    "flow (do not tidy, shorten or straighten the hair), eyebrow shape, eye shape and eye color, nose, smile, cheeks "
    "(keep rosy cheeks if present), ears, skin tone, age and overall expression. If present, keep glasses, a hijab, a "
    "beard or a moustache exactly (same shape and fullness), simplified into the cartoon style."
)


def character_sheet_prompt(who: str, outfit: str | None = None, style_text: str | None = None,
                           sheet_rules: str | None = None) -> str:
    """Photo → cartoon character sheet (the owner's proven prompt, fixed: opaque
    white instead of transparent, photo rules, photo outfit by default, one view)."""
    return (
        f"Create a highly stylized 2D children's storybook cartoon character based on the uploaded photo of {who}, "
        "more cartoonish than the photo while keeping the person instantly recognizable to their own family. "
        "The first reference image is the photo (use it ONLY for identity). "
        f"{STYLE_REF_NOTE}\n\n{IDENTITY_RULES}\n\n{PHOTO_RULES}\n\nOUTFIT: {outfit_rule(outfit)}.\n\n"
        f"STYLE: {style_text or STYLE}\n\nCOMPOSITION: {sheet_rules or SHEET_RULES}"
    )


MOTION_STYLE = "Keep the 2D storybook animation style and the characters' faces and outfits unchanged."
VIDEO_NEGATIVE = (
    "photorealistic, live action, 3D render, morphing face, changing identity, extra fingers, extra limbs, "
    "distorted hands, text, subtitles, watermark, blur, flicker, low quality"
)
# The plan's style_guide no longer comes from the LLM; every story uses this.
STYLE_GUIDE = {
    "art_direction": STYLE,
    "palette": "warm appealing colors",
    "lighting": "soft warm storybook lighting",
}

# --- Pacing -------------------------------------------------------------------
# Measured on the reference videos: ~1.95 spoken words/s, a new shot every ~5 s.
WORDS_PER_SECOND = 1.9
SHOT_SECONDS = 5
SHOT_TYPES = ["wide", "medium", "close-up", "insert", "over-the-shoulder", "back view"]
# Kling v3 clip length bounds (seconds).
CLIP_MIN_SEC, CLIP_MAX_SEC = 3, 15
# Silence kept after each narration line before the next shot.
LINE_GAP_SEC = 0.35
# Extra time on the very last shot so the story doesn't end mid-breath.
END_TAIL_SEC = 1.2


def shot_counts(duration_seconds: int, scene_count: int, shot_seconds: float | None = None) -> list[int]:
    """Shots per scene for a story length: ~one shot per 5 s, at least 2 per scene."""
    total = max(scene_count * 2, round(duration_seconds / (shot_seconds or SHOT_SECONDS)))
    base, extra = divmod(total, scene_count)
    # Give the remainder to the middle of the story (the problem / turning point).
    order = sorted(range(scene_count), key=lambda i: abs(i - (scene_count - 1) / 2))
    counts = [base] * scene_count
    for i in order[:extra]:
        counts[i] += 1
    return counts


def max_line_words(shot_seconds: float | None = None, words_per_second: float | None = None) -> int:
    return math.floor((shot_seconds or SHOT_SECONDS) * (words_per_second or WORDS_PER_SECOND)) + 1


def clip_seconds(narration_seconds: float, line_gap: float | None = None) -> int:
    """Kling clip length that covers a narration line plus its gap (never a held frame)."""
    need = narration_seconds + (LINE_GAP_SEC if line_gap is None else line_gap) + 0.15
    return int(min(CLIP_MAX_SEC, max(CLIP_MIN_SEC, math.ceil(need))))


# Kling 2.x clips come only as 5 or 10 s. A 5 s clip may be slowed this much to
# cover a slightly longer line (gentle slow motion still moves) before we pay for 10 s.
FIVE_SECOND_STRETCH = 1.2


def clip_seconds_for(model: str, narration_seconds: float, line_gap: float | None = None,
                     five_second_stretch: float | None = None) -> int:
    """Clip length to request from a given video model for a narration line."""
    gap = LINE_GAP_SEC if line_gap is None else line_gap
    if "/v3/" in model:
        return clip_seconds(narration_seconds, gap)  # any length 3–15 s
    need = narration_seconds + gap + 0.15
    return 5 if need <= 5 * (five_second_stretch or FIVE_SECOND_STRETCH) else 10


# --- Dialects -----------------------------------------------------------------
# tts_direction stays one short line: Gemini TTS reads long instructions aloud.
# key = story_options(kind=language).value chosen by the parent.
DIALECTS: dict[str, dict] = {
    "egyptian": {
        "name_ar": "مصري",
        "writing": (
            "اكتب كل narration_line باللهجة المصرية العامية الطبيعية الموجّهة للأطفال (مثل: بيجروا، أوي، سوا، "
            "بصّ، قرّب، الأوضة، ماما، بابا)، جمل قصيرة دافئة. لا تخلط بالفصحى. ضع الشدّة والتشكيل على أي كلمة "
            "يمكن أن تُنطق خطأ (مثل: بصّت، قرّبت، طفّت)."
        ),
        "tts_direction": "Read aloud in a warm, gentle Egyptian Arabic storyteller voice for young children:",
        "voices": {"male": "Algieba", "female": "Sulafat"},
    },
    "gulf": {
        "name_ar": "سعودي / خليجي",
        "writing": (
            "اكتب كل narration_line باللهجة السعودية (نجدية/حجازية خفيفة مفهومة لكل الخليج) الموجّهة للأطفال "
            "(مثل: شوي، وش، يبي، زين، مره، الغرفة، أمه، أبوه)، جمل قصيرة دافئة. لا تخلط بالمصرية أو الشامية. "
            "ضع التشكيل على أي كلمة يمكن أن تُنطق خطأ."
        ),
        "tts_direction": "Read aloud in a warm, gentle Saudi Arabic storyteller voice for young children:",
        "voices": {"male": "Algieba", "female": "Sulafat"},
    },
    "msa": {
        "name_ar": "فصحى مبسطة",
        "writing": (
            "اكتب كل narration_line بالعربية الفصحى المبسّطة المناسبة للأطفال، جمل قصيرة دافئة، مع تشكيل كامل "
            "لأواخر الكلمات وأي كلمة قد تُنطق خطأ."
        ),
        "tts_direction": "Read aloud in a warm, gentle Modern Standard Arabic storyteller voice for young children:",
        "voices": {"male": "Algieba", "female": "Sulafat"},
    },
}
DEFAULT_DIALECT = "msa"
_OPTION_TO_DIALECT = {"egyptian": "egyptian", "gulf": "gulf", "saudi": "gulf", "arabic-simple": "msa", "msa": "msa"}


async def dialect_for_order(order: dict) -> str:
    """Dialect key from the parent's language option (story_options kind=language)."""
    from db import db

    option_id = ((order.get("data") or {}).get("style") or {}).get("language_id")
    if not option_id:
        return DEFAULT_DIALECT
    option = await db.story_options.find_one({"id": option_id}, {"_id": 0, "value": 1})
    value = (option or {}).get("value")
    # Known aliases map to the launch dialects; any other value is taken as the
    # key of an admin-added dialect profile (engine_config.get_dialect falls back to MSA).
    return _OPTION_TO_DIALECT.get(value) or value or DEFAULT_DIALECT


async def narrator_for_order(order: dict) -> str:
    """'male' or 'female' narrator: the parent's voice option (boy/girl), else the child's gender."""
    from db import db

    data = order.get("data") or {}
    option_id = (data.get("style") or {}).get("voice_id")
    option = await db.story_options.find_one({"id": option_id}, {"_id": 0, "value": 1}) if option_id else None
    value = (option or {}).get("value")
    if value == "boy":
        return "male"
    if value == "girl":
        return "female"
    return "male" if (data.get("child") or {}).get("gender") == "male" else "female"
