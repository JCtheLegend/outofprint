#!/usr/bin/env python3
from __future__ import annotations

import base64
import io
import os
import queue
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk


TRIM_WIDTH_IN = 6.0
TRIM_HEIGHT_IN = 9.0
DPI = 300
BLEED_EXPAND_IN = 0.125
PAPER_CALIPER_IN = 0.0025
BAND_HEIGHT_IN = 1.5
BAND_BOTTOM_CLEAR_IN = 1.5
SPINE_TOP_BOTTOM_MARGIN_IN = 1.0
SPINE_VOLUME_LABEL_FONT_SIZE = 96
SPINE_LOGO_SIZES_IN = (1.0, 0.5, 0.25)
PUBLISHER_LOGO_FILENAME = "Lionheart Press logo design.png"


try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_LANCZOS = Image.LANCZOS


@dataclass(frozen=True)
class EraStyle:
    label: str
    color_name: str
    band_color: tuple[int, int, int]
    art_style_prompt: str


ERA_20TH_PLUS = EraStyle(
    label="20th century or later",
    color_name="green",
    band_color=(46, 125, 50),
    art_style_prompt=(
        "Italian futurism painting, bold geometric composition, "
        "refined tonal contrast, elegant gallery-quality finish"
    ),
)
ERA_19TH = EraStyle(
    label="19th century",
    color_name="blue",
    band_color=(40, 94, 160),
    art_style_prompt=(
        "romantic realism painting, dramatic sky and landscape, classical detail, "
        "period atmosphere"
    ),
)
ERA_18TH = EraStyle(
    label="18th century",
    color_name="red",
    band_color=(160, 45, 45),
    art_style_prompt=(
        "neoclassical painting style, balanced composition, elegant historical mood, "
        "soft museum-like lighting"
    ),
)
ERA_17TH = EraStyle(
    label="17th century",
    color_name="yellow",
    band_color=(206, 170, 50),
    art_style_prompt=(
        "baroque oil painting style, chiaroscuro lighting, rich textures, "
        "historic period feeling"
    ),
)
ERA_PRE_17TH = EraStyle(
    label="before 17th century",
    color_name="brown",
    band_color=(116, 80, 48),
    art_style_prompt=(
        "late medieval and early renaissance painted manuscript aesthetic, "
        "hand-painted textures, muted pigments, historical atmosphere"
    ),
)


def style_for_year(year: int) -> EraStyle:
    if year >= 1900:
        return ERA_20TH_PLUS
    if year >= 1800:
        return ERA_19TH
    if year >= 1700:
        return ERA_18TH
    if year >= 1600:
        return ERA_17TH
    return ERA_PRE_17TH


def spine_thickness_in(page_count: int) -> float:
    return max(0.08, page_count * PAPER_CALIPER_IN)


def spine_width_px(page_count: int) -> int:
    return max(24, int(round(spine_thickness_in(page_count) * DPI)))


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def text_color_for_background(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return (255, 255, 255) if luminance(rgb) < 140 else (20, 20, 20)


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Times New Roman Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "DejaVuSerif-Bold.ttf",
        ])
    else:
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Times New Roman.ttf",
            "/Library/Fonts/Arial.ttf",
            "DejaVuSerif.ttf",
        ])

    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def load_spine_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Baskerville Bold.ttf",
            "/System/Library/Fonts/Supplemental/Palatino Bold.ttf",
            "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
            "DejaVuSerif-Bold.ttf",
        ])
    else:
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Baskerville.ttc",
            "/System/Library/Fonts/Supplemental/Palatino.ttc",
            "/System/Library/Fonts/Supplemental/Georgia.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
            "DejaVuSerif.ttf",
        ])

    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return load_font(size, bold=bold)


def load_front_title_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Didot.ttc",
        "/System/Library/Fonts/Supplemental/Bodoni 72.ttc",
        "/System/Library/Fonts/Supplemental/Baskerville Bold.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        "DejaVuSerif-Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return load_font(size, bold=True)


def load_front_text_font(size: int, bold: bool = False, italic: bool = False) -> ImageFont.ImageFont:
    candidates: list[str] = []
    if bold and italic:
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Palatino Bold Italic.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf",
        ])
    elif bold:
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Palatino Bold.ttf",
            "/System/Library/Fonts/Supplemental/Baskerville Bold.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        ])
    elif italic:
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Palatino Italic.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf",
        ])
    else:
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Palatino.ttc",
            "/System/Library/Fonts/Supplemental/Baskerville.ttc",
            "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        ])
    candidates.extend(["DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf"])
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return load_font(size, bold=bold)


