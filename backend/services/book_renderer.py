"""Magazine-style picture book: HTML/CSS laid out per page, printed to PDF by a
headless Chromium (Edge on Windows, Chromium/Chrome on the server).

Why a browser: Arabic shaping, diacritics, RTL line breaking, gradients,
masks, rounded photo frames and real fonts come for free, and the layout lives
in templates/book.html where it can be restyled without touching Python.
If no browser is installed, render_book_pdf returns None and the caller falls
back to the plain ReportLab book.

Pages: cover (full-bleed art + title) · story heroes (character portraits from
their sheets) · one page per book page in three rotating layouts (hero / split
/ collage, using the scene's shot keyframes) · a "hero of the story"
certificate · back cover. Accent colours are taken from the cover art so every
book matches its own illustrations.
"""
from __future__ import annotations

import asyncio
import colorsys
import glob
import io
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from db import db
from services import house_style

logger = logging.getLogger("book_renderer")

BACKEND = Path(__file__).resolve().parent.parent
TEMPLATES = BACKEND / "templates"
FONTS = {"baloo_semibold": BACKEND / "assets" / "fonts" / "BalooBhaijaan2-SemiBold.ttf",
         "baloo_bold": BACKEND / "assets" / "fonts" / "BalooBhaijaan2-Bold.ttf",
         "baloo_extrabold": BACKEND / "assets" / "fonts" / "BalooBhaijaan2-ExtraBold.ttf",
         "amiri": BACKEND / "fonts" / "Amiri-Regular.ttf",
         "amiri_bold": BACKEND / "fonts" / "Amiri-Bold.ttf"}
LOGO = BACKEND / "assets" / "brand" / "gheras-logo.png"
LAYOUTS = ["hero", "split", "collage", "band"]
ROLE_AR = {"child": ("البطل", "البطلة"), "father": "بابا", "mother": "ماما", "brother": "الأخ", "sister": "الأخت",
           "grandfather": "جدو", "grandmother": "تيتة", "friend": "الصديق", "teacher": "المعلّم",
           "other": "صديق الحكاية"}
AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


# ---------------------------------------------------------------- browser
def find_browser() -> str | None:
    """PDF_BROWSER env, else Edge/Chrome/Chromium in the usual places (incl. Playwright's)."""
    env = os.environ.get("PDF_BROWSER")
    if env and os.path.exists(env):
        return env
    if platform.system() == "Windows":
        candidates = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                      r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                      r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
        candidates += sorted(glob.glob(r"D:\DevData\ms-playwright\chromium-*\chrome-win\chrome.exe"), reverse=True)
    else:
        candidates = [shutil.which(n) for n in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")]
        candidates += sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux/chrome")),
                             reverse=True)
    return next((c for c in candidates if c and os.path.exists(c)), None)


def _print_pdf(browser: str, html: Path, out: Path) -> None:
    args = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--hide-scrollbars", "--no-pdf-header-footer", "--allow-file-access-from-files",
            "--virtual-time-budget=20000", f"--user-data-dir={html.parent / 'profile'}",
            f"--print-to-pdf={out}", html.as_uri()]
    if platform.system() != "Windows":
        args.insert(1, "--no-sandbox")  # the service runs as root on the VPS
    subprocess.run(args, check=True, timeout=180, capture_output=True)
    if not out.exists() or out.stat().st_size < 1000:
        raise RuntimeError("browser produced no PDF")


# ---------------------------------------------------------------- assets
async def _bytes_of(url: str | None) -> bytes | None:
    if not url:
        return None
    from services.child_character_service import _fetch_source_bytes
    got = await _fetch_source_bytes(url)
    return got[0] if got else None


def _save_jpeg(data: bytes, path: Path, max_side: int = 2000) -> str:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((max_side, max_side))
    img.save(path, format="JPEG", quality=86, optimize=True)
    return path.name


def _palette(cover: bytes | None) -> dict:
    """Three lively accents + a deep ink colour from the cover art."""
    fallback = {"accent": "#E8743B", "accent2": "#7A5BD6", "accent3": "#2FA4A0", "deep": "#3A2A5C", "soft": "#F6D9C4"}
    if not cover:
        return fallback
    img = Image.open(io.BytesIO(cover)).convert("RGB").resize((96, 54))
    colors = img.quantize(colors=12, method=Image.Quantize.MEDIANCUT).convert("RGB").getcolors(96 * 54) or []
    scored = []
    for count, (r, g, b) in colors:
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s < .28 or v < .35:
            continue
        scored.append((s * v * (count ** .35), h, s, v))
    picks: list[tuple[float, float, float]] = []
    for _score, h, s, v in sorted(scored, reverse=True):
        if all(min(abs(h - ph), 1 - abs(h - ph)) > .09 for ph, _, _ in picks):
            picks.append((h, s, v))
        if len(picks) == 3:
            break

    def hexify(h, s, v):
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return "#%02X%02X%02X" % (int(r * 255), int(g * 255), int(b * 255))

    if not picks:
        return fallback
    while len(picks) < 3:  # complementary fill-ins
        h, s, v = picks[-1]
        picks.append(((h + .38) % 1, max(s, .5), min(v, .8)))
    # Accents strong enough for white text on them; deep = darkest version of the first hue.
    acc = [hexify(h, min(max(s, .62), .9), min(max(v, .62), .84)) for h, s, v in picks]
    h0, s0, _ = picks[0]
    return {"accent": acc[0], "accent2": acc[1], "accent3": acc[2],
            "deep": hexify(h0, min(.75, s0 + .1), .32), "soft": hexify(h0, .18, .98)}


