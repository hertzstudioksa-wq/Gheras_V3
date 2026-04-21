"""Final PDF assembly — ReportLab with Arabic RTL via arabic-reshaper + python-bidi.

Produces an A5-landscape-ish children's storybook PDF:
  * Cover page: cover image + title + story summary.
  * One page per scene (image on top, Arabic text below, page number).
  * Back page: "النهاية" with main_message.
"""
import asyncio
import io
import logging
import os
import uuid
from typing import Sequence

from PIL import Image
from reportlab.lib.pagesizes import A5, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

import arabic_reshaper
from bidi.algorithm import get_display

from db import db
from storage import put_object, get_object, APP_NAME

logger = logging.getLogger("pdf_assembly_service")


# Amiri — a proper Arabic typeface shipped with the app. Falls back to DejaVu only
# if Amiri cannot be found (should never happen in production).
_BUNDLED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
AMIRI_REGULAR = os.path.join(_BUNDLED_DIR, "Amiri-Regular.ttf")
AMIRI_BOLD = os.path.join(_BUNDLED_DIR, "Amiri-Bold.ttf")

ARABIC_FONT_NAME = "GherasAr"
ARABIC_FONT_BOLD = "GherasAr-Bold"
_FONT_REGISTERED = False


def _ensure_font():
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    regular_candidates = [
        AMIRI_REGULAR,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    bold_candidates = [
        AMIRI_BOLD,
        AMIRI_REGULAR,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    reg = next((p for p in regular_candidates if os.path.exists(p)), None)
    bold = next((p for p in bold_candidates if os.path.exists(p)), None)
    if not reg:
        raise RuntimeError("No usable TTF font found on system for Arabic PDF")
    pdfmetrics.registerFont(TTFont(ARABIC_FONT_NAME, reg))
    if bold and bold != reg:
        pdfmetrics.registerFont(TTFont(ARABIC_FONT_BOLD, bold))
    else:
        pdfmetrics.registerFont(TTFont(ARABIC_FONT_BOLD, reg))
    _FONT_REGISTERED = True


def _shape_ar(text: str) -> str:
    if not text:
        return ""
    reshaped = arabic_reshaper.reshape(str(text))
    return get_display(reshaped)


async def _fetch_file_bytes(file_id: str) -> bytes | None:
    rec = await db.files.find_one({"id": file_id}, {"_id": 0})
    if not rec:
        return None
    sp = rec.get("storage_path")
    if not sp:
        return None
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: get_object(sp))
    if isinstance(result, tuple):
        return result[0]
    return result


def _file_id_from_url(url: str) -> str | None:
    if not url:
        return None
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else None


def _draw_wrapped_ar(c: canvas.Canvas, text: str, x: float, y: float, width: float, font_size: int, leading: float) -> float:
    """Draw Arabic text wrapped within `width`. Returns final y after drawing."""
    if not text:
        return y
    c.setFont(ARABIC_FONT_NAME, font_size)
    # Split into lines that fit
    words = str(text).split()
    lines: list[str] = []
    current = ""
    for w in words:
        attempt = (current + " " + w).strip()
        shaped = _shape_ar(attempt)
        if c.stringWidth(shaped, ARABIC_FONT_NAME, font_size) <= width:
            current = attempt
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    for line in lines:
        shaped = _shape_ar(line)
        # Right-aligned since Arabic RTL
        line_width = c.stringWidth(shaped, ARABIC_FONT_NAME, font_size)
        c.drawString(x + width - line_width, y, shaped)
        y -= leading
    return y


def _draw_image_fit(c: canvas.Canvas, img_bytes: bytes, x: float, y: float, box_w: float, box_h: float):
    """Draw an image centered in a box, preserving aspect ratio."""
    try:
        img = Image.open(io.BytesIO(img_bytes))
        iw, ih = img.size
        ratio = min(box_w / iw, box_h / ih)
        dw, dh = iw * ratio, ih * ratio
        cx = x + (box_w - dw) / 2
        cy = y + (box_h - dh) / 2
        # ReportLab wants a temp file or an ImageReader; use ImageReader via BytesIO
        from reportlab.lib.utils import ImageReader
        c.drawImage(ImageReader(io.BytesIO(img_bytes)), cx, cy, width=dw, height=dh,
                    preserveAspectRatio=True, mask="auto")
    except Exception as e:
        logger.warning(f"Failed to draw image: {e}")


async def assemble_pdf(
    order_id: str,
    plan: dict,
    cover_image_url: str | None,
    book_assets: Sequence[dict],
) -> tuple[str, int, dict]:
    """
    Returns (pdf_url, page_count, metadata).
    book_assets: book_assets rows sorted by page_number.
    """
    _ensure_font()

    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "user_id": 1})
    user_id = (order or {}).get("user_id")

    # Load image bytes upfront
    cover_bytes = None
    if cover_image_url:
        fid = _file_id_from_url(cover_image_url)
        if fid:
            cover_bytes = await _fetch_file_bytes(fid)

    page_images: list[tuple[dict, bytes | None]] = []
    for ba in book_assets:
        fid = _file_id_from_url(ba.get("illustration_url"))
        img = await _fetch_file_bytes(fid) if fid else None
        page_images.append((ba, img))

    # A5 landscape: 210mm x 148mm
    page_w, page_h = landscape(A5)
    margin = 14 * mm

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.setTitle(plan.get("title") or "قصة غراس")

    # ---- Cover page ----
    # Full image fills most of the page, title overlay below
    if cover_bytes:
        _draw_image_fit(c, cover_bytes, margin, margin + 25 * mm, page_w - 2 * margin, page_h - 2 * margin - 25 * mm)
    # Title at bottom
    title = plan.get("title") or ""
    c.setFont(ARABIC_FONT_BOLD, 22)
    shaped = _shape_ar(title)
    tw = c.stringWidth(shaped, ARABIC_FONT_BOLD, 22)
    c.drawString((page_w - tw) / 2, margin + 12 * mm, shaped)
    # Small brand tag
    c.setFont(ARABIC_FONT_NAME, 9)
    brand = _shape_ar("من إعداد غِراس")
    bw = c.stringWidth(brand, ARABIC_FONT_NAME, 9)
    c.drawString((page_w - bw) / 2, margin + 4 * mm, brand)
    c.showPage()

    # ---- Story pages ----
    pages_drawn = 0
    for ba, img_bytes in page_images:
        page_number = int(ba.get("page_number") or (pages_drawn + 1))

        # Image area (top 65% of page)
        img_box_h = (page_h - 2 * margin) * 0.65
        img_box_y = page_h - margin - img_box_h
        if img_bytes:
            _draw_image_fit(c, img_bytes, margin, img_box_y, page_w - 2 * margin, img_box_h)

        # Text area
        text_top = img_box_y - 8 * mm
        _draw_wrapped_ar(c, ba.get("page_text") or "",
                         x=margin, y=text_top,
                         width=page_w - 2 * margin,
                         font_size=13, leading=18)

        # Page number (bottom center)
        c.setFont(ARABIC_FONT_NAME, 9)
        pn = _shape_ar(str(page_number))
        pnw = c.stringWidth(pn, ARABIC_FONT_NAME, 9)
        c.drawString((page_w - pnw) / 2, margin / 2, pn)

        c.showPage()
        pages_drawn += 1

    # ---- Back page ----
    c.setFont(ARABIC_FONT_BOLD, 20)
    the_end = _shape_ar("النهاية")
    tw = c.stringWidth(the_end, ARABIC_FONT_BOLD, 20)
    c.drawString((page_w - tw) / 2, page_h / 2 + 15 * mm, the_end)
    message = plan.get("main_message") or ""
    _draw_wrapped_ar(c, message, x=margin, y=page_h / 2, width=page_w - 2 * margin, font_size=13, leading=20)
    c.showPage()
    pages_drawn += 2  # cover + back

    c.save()
    pdf_bytes = buf.getvalue()

    # Store in object storage
    pdf_file_id = str(uuid.uuid4())
    storage_path = f"{APP_NAME}/orders/{order_id}/generated/final-pdf/{pdf_file_id}.pdf"
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: put_object(storage_path, pdf_bytes, "application/pdf"))
    await db.files.insert_one({
        "id": pdf_file_id,
        "user_id": user_id,
        "scope": "final-pdf",
        "storage_path": result.get("path", storage_path),
        "original_filename": "story.pdf",
        "content_type": "application/pdf",
        "size": result.get("size", len(pdf_bytes)),
        "is_deleted": False,
        "created_at": None,
    })
    return f"/api/uploads/file/{pdf_file_id}", pages_drawn, {
        "renderer": "reportlab",
        "rtl": True,
        "size_bytes": len(pdf_bytes),
        "cover_included": cover_bytes is not None,
    }