def load_spine_title_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Didot.ttc",
        "/System/Library/Fonts/Supplemental/Bodoni 72.ttc",
        "/System/Library/Fonts/Supplemental/Bodoni 72 Smallcaps Book.ttf",
        "/System/Library/Fonts/Supplemental/Baskerville Bold.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        "DejaVuSerif-Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return load_spine_font(size, bold=True)


def load_spine_author_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Palatino.ttc",
        "/System/Library/Fonts/Supplemental/Garamond.ttf",
        "/System/Library/Fonts/Supplemental/Baskerville.ttc",
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "DejaVuSerif.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return load_spine_font(size, bold=False)


def load_spine_volume_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/Library/Fonts/Times New Roman.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        "/Library/Fonts/Times New Roman Bold.ttf",
        "DejaVuSerif.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return load_font(size, bold=False)


def draw_fancy_spine_divider(draw: ImageDraw.ImageDraw, x: int, y0: int, y1: int, color: tuple[int, int, int]) -> None:
    if y1 <= y0 + 8:
        return
    draw.line((x - 1, y0, x - 1, y1), fill=color, width=1)
    draw.line((x + 1, y0, x + 1, y1), fill=color, width=1)
    mid = (y0 + y1) // 2
    diamond_h = 9
    diamond_w = 6
    draw.polygon(
        [(x, mid - diamond_h), (x + diamond_w, mid), (x, mid + diamond_h), (x - diamond_w, mid)],
        outline=color,
    )
    dot_r = 2
    draw.ellipse((x - dot_r, y0 - dot_r, x + dot_r, y0 + dot_r), fill=color)
    draw.ellipse((x - dot_r, y1 - dot_r, x + dot_r, y1 + dot_r), fill=color)