PEOPLE = {"child", "father", "mother", "brother", "sister", "grandfather", "grandmother", "friend", "teacher"}
# Head and shoulders = this share of the figure's height. The old crop was as wide as the
# figure, so a slim child under a big helmet was cut at the chin.
PORTRAIT_SHARE = 0.44


async def tashkeel_on() -> bool:
    s = await db.settings.find_one({"key": "book.tashkeel"}, {"_id": 0, "value": 1})
    return (s or {}).get("value") is True


def _portrait(data: bytes, kind: str, path: Path) -> str:
    """Square portrait cut from a character sheet (figure on plain white):
    head and shoulders for people, the whole figure for animals and toys."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    gray = img.convert("L").point(lambda v: 255 if v < 238 else 0)
    box = gray.getbbox() or (0, 0, img.width, img.height)
    left, top, right, bottom = box
    w, h = right - left, bottom - top
    if kind in PEOPLE:
        # The head sits in the top band of the figure; centre on what's drawn there.
        band = gray.crop((left, top, right, top + max(1, int(h * .22)))).getbbox()
        cx = left + ((band[0] + band[2]) / 2 if band else w / 2)
        side = max(h * PORTRAIT_SHARE, 1)
        crop = (cx - side / 2, top - side * .05, cx + side / 2, top + side * .95)
    else:
        side = max(w, h) * 1.08
        cx, cy = left + w / 2, top + h / 2
        crop = (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
    # Paste only the part inside the sheet, so a crop reaching past its edge stays white.
    x0, y0, x1, y1 = (int(v) for v in crop)
    canvas = Image.new("RGB", (x1 - x0, y1 - y0), "white")
    inside = (max(x0, 0), max(y0, 0), min(x1, img.width), min(y1, img.height))
    canvas.paste(img.crop(inside), (inside[0] - x0, inside[1] - y0))
    canvas.thumbnail((700, 700))
    canvas.save(path, format="JPEG", quality=88)
    return path.name


def _text_size(longest: int) -> int:
    return 25 if longest <= 140 else 23 if longest <= 200 else 21 if longest <= 260 else 19


# ---------------------------------------------------------------- data
async def _book_data(order_id: str, plan: dict, cover_url: str | None, book_assets, work: Path) -> dict:
    from services.shot_pipeline import _profiles, load_character_sheets

    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    data = order.get("data") or {}
    child = data.get("child") or {}
    female = child.get("gender") == "female"
    img_dir = work / "img"
    img_dir.mkdir(exist_ok=True)

    cover_bytes = await _bytes_of(cover_url)
    cover = f"img/{_save_jpeg(cover_bytes, img_dir / 'cover.jpg', 2400)}" if cover_bytes else None

    # Each book page gets its scene's shot keyframes (hero first), else its illustration.
    scenes = {s["scene_index"]: s for s in await db.scene_plans.find(
        {"production_plan_id": plan["id"]}, {"_id": 0, "scene_index": 1, "title": 1}).to_list(50)}
    shots: dict[int, list[str]] = {}
    async for r in db.shot_assets.find({"production_plan_id": plan["id"], "keyframe_url": {"$ne": None}},
                                       {"_id": 0, "scene_index": 1, "shot_index": 1, "keyframe_url": 1}
                                       ).sort([("scene_index", 1), ("shot_index", 1)]):
        shots.setdefault(r["scene_index"], []).append(r["keyframe_url"])

    # Fully vowelled text only when the admin turns it on (owner: not needed, it costs money).
    vowelled = {}
    if await tashkeel_on():
        from services.tashkeel_service import vowelled_pages
        vowelled = await vowelled_pages([ba for ba in book_assets if ba.get("id")])

    pages, strip, longest = [], [], 0
    for i, ba in enumerate(sorted(book_assets, key=lambda b: int(b.get("page_number") or 0))):
        scene_index = ba.get("scene_index") or ba.get("page_number")
        urls = shots.get(scene_index) or ([ba["illustration_url"]] if ba.get("illustration_url") else [])
        images = []
        for j, u in enumerate(urls[:3]):
            b = await _bytes_of(u)
            if b:
                images.append(f"img/{_save_jpeg(b, img_dir / f'p{i}_{j}.jpg')}")
        if not images and cover:
            images = [cover]
        strip.extend(images[:1])
        text = vowelled.get(ba.get("id")) or (ba.get("page_text") or "").strip()
        # Line length is judged on the letters, not the vowel marks.
        from services.tashkeel_service import strip_marks
        longest = max(longest, len(strip_marks(text)))
        first, _, rest = text.partition(" ")
        number = i + 1
        pages.append({"layout": LAYOUTS[i % len(LAYOUTS)], "images": images,
                      "title": (scenes.get(scene_index) or {}).get("title") or "",
                      "first_word": first, "rest": rest,
                      "number_ar": str(number).translate(AR_DIGITS),
                      "page_ar": str(number + 2).translate(AR_DIGITS)})

    # Story heroes: portraits cut from the character sheets (child first).
    sheets = await load_character_sheets(order, plan)
    profiles = await _profiles(plan)
    cast = []
    for t in sorted(sheets, key=lambda t: (t != "child", t))[:4]:
        b = await _bytes_of(sheets[t]["url"])
        if not b:
            continue
        name = (profiles.get(t) or {}).get("name") or (child.get("name") if t == "child" else "")
        role = ROLE_AR.get(house_style.base_type(t), ROLE_AR["other"])
        role = role[1 if female else 0] if isinstance(role, tuple) else role
        cast.append({"image": f"img/{_portrait(b, house_style.base_type(t), img_dir / f'cast_{t}.jpg')}",
                     "name": name or role,
                     "role": role, "type": t})

    enriched = order.get("enriched") or {}
    goal = data.get("goal") or {}
    category = await db.categories.find_one({"id": goal.get("category_id")}, {"_id": 0, "slug": 1}) \
        if goal.get("category_id") else None
    # The ambition topics are roles (a doctor, a policeman), not values: "learned
    # the meaning of policeman" read wrong on the first real story's certificate.
    role = enriched.get("subcategory_name") if (category or {}).get("slug") == "imagination" else None
    from datetime import datetime
    months = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
    now = datetime.now()
    date_ar = f"{str(now.day).translate(AR_DIGITS)} {months[now.month - 1]} {str(now.year).translate(AR_DIGITS)}"
    if LOGO.exists():
        shutil.copy(LOGO, work / "logo.png")
    fonts_dir = work / "fonts"
    fonts_dir.mkdir(exist_ok=True)
    fonts = {}
    for key, src in FONTS.items():
        if src.exists():
            shutil.copy(src, fonts_dir / src.name)
            fonts[key] = f"fonts/{src.name}"
    return {
        "title": plan.get("title") or "حكاية من غِراس",
        "child": {"name": child.get("name") or "", "female": female},
        "summary": (plan.get("story_summary") or "").split("\n")[0],
        "lesson": plan.get("main_message") or "",
        # A topic the parent typed is a sentence, not a value name: the certificate
        # then gives the lesson alone instead of the broad category.
        "role": role,
        "value": None if role else enriched.get("subcategory_name") or (
            None if (data.get("goal") or {}).get("custom_subcategory")
            else enriched.get("category_name") or "القيم الجميلة"),
        "cover": cover, "logo": "logo.png" if LOGO.exists() else None,
        "pages": pages, "cast": cast, "strip": (strip + ([cover] if cover else []))[:5],
        "palette": _palette(cover_bytes), "text_size": _text_size(longest), "fonts": fonts,
        "child_portrait": next((c for c in cast if c["type"] == "child"), None), "date_ar": date_ar,
    }


# ---------------------------------------------------------------- entry
async def render_book_pdf(order_id: str, plan: dict, cover_url: str | None, book_assets) -> tuple[bytes, dict] | None:
    """(pdf_bytes, meta), or None when no headless browser is available."""
    browser = find_browser()
    if not browser:
        logger.warning("[book] no headless browser found (set PDF_BROWSER) — falling back to ReportLab")
        return None
    from services.shot_pipeline import work_dir

    work = Path(work_dir(f"book-{order_id[:8]}-"))
    try:
        ctx = await _book_data(order_id, plan, cover_url, book_assets, work)
        env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
        html = work / "book.html"
        html.write_text(env.get_template("book.html").render(**ctx), encoding="utf-8")
        out = work / "book.pdf"
        await asyncio.to_thread(_print_pdf, browser, html, out)
        pdf = out.read_bytes()
        from pypdf import PdfReader
        page_count = len(PdfReader(io.BytesIO(pdf)).pages)
        return pdf, {"renderer": "html-chromium", "browser": os.path.basename(browser), "pages": page_count,
                     "layouts": [p["layout"] for p in ctx["pages"]], "palette": ctx["palette"],
                     "cast": [c["name"] for c in ctx["cast"]]}
    finally:
        if not os.environ.get("BOOK_KEEP_WORKDIR"):
            shutil.rmtree(work, ignore_errors=True)