def fixed_size_spine_logo(
    logo_img: Image.Image,
    max_w: int,
    max_h: int,
) -> Image.Image | None:
    for size_in in SPINE_LOGO_SIZES_IN:
        target = int(round(size_in * DPI))
        if target <= max_w and target <= max_h:
            logo = logo_img.copy()
            w, h = logo.size
            if w <= 0 or h <= 0:
                return None
            scale = target / max(w, h)
            new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
            return logo.resize(new_size, RESAMPLE_LANCZOS)
    return None


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def best_two_line_split(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> list[str]:
    words = text.split()
    if len(words) <= 1:
        return [text.strip()] if text.strip() else []
    best_left = " ".join(words[:-1])
    best_right = words[-1]
    best_score = float("inf")
    for idx in range(1, len(words)):
        left = " ".join(words[:idx])
        right = " ".join(words[idx:])
        score = max(draw.textlength(left, font=font), draw.textlength(right, font=font))
        if score < best_score:
            best_score = score
            best_left = left
            best_right = right
    return [best_left, best_right]


def author_last_name(author: str) -> str:
    parts = [part for part in author.replace(",", " ").split() if part]
    if not parts:
        return ""
    suffixes = {"jr", "sr", "ii", "iii", "iv", "v"}
    tail = parts[-1].rstrip(".").lower()
    if len(parts) >= 2 and tail in suffixes:
        return parts[-2]
    return parts[-1]


def to_roman(value: int) -> str:
    if value <= 0:
        raise ValueError("Roman numerals require a positive integer.")
    numerals = [
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ]
    remaining = value
    result: list[str] = []
    for amount, numeral in numerals:
        count, remaining = divmod(remaining, amount)
        if count:
            result.append(numeral * count)
    return "".join(result)


def build_prompt(title: str, subtitle: str, author: str, year: int, style: EraStyle) -> str:
    subtitle_clause = f"Subtitle context: {subtitle}." if subtitle else "No subtitle."
    return (
        "Create a vertical painted book cover image (no text, no letters, no logos, no typography). "
        "The image is for a historical nonfiction book and must feel premium and timeless. "
        "Leave the lower 28% visually calmer to allow a colored title band overlay. "
        "Avoid hard edges at the very bottom so text remains legible over a color band. "
        f"Use this painting direction: {style.art_style_prompt}. "
        f"Book context: title is {title}. Author is {author}. {subtitle_clause} "
        f"Publication year context: {year}. "
        "Return only a single coherent artwork."
    )


def build_prompt_with_extra(
    title: str,
    subtitle: str,
    author: str,
    year: int,
    style: EraStyle,
    extra_instructions: str,
) -> str:
    base = build_prompt(title, subtitle, author, year, style)
    extra = extra_instructions.strip()
    if not extra:
        return base
    return f"{base} Additional user art direction: {extra}"


def build_back_prompt(title: str, subtitle: str, author: str, year: int, style: EraStyle) -> str:
    subtitle_clause = f"Subtitle context: {subtitle}." if subtitle else "No subtitle."
    return (
        "This is a wraparound outpainting task. The right panel is the existing front cover and must remain unchanged. "
        "Paint only the left panel as a natural extension of the same scene to the left. "
        "Ensure visual continuity at the panel seam and keep brushwork, lighting, and palette consistent. "
        "Keep the lower 28% visually calm for a color band overlay. "
        "No text, no letters, no logos, no typography. "
        f"Use this painting direction: {style.art_style_prompt}. "
        f"Book context: title is {title}. Author is {author}. {subtitle_clause} "
        f"Publication year context: {year}. "
        "Return only a single coherent artwork."
    )


def _image_from_response(response: Any) -> Image.Image:
    if not getattr(response, "data", None):
        raise RuntimeError("Image API returned no data.")

    item = response.data[0]
    b64_payload = getattr(item, "b64_json", None)
    if b64_payload:
        raw = base64.b64decode(b64_payload)
        return Image.open(io.BytesIO(raw)).convert("RGB")

    url = getattr(item, "url", None)
    if url:
        with urllib.request.urlopen(url) as handle:
            raw = handle.read()
        return Image.open(io.BytesIO(raw)).convert("RGB")

    raise RuntimeError("Image API returned an unsupported payload.")


def generate_front_art(api_key: str, model: str, prompt: str) -> Image.Image:
    client = OpenAI(api_key=api_key)
    response = client.images.generate(
        model=model,
        prompt=prompt,
        size="1024x1536",
    )
    return _image_from_response(response)


def generate_back_art(
    api_key: str,
    model: str,
    front_art: Image.Image,
    title: str,
    subtitle: str,
    author: str,
    year: int,
    style: EraStyle,
) -> Image.Image:
    client = OpenAI(api_key=api_key)
    prompt = build_back_prompt(title, subtitle, author, year, style)

    # Build a two-panel horizontal seed: blank back panel on the left and front panel on the right.
    panel_w, panel_h = 768, 1024
    wrap_w = panel_w * 2
    front_panel = ImageOps.fit(front_art, (panel_w, panel_h), method=RESAMPLE_LANCZOS)
    seed = Image.new("RGBA", (wrap_w, panel_h), (0, 0, 0, 0))
    seed.paste(front_panel.convert("RGBA"), (panel_w, 0))
    with io.BytesIO() as buf:
        seed.save(buf, format="PNG")
        seed_payload = buf.getvalue()

    try:
        response = client.images.edit(
            model=model,
            image=("wrap_seed.png", seed_payload, "image/png"),
            prompt=prompt,
            size="1536x1024",
        )
        wrap_image = _image_from_response(response)
        back_panel = wrap_image.crop((0, 0, panel_w, panel_h))
        return back_panel
    except Exception:
        fallback_prompt = (
            "Create a vertical painted back cover only. "
            "It should feel like the scene extends naturally to the left of the front cover, "
            "with matching palette, lighting, and brushwork. "
            "No text, no letters, no logos, no typography. "
            f"Use this painting direction: {style.art_style_prompt}. "
            f"Book context: title is {title}. Author is {author}. "
            f"Publication year context: {year}."
        )
        response = client.images.generate(
            model=model,
            prompt=fallback_prompt,
            size="1024x1536",
        )
        return _image_from_response(response)


def compose_full_cover(
    front_art: Image.Image,
    back_art: Image.Image,
    title: str,
    subtitle: str,
    author: str,
    spine_title: str,
    volume_label: str,
    page_count: int,
    manual_spine_width_in: float | None,
    expand_with_bleed: bool,
    style: EraStyle,
) -> tuple[Image.Image, dict[str, Any]]:
    front_w = int(round(TRIM_WIDTH_IN * DPI))
    cover_h = int(round(TRIM_HEIGHT_IN * DPI))
    spine_thickness = manual_spine_width_in if manual_spine_width_in is not None else spine_thickness_in(page_count)
    spine_w = max(1, int(round(spine_thickness * DPI)))
    full_w = front_w * 2 + spine_w
    bleed_px = int(round(BLEED_EXPAND_IN * DPI)) if expand_with_bleed else 0
    output_w = full_w + (2 * bleed_px)
    output_h = cover_h + (2 * bleed_px)

    cover = Image.new("RGB", (output_w, output_h), style.band_color)
    draw = ImageDraw.Draw(cover)

    back_x0 = bleed_px
    spine_x0 = bleed_px + front_w
    front_x0 = bleed_px + front_w + spine_w

    back_img = ImageOps.fit(back_art, (front_w + bleed_px, output_h), method=RESAMPLE_LANCZOS)
    front_img = ImageOps.fit(front_art, (front_w + bleed_px, output_h), method=RESAMPLE_LANCZOS)
    cover.paste(back_img, (0, 0))
    cover.paste(front_img, (front_x0, 0))

    band_h = int(round(BAND_HEIGHT_IN * DPI))
    band_bottom_clear = int(round(BAND_BOTTOM_CLEAR_IN * DPI))
    band_y1 = bleed_px + max(0, cover_h - band_bottom_clear)
    band_y0 = max(0, band_y1 - band_h)
    draw.rectangle((0, band_y0, back_x0 + front_w, band_y1), fill=style.band_color)
    draw.rectangle((front_x0, band_y0, front_x0 + front_w + bleed_px, band_y1), fill=style.band_color)

    # Subtle separators between back/spine/front
    separator = tuple(max(0, channel - 35) for channel in style.band_color)
    draw.line((spine_x0, 0, spine_x0, output_h), fill=separator, width=2)
    draw.line((spine_x0 + spine_w, 0, spine_x0 + spine_w, output_h), fill=separator, width=2)

    band_text_color = text_color_for_background(style.band_color)
    title_font = load_front_title_font(96)
    subtitle_font = load_front_text_font(44, italic=True)
    author_font = load_front_text_font(42, bold=True)

    available_w = front_w - 130
    title_lines = wrap_text(draw, title.strip(), title_font, available_w)
    subtitle_lines = wrap_text(draw, subtitle.strip(), subtitle_font, available_w) if subtitle.strip() else []
    author_front_text = author.strip().upper()
    author_lines = wrap_text(draw, author_front_text, author_font, available_w) if author_front_text else []

    y = band_y0 + 38
    x_center = front_x0 + front_w // 2
    for line in title_lines[:2]:
        draw.text((x_center, y), line, font=title_font, fill=band_text_color, anchor="ma")
        y += int(title_font.size * 1.08)
    if subtitle_lines:
        y += 16
        for line in subtitle_lines[:2]:
            draw.text((x_center, y), line, font=subtitle_font, fill=band_text_color, anchor="ma")
            y += int(subtitle_font.size * 1.1)
    if author_lines:
        y += 18
        for line in author_lines[:2]:
            draw.text((x_center, y), line, font=author_font, fill=band_text_color, anchor="ma")
            y += int(author_font.size * 1.1)

    spine_title_text = spine_title.strip() or title.strip()
    spine_author_text = author_last_name(author.strip())
    spine_layer = Image.new("RGBA", (cover_h, spine_w), (0, 0, 0, 0))
    spine_draw = ImageDraw.Draw(spine_layer)

    zone_h = int(round(1.5 * DPI))
    content_start = zone_h
    content_end = max(zone_h + 40, cover_h - zone_h)
    content_len = max(100, content_end - content_start)

    # Keep title and author visually distinct on the spine.
    if spine_title_text and spine_author_text:
        segment_gap = min(70, max(36, int(content_len * 0.06)))
        segment_len = max(60, content_len - segment_gap)
        title_seg = int(segment_len * 0.58)
        author_seg = max(40, segment_len - title_seg)

        title_size = 80
        author_size = 80
        title_font = load_spine_title_font(title_size)
        author_font = load_spine_author_font(author_size)
        author_display = spine_author_text.upper()
        title_max = max(40, title_seg - 24)

        y_center = spine_w // 2
        title_x = content_start + (title_seg // 2)
        author_x = content_start + title_seg + segment_gap + (author_seg // 2)
        divider_x = content_start + title_seg + (segment_gap // 2)

        one_line_limit = int(title_max * 0.72)
        if spine_draw.textlength(spine_title_text, font=title_font) > one_line_limit:
            split_font = load_spine_title_font(60)
            split_lines = best_two_line_split(spine_draw, spine_title_text, split_font)
            if len(split_lines) >= 2:
                # Draw as left/right columns on the final spine while keeping the pair centered.
                requested_offset = max(18, int(60 * 0.45))
                max_offset = max(6, (spine_w // 2) - 8)
                side_offset = min(requested_offset, max_offset)
                split_center = title_x
                spine_draw.text(
                    (split_center, y_center - side_offset),
                    split_lines[0],
                    fill=band_text_color,
                    font=split_font,
                    anchor="mm",
                )
                spine_draw.text(
                    (split_center, y_center + side_offset),
                    split_lines[1],
                    fill=band_text_color,
                    font=split_font,
                    anchor="mm",
                )
            elif split_lines:
                spine_draw.text((title_x, y_center), split_lines[0], fill=band_text_color, font=split_font, anchor="mm")
        else:
            spine_draw.text((title_x, y_center), spine_title_text, fill=band_text_color, font=title_font, anchor="mm")
        spine_draw.text((author_x, y_center), author_display, fill=band_text_color, font=author_font, anchor="mm")
        draw_fancy_spine_divider(spine_draw, divider_x, 14, max(18, spine_w - 14), band_text_color)
    else:
        fallback = spine_title_text or spine_author_text or "Untitled"
        spine_font = load_spine_font(max(12, int(spine_w * 0.80)), bold=True)
        max_spine_text_w = cover_h - 120
        while spine_font.size > 10 and spine_draw.textlength(fallback, font=spine_font) > max_spine_text_w:
            spine_font = load_spine_font(spine_font.size - 1, bold=True)
        spine_draw.text((cover_h // 2, spine_w // 2), fallback, fill=band_text_color, font=spine_font, anchor="mm")

    spine_rotated = spine_layer.rotate(90, expand=True)
    cover.paste(spine_rotated, (spine_x0, bleed_px), spine_rotated)

    logo_path = Path(__file__).with_name(PUBLISHER_LOGO_FILENAME)
    logo_img: Image.Image | None = None
    if logo_path.exists():
        try:
            logo_img = Image.open(logo_path).convert("RGBA")
        except Exception:
            logo_img = None

    if logo_img is not None:
        # Spine top zone logo: choose one fixed size only, or omit if none fit.
        spine_logo_max_w = max(12, spine_w - 10)
        spine_logo_max_h = max(12, zone_h - 16)
        spine_logo = fixed_size_spine_logo(logo_img, spine_logo_max_w, spine_logo_max_h)
        if spine_logo is not None:
            spine_logo_x = spine_x0 + ((spine_w - spine_logo.width) // 2)
            spine_logo_y = bleed_px + ((zone_h - spine_logo.height) // 2)
            cover.paste(spine_logo, (spine_logo_x, spine_logo_y), spine_logo)

        # Back band publisher mark and imprint text.
        back_logo = logo_img.copy()
        back_logo_max_h = max(40, band_h - 40)
        back_logo_max_w = max(40, int(front_w * 0.22))
        back_logo.thumbnail((back_logo_max_w, back_logo_max_h), RESAMPLE_LANCZOS)
        back_logo_x = back_x0 + 34
        back_logo_y = band_y0 + (band_h - back_logo.height) // 2
        cover.paste(back_logo, (back_logo_x, back_logo_y), back_logo)

        imprint = (
            "This book has been republished by Lionheart Press. "
            "Our mission is to make every public domain book available in a quality printed format. "
            "Request that any public domain book be added to our catelog at Lionheartpress.com"
        )
        text_x0 = back_logo_x + back_logo.width + 24
        text_x1 = back_x0 + front_w - 28
        text_y = band_y0 + 26
        imprint_font = load_font(30, bold=False)
        text_max_w = max(120, text_x1 - text_x0)
        lines = wrap_text(draw, imprint, imprint_font, text_max_w)
        line_step = int(imprint_font.size * 1.2)
        max_lines = max(2, (band_h - 52) // max(1, line_step))
        while len(lines) > max_lines and imprint_font.size > 14:
            imprint_font = load_font(imprint_font.size - 2, bold=False)
            lines = wrap_text(draw, imprint, imprint_font, text_max_w)
            line_step = int(imprint_font.size * 1.2)
            max_lines = max(2, (band_h - 52) // max(1, line_step))
        for line in lines[:max_lines]:
            draw.text((text_x0, text_y), line, fill=band_text_color, font=imprint_font, anchor="la")
            text_y += line_step

    volume_text = volume_label.strip()
    if volume_text:
        draw_label = volume_text
        if volume_text.isdigit():
            try:
                numeric_volume = int(volume_text)
            except ValueError:
                numeric_volume = 0
            if numeric_volume > 0:
                draw_label = to_roman(numeric_volume)
        vol_font = load_spine_volume_font(SPINE_VOLUME_LABEL_FONT_SIZE)
        bottom_zone_h = int(round(1.5 * DPI))
        volume_y = bleed_px + cover_h - (bottom_zone_h // 2)
        draw.text(
            (spine_x0 + (spine_w // 2), volume_y),
            draw_label,
            fill=band_text_color,
            font=vol_font,
            anchor="mm",
        )

    output = cover

    return output, {
        "front_width_px": front_w,
        "height_px": cover_h,
        "spine_width_px": spine_w,
        "spine_thickness_in": spine_thickness,
        "era_label": style.label,
        "band_color": style.color_name,
        "full_width_px": full_w,
        "output_width_px": output.width,
        "output_height_px": output.height,
        "expand_with_bleed": expand_with_bleed,
        "bleed_px": bleed_px,
        "bleed_in": BLEED_EXPAND_IN if expand_with_bleed else 0,
    }


class CoverDesignerGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Automatic Cover Designer")
        self.root.geometry("1360x900")
        self.messages: queue.Queue = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.preview_tk: ImageTk.PhotoImage | None = None
        self.current_cover: Image.Image | None = None

        self.api_key_var = tk.StringVar(value=os.environ.get("OPENAI_API_KEY", ""))
        self.model_var = tk.StringVar(value="gpt-image-1")
        self.title_var = tk.StringVar()
        self.subtitle_var = tk.StringVar()
        self.author_var = tk.StringVar()
        self.spine_title_var = tk.StringVar()
        self.volume_var = tk.StringVar()
        self.manual_spine_width_var = tk.StringVar()
        self.expand_bleed_var = tk.BooleanVar(value=False)
        self.year_var = tk.StringVar(value="1776")
        self.pages_var = tk.StringVar(value="320")
        self.extra_instructions_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(Path.cwd()))
        self.status_var = tk.StringVar(value="Ready")
        self.metrics_var = tk.StringVar(value="")
        self.style_var = tk.StringVar(value="")

        self._build_ui()
        self.root.after(150, self._poll_queue)

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        form = ttk.Frame(outer)
        form.pack(fill="x")
        ttk.Label(form, text="Title").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.title_var, width=54).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Label(form, text="Subtitle").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.subtitle_var, width=54).grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(6, 0))
        ttk.Label(form, text="Author").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.author_var, width=54).grid(row=2, column=1, sticky="ew", padx=(8, 8), pady=(6, 0))
        ttk.Label(form, text="Spine title (optional)").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.spine_title_var, width=54).grid(row=3, column=1, sticky="ew", padx=(8, 8), pady=(6, 0))

        ttk.Label(form, text="Publication year").grid(row=0, column=2, sticky="w")
        ttk.Entry(form, textvariable=self.year_var, width=10).grid(row=0, column=3, sticky="w", padx=(8, 8))
        ttk.Label(form, text="Page count").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.pages_var, width=10).grid(row=1, column=3, sticky="w", padx=(8, 8), pady=(6, 0))
        ttk.Label(form, text="Image model").grid(row=2, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.model_var, width=14).grid(row=2, column=3, sticky="w", padx=(8, 8), pady=(6, 0))
        ttk.Label(form, text="Volume label (optional)").grid(row=3, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.volume_var, width=10).grid(row=3, column=3, sticky="w", padx=(8, 8), pady=(6, 0))
        ttk.Label(form, text="Manual spine width in (optional)").grid(row=4, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.manual_spine_width_var, width=10).grid(row=4, column=3, sticky="w", padx=(8, 8), pady=(6, 0))
        ttk.Checkbutton(form, text='Add 0.125" bleed all around', variable=self.expand_bleed_var).grid(
            row=5, column=2, columnspan=2, sticky="w", pady=(6, 0)
        )

        ttk.Label(form, text="OpenAI API key").grid(row=6, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(form, textvariable=self.api_key_var, show="*", width=70).grid(row=6, column=1, columnspan=3, sticky="ew", padx=(8, 8), pady=(10, 0))
        ttk.Label(form, text="Additional image instructions").grid(row=7, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.extra_instructions_var, width=70).grid(row=7, column=1, columnspan=3, sticky="ew", padx=(8, 8), pady=(6, 0))
        ttk.Label(form, text="Output folder").grid(row=8, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.output_var, width=70).grid(row=8, column=1, columnspan=2, sticky="ew", padx=(8, 8), pady=(6, 0))
        ttk.Button(form, text="Browse", command=self._choose_output_dir).grid(row=8, column=3, sticky="w", pady=(6, 0))
        form.columnconfigure(1, weight=1)

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(12, 6))
        self.generate_button = ttk.Button(controls, text="Generate Cover", command=self.start_generate)
        self.generate_button.grid(row=0, column=0, sticky="w")
        self.regen_button = ttk.Button(controls, text="Get New Image", command=self.start_regenerate)
        self.regen_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.save_button = ttk.Button(controls, text="Save Full Cover", command=self.save_cover)
        self.save_button.grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Label(controls, textvariable=self.status_var).grid(row=0, column=3, sticky="w", padx=(12, 0))

        ttk.Label(outer, textvariable=self.style_var).pack(anchor="w")
        ttk.Label(outer, textvariable=self.metrics_var).pack(anchor="w", pady=(2, 6))
        self.progress = ttk.Progressbar(outer, mode="determinate")
        self.progress.pack(fill="x")

        preview_frame = ttk.Frame(outer)
        preview_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.preview_label = ttk.Label(preview_frame, anchor="center")
        self.preview_label.pack(fill="both", expand=True)
        self.root.bind("<Configure>", self._on_resize)

    def _choose_output_dir(self):
        folder = filedialog.askdirectory(title="Choose output folder", parent=self.root)
        if folder:
            self.output_var.set(folder)

    def _collect_inputs(self) -> dict[str, Any]:
        title = self.title_var.get().strip()
        author = self.author_var.get().strip()
        subtitle = self.subtitle_var.get().strip()
        if not title:
            raise ValueError("Enter a title.")
        if not author:
            raise ValueError("Enter an author.")
        api_key = self.api_key_var.get().strip()
        if not api_key:
            raise ValueError("Enter your OpenAI API key.")

        try:
            year = int(self.year_var.get().strip())
        except ValueError as e:
            raise ValueError("Publication year must be an integer.") from e

        try:
            page_count = int(self.pages_var.get().strip())
        except ValueError as e:
            raise ValueError("Page count must be an integer.") from e
        if page_count <= 0:
            raise ValueError("Page count must be greater than 0.")
        volume_label = self.volume_var.get().strip()
        manual_spine_width_in: float | None = None
        manual_spine_text = self.manual_spine_width_var.get().strip()
        if manual_spine_text:
            try:
                manual_spine_width_in = float(manual_spine_text)
            except ValueError as e:
                raise ValueError("Manual spine width must be a number in inches.") from e
            if manual_spine_width_in <= 0:
                raise ValueError("Manual spine width must be greater than 0.")

        output_dir = Path(self.output_var.get().strip())
        if not output_dir:
            raise ValueError("Choose an output folder.")
        output_dir.mkdir(parents=True, exist_ok=True)

        return {
            "title": title,
            "subtitle": subtitle,
            "author": author,
            "spine_title": self.spine_title_var.get().strip(),
            "volume_label": volume_label,
            "api_key": api_key,
            "year": year,
            "page_count": page_count,
            "manual_spine_width_in": manual_spine_width_in,
            "expand_with_bleed": bool(self.expand_bleed_var.get()),
            "model": self.model_var.get().strip() or "gpt-image-1",
            "output_dir": output_dir,
            "extra_instructions": self.extra_instructions_var.get().strip(),
        }

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self.generate_button.config(state=state)
        self.regen_button.config(state=state)
        self.save_button.config(state="normal" if (not busy and self.current_cover is not None) else "disabled")

    def start_generate(self):
        self._start_generation()

    def start_regenerate(self):
        self._start_generation()

    def _start_generation(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Busy", "Generation is already running.", parent=self.root)
            return
        try:
            cfg = self._collect_inputs()
        except ValueError as e:
            messagebox.showerror("Input error", str(e), parent=self.root)
            return
        self._set_busy(True)
        self.progress["value"] = 0
        self.progress["maximum"] = 4
        self.status_var.set("Generating front artwork...")
        self.worker_thread = threading.Thread(target=self._generate_worker, args=(cfg,), daemon=True)
        self.worker_thread.start()

    def _generate_worker(self, cfg: dict[str, Any]):
        try:
            style = style_for_year(cfg["year"])
            self.messages.put(("progress", (1, 4)))
            prompt = build_prompt_with_extra(
                cfg["title"],
                cfg["subtitle"],
                cfg["author"],
                cfg["year"],
                style,
                cfg.get("extra_instructions", ""),
            )
            front_art = generate_front_art(cfg["api_key"], cfg["model"], prompt)

            self.messages.put(("status", "Generating matching back artwork..."))
            self.messages.put(("progress", (2, 4)))
            back_art = generate_back_art(
                api_key=cfg["api_key"],
                model=cfg["model"],
                front_art=front_art,
                title=cfg["title"],
                subtitle=cfg["subtitle"],
                author=cfg["author"],
                year=cfg["year"],
                style=style,
            )

            self.messages.put(("status", "Composing full cover..."))
            self.messages.put(("progress", (3, 4)))
            cover, metrics = compose_full_cover(
                front_art=front_art,
                back_art=back_art,
                title=cfg["title"],
                subtitle=cfg["subtitle"],
                author=cfg["author"],
                spine_title=cfg.get("spine_title", ""),
                volume_label=cfg.get("volume_label", ""),
                page_count=cfg["page_count"],
                manual_spine_width_in=cfg.get("manual_spine_width_in"),
                expand_with_bleed=bool(cfg.get("expand_with_bleed", False)),
                style=style,
            )
            self.messages.put(("done", (cover, metrics, style)))
        except Exception as e:
            self.messages.put(("error", str(e)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "progress":
                    value, maximum = payload
                    self.progress["maximum"] = max(1, int(maximum))
                    self.progress["value"] = int(value)
                elif kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "done":
                    cover, metrics, style = payload
                    self.current_cover = cover
                    self.style_var.set(
                        f"Century style: {style.label} | Band color: {style.color_name} | Painting style: {style.art_style_prompt}"
                    )
                    self.metrics_var.set(
                        f"Spine thickness: {metrics['spine_thickness_in']:.3f} in ({metrics['spine_width_px']} px @ {DPI} dpi) | "
                        f"Trim size: {metrics['full_width_px']} x {metrics['height_px']} px | "
                        f"Output size: {metrics['output_width_px']} x {metrics['output_height_px']} px"
                    )
                    self.status_var.set("Ready")
                    self.progress["value"] = self.progress["maximum"]
                    self._render_preview()
                    self._set_busy(False)
                elif kind == "error":
                    self._set_busy(False)
                    self.status_var.set("Failed")
                    messagebox.showerror("Cover generation failed", str(payload), parent=self.root)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)

    def _render_preview(self):
        if self.current_cover is None:
            return
        width = max(300, self.preview_label.winfo_width() - 20)
        height = max(300, self.preview_label.winfo_height() - 20)
        preview = self.current_cover.copy()
        preview.thumbnail((width, height), RESAMPLE_LANCZOS)
        self.preview_tk = ImageTk.PhotoImage(preview)
        self.preview_label.configure(image=self.preview_tk)

    def _on_resize(self, event):
        if event.widget is self.root and self.current_cover is not None:
            self._render_preview()

    def save_cover(self):
        if self.current_cover is None:
            messagebox.showinfo("Nothing to save", "Generate a cover first.", parent=self.root)
            return
        output_dir = Path(self.output_var.get().strip() or Path.cwd())
        output_dir.mkdir(parents=True, exist_ok=True)
        default_name = f"{self.title_var.get().strip() or 'book'}_full_cover.png".replace(" ", "_")
        out_path = filedialog.asksaveasfilename(
            title="Save full cover",
            initialdir=str(output_dir),
            initialfile=default_name,
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("JPEG", "*.jpg;*.jpeg"), ("All files", "*.*")],
            parent=self.root,
        )
        if not out_path:
            return
        path = Path(out_path)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            # Pillow PDF export expects RGB/L mode images.
            self.current_cover.convert("RGB").save(path, format="PDF", resolution=DPI)
        elif suffix in {".jpg", ".jpeg"}:
            self.current_cover.save(path, quality=95)
        else:
            self.current_cover.save(path)
        self.status_var.set(f"Saved: {path}")


def main():
    root = tk.Tk()
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    CoverDesignerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
