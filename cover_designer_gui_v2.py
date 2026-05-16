#!/usr/bin/env python3
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk


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
PANEL_BORDER_MARGIN_PX = int(round(0.28 * DPI))
BORDER_CORNER_GAP_PX = 150
BACK_FOOTER_BORDER_GUTTER_PX = int(round(0.50 * DPI))
BACK_FOOTER_MAX_HEIGHT_PX = int(round(1.15 * DPI))
BACK_LOGO_MAX_SIZE_PX = int(round(1.05 * DPI))


try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_LANCZOS = Image.LANCZOS


@dataclass(frozen=True)
class EraStyle:
    label: str
    color_name: str
    band_color: tuple[int, int, int]
    accent_color: tuple[int, int, int]
    front_border_pattern: str
    back_border_pattern: str


ERA_20TH_PLUS = EraStyle(
    label="20th century or later",
    color_name="green",
    band_color=(46, 125, 50),
    accent_color=(239, 228, 177),
    front_border_pattern="geometric_blocks",
    back_border_pattern="diagonal_ticks",
)
ERA_19TH = EraStyle(
    label="19th century",
    color_name="blue",
    band_color=(40, 94, 160),
    accent_color=(235, 220, 170),
    front_border_pattern="victorian_rosettes",
    back_border_pattern="vine_dots",
)
ERA_18TH = EraStyle(
    label="18th century",
    color_name="red",
    band_color=(160, 45, 45),
    accent_color=(247, 226, 174),
    front_border_pattern="greek_key",
    back_border_pattern="laurel",
)
ERA_17TH = EraStyle(
    label="17th century",
    color_name="yellow",
    band_color=(206, 170, 50),
    accent_color=(74, 50, 34),
    front_border_pattern="baroque_scallop",
    back_border_pattern="beaded_frame",
)
ERA_PRE_17TH = EraStyle(
    label="before 17th century",
    color_name="brown",
    band_color=(116, 80, 48),
    accent_color=(230, 198, 132),
    front_border_pattern="manuscript_blocks",
    back_border_pattern="rubric_dashes",
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


def _inset_rect(rect: tuple[int, int, int, int], amount: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    return (x0 + amount, y0 + amount, x1 - amount, y1 - amount)


def _draw_frame_rules(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    draw.rectangle(rect, outline=color, width=6)
    draw.rectangle(_inset_rect(rect, 22), outline=color, width=2)


def _draw_diamond(draw: ImageDraw.ImageDraw, x: int, y: int, r: int, color: tuple[int, int, int], fill: bool = False) -> None:
    points = [(x, y - r), (x + r, y), (x, y + r), (x - r, y)]
    draw.polygon(points, outline=color, fill=color if fill else None)


def _edge_positions(start: int, end: int, spacing: int, gap: int = BORDER_CORNER_GAP_PX) -> range:
    return range(start + gap, end - gap, spacing)


def _draw_corner_brackets(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    x0, y0, x1, y1 = rect
    offset = 44
    length = 68
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        cx = x0 + offset if sx > 0 else x1 - offset
        cy = y0 + offset if sy > 0 else y1 - offset
        draw.line((cx, cy, cx + (sx * length), cy), fill=color, width=4)
        draw.line((cx, cy, cx, cy + (sy * length)), fill=color, width=4)
        _draw_diamond(draw, cx + (sx * 26), cy + (sy * 26), 9, color, fill=True)


def _draw_geometric_blocks(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    _draw_frame_rules(draw, rect, color)
    x0, y0, x1, y1 = rect
    block = 28
    spacing = 120
    for x in _edge_positions(x0, x1, spacing):
        draw.rectangle((x, y0 + 34, x + block, y0 + 64), fill=color)
        draw.rectangle((x + 44, y1 - 64, x + 44 + block, y1 - 34), fill=color)
    for y in _edge_positions(y0, y1, spacing):
        draw.rectangle((x0 + 34, y, x0 + 64, y + block), fill=color)
        draw.rectangle((x1 - 64, y + 44, x1 - 34, y + 44 + block), fill=color)
    corner = 44
    for cx, cy in ((x0 + 44, y0 + 44), (x1 - 44, y0 + 44), (x0 + 44, y1 - 44), (x1 - 44, y1 - 44)):
        draw.rectangle((cx - corner // 2, cy - corner // 2, cx + corner // 2, cy + corner // 2), outline=color, width=4)


def _draw_diagonal_ticks(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    _draw_frame_rules(draw, rect, color)
    x0, y0, x1, y1 = rect
    spacing = 84
    _draw_corner_brackets(draw, rect, color)
    for x in _edge_positions(x0, x1, spacing):
        draw.line((x, y0 + 36, x + 30, y0 + 66), fill=color, width=4)
        draw.line((x, y1 - 66, x + 30, y1 - 36), fill=color, width=4)
    for y in _edge_positions(y0, y1, spacing):
        draw.line((x0 + 36, y, x0 + 66, y + 30), fill=color, width=4)
        draw.line((x1 - 66, y, x1 - 36, y + 30), fill=color, width=4)


def _draw_victorian_rosettes(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    _draw_frame_rules(draw, rect, color)
    x0, y0, x1, y1 = rect
    for cx, cy in ((x0 + 58, y0 + 58), (x1 - 58, y0 + 58), (x0 + 58, y1 - 58), (x1 - 58, y1 - 58)):
        draw.ellipse((cx - 32, cy - 32, cx + 32, cy + 32), outline=color, width=3)
        draw.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), fill=color)
        _draw_diamond(draw, cx, cy - 45, 10, color, fill=True)
        _draw_diamond(draw, cx, cy + 45, 10, color, fill=True)
        _draw_diamond(draw, cx - 45, cy, 10, color, fill=True)
        _draw_diamond(draw, cx + 45, cy, 10, color, fill=True)
    for x in _edge_positions(x0, x1, 95):
        _draw_diamond(draw, x, y0 + 48, 8, color, fill=True)
        _draw_diamond(draw, x, y1 - 48, 8, color, fill=True)
    for y in _edge_positions(y0, y1, 95):
        _draw_diamond(draw, x0 + 48, y, 8, color, fill=True)
        _draw_diamond(draw, x1 - 48, y, 8, color, fill=True)


def _draw_vine_dots(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    _draw_frame_rules(draw, rect, color)
    x0, y0, x1, y1 = rect
    spacing = 86
    dot = 6
    _draw_corner_brackets(draw, rect, color)
    for x in _edge_positions(x0, x1, spacing):
        draw.ellipse((x - dot, y0 + 44 - dot, x + dot, y0 + 44 + dot), fill=color)
        draw.ellipse((x - dot, y1 - 44 - dot, x + dot, y1 - 44 + dot), fill=color)
        draw.arc((x - 28, y0 + 28, x + 28, y0 + 76), start=200, end=340, fill=color, width=3)
        draw.arc((x - 28, y1 - 76, x + 28, y1 - 28), start=20, end=160, fill=color, width=3)
    for y in _edge_positions(y0, y1, spacing):
        draw.ellipse((x0 + 44 - dot, y - dot, x0 + 44 + dot, y + dot), fill=color)
        draw.ellipse((x1 - 44 - dot, y - dot, x1 - 44 + dot, y + dot), fill=color)


def _draw_greek_key(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    _draw_frame_rules(draw, rect, color)
    x0, y0, x1, y1 = rect
    step = 56
    depth = 28
    _draw_corner_brackets(draw, rect, color)
    for x in _edge_positions(x0, x1, step):
        draw.line((x, y0 + 44, x, y0 + 44 + depth, x + depth, y0 + 44 + depth, x + depth, y0 + 58), fill=color, width=4)
        draw.line((x, y1 - 44, x, y1 - 44 - depth, x + depth, y1 - 44 - depth, x + depth, y1 - 58), fill=color, width=4)
    for y in _edge_positions(y0, y1, step):
        draw.line((x0 + 44, y, x0 + 44 + depth, y, x0 + 44 + depth, y + depth, x0 + 58, y + depth), fill=color, width=4)
        draw.line((x1 - 44, y, x1 - 44 - depth, y, x1 - 44 - depth, y + depth, x1 - 58, y + depth), fill=color, width=4)


def _draw_laurel(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    _draw_frame_rules(draw, rect, color)
    x0, y0, x1, y1 = rect
    spacing = 72
    _draw_corner_brackets(draw, rect, color)
    for x in _edge_positions(x0, x1, spacing):
        draw.polygon([(x, y0 + 40), (x + 22, y0 + 52), (x, y0 + 64), (x - 12, y0 + 52)], outline=color, fill=None)
        draw.polygon([(x, y1 - 40), (x + 22, y1 - 52), (x, y1 - 64), (x - 12, y1 - 52)], outline=color, fill=None)
    for y in _edge_positions(y0, y1, spacing):
        draw.polygon([(x0 + 40, y), (x0 + 52, y + 22), (x0 + 64, y), (x0 + 52, y - 12)], outline=color, fill=None)
        draw.polygon([(x1 - 40, y), (x1 - 52, y + 22), (x1 - 64, y), (x1 - 52, y - 12)], outline=color, fill=None)


def _draw_baroque_scallop(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    _draw_frame_rules(draw, rect, color)
    x0, y0, x1, y1 = rect
    radius = 58
    for x in _edge_positions(x0, x1, radius):
        draw.arc((x - radius // 2, y0 + 34, x + radius // 2, y0 + 92), start=180, end=360, fill=color, width=4)
        draw.arc((x - radius // 2, y1 - 92, x + radius // 2, y1 - 34), start=0, end=180, fill=color, width=4)
    for y in _edge_positions(y0, y1, radius):
        draw.arc((x0 + 34, y - radius // 2, x0 + 92, y + radius // 2), start=90, end=270, fill=color, width=4)
        draw.arc((x1 - 92, y - radius // 2, x1 - 34, y + radius // 2), start=270, end=90, fill=color, width=4)
    for cx, cy in ((x0 + 62, y0 + 62), (x1 - 62, y0 + 62), (x0 + 62, y1 - 62), (x1 - 62, y1 - 62)):
        draw.ellipse((cx - 15, cy - 15, cx + 15, cy + 15), outline=color, width=3)


def _draw_beaded_frame(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    _draw_frame_rules(draw, rect, color)
    x0, y0, x1, y1 = rect
    spacing = 50
    dot = 7
    _draw_corner_brackets(draw, rect, color)
    for x in _edge_positions(x0, x1, spacing):
        draw.ellipse((x - dot, y0 + 48 - dot, x + dot, y0 + 48 + dot), fill=color)
        draw.ellipse((x - dot, y1 - 48 - dot, x + dot, y1 - 48 + dot), fill=color)
    for y in _edge_positions(y0, y1, spacing):
        draw.ellipse((x0 + 48 - dot, y - dot, x0 + 48 + dot, y + dot), fill=color)
        draw.ellipse((x1 - 48 - dot, y - dot, x1 - 48 + dot, y + dot), fill=color)


def _draw_manuscript_blocks(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    _draw_frame_rules(draw, rect, color)
    x0, y0, x1, y1 = rect
    block = 38
    for cx, cy in ((x0 + 58, y0 + 58), (x1 - 58, y0 + 58), (x0 + 58, y1 - 58), (x1 - 58, y1 - 58)):
        draw.rectangle((cx - block, cy - block, cx + block, cy + block), outline=color, width=5)
        _draw_diamond(draw, cx, cy, 18, color, fill=True)
    for x in _edge_positions(x0, x1, 78, gap=170):
        draw.rectangle((x - 12, y0 + 40, x + 12, y0 + 64), fill=color)
        draw.rectangle((x - 12, y1 - 64, x + 12, y1 - 40), fill=color)
    for y in _edge_positions(y0, y1, 78, gap=170):
        draw.rectangle((x0 + 40, y - 12, x0 + 64, y + 12), fill=color)
        draw.rectangle((x1 - 64, y - 12, x1 - 40, y + 12), fill=color)


def _draw_rubric_dashes(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    _draw_frame_rules(draw, rect, color)
    x0, y0, x1, y1 = rect
    spacing = 70
    _draw_corner_brackets(draw, rect, color)
    for x in _edge_positions(x0, x1, spacing):
        draw.line((x - 18, y0 + 48, x + 18, y0 + 48), fill=color, width=5)
        draw.line((x - 18, y1 - 48, x + 18, y1 - 48), fill=color, width=5)
    for y in _edge_positions(y0, y1, spacing):
        draw.line((x0 + 48, y - 18, x0 + 48, y + 18), fill=color, width=5)
        draw.line((x1 - 48, y - 18, x1 - 48, y + 18), fill=color, width=5)


def draw_panel_border_pattern(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    panel_w: int,
    panel_h: int,
    style: EraStyle,
    panel: str,
) -> None:
    rect = (
        x0 + PANEL_BORDER_MARGIN_PX,
        y0 + PANEL_BORDER_MARGIN_PX,
        x0 + panel_w - PANEL_BORDER_MARGIN_PX,
        y0 + panel_h - PANEL_BORDER_MARGIN_PX,
    )
    pattern = style.front_border_pattern if panel == "front" else style.back_border_pattern
    color = style.accent_color
    pattern_drawers = {
        "geometric_blocks": _draw_geometric_blocks,
        "diagonal_ticks": _draw_diagonal_ticks,
        "victorian_rosettes": _draw_victorian_rosettes,
        "vine_dots": _draw_vine_dots,
        "greek_key": _draw_greek_key,
        "laurel": _draw_laurel,
        "baroque_scallop": _draw_baroque_scallop,
        "beaded_frame": _draw_beaded_frame,
        "manuscript_blocks": _draw_manuscript_blocks,
        "rubric_dashes": _draw_rubric_dashes,
    }
    pattern_drawers.get(pattern, _draw_frame_rules)(draw, rect, color)


def compose_full_cover(
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

    draw_panel_border_pattern(draw, back_x0, bleed_px, front_w, cover_h, style, "back")
    draw_panel_border_pattern(draw, front_x0, bleed_px, front_w, cover_h, style, "front")

    # Subtle separators between back/spine/front
    separator = tuple(max(0, channel - 35) for channel in style.band_color)
    draw.line((spine_x0, 0, spine_x0, output_h), fill=separator, width=2)
    draw.line((spine_x0 + spine_w, 0, spine_x0 + spine_w, output_h), fill=separator, width=2)

    band_text_color = text_color_for_background(style.band_color)
    title_font = load_front_title_font(104)
    subtitle_font = load_front_text_font(46, italic=True)
    author_font = load_front_text_font(42, bold=True)

    available_w = front_w - int(round(1.35 * DPI))
    title_lines = wrap_text(draw, title.strip(), title_font, available_w)[:4]
    subtitle_lines = wrap_text(draw, subtitle.strip(), subtitle_font, available_w)[:2] if subtitle.strip() else []
    author_front_text = author.strip().upper()
    author_lines = wrap_text(draw, author_front_text, author_font, available_w)[:2] if author_front_text else []

    title_steps = [int(title_font.size * 1.08)] * len(title_lines)
    subtitle_steps = [int(subtitle_font.size * 1.1)] * len(subtitle_lines)
    author_steps = [int(author_font.size * 1.1)] * len(author_lines)
    title_height = sum(title_steps)
    if title_lines:
        title_height -= title_steps[-1] - title_font.size
    subtitle_gap = 34 if subtitle_lines else 0
    author_gap = 44 if author_lines else 0
    subtitle_height = sum(subtitle_steps)
    if subtitle_lines:
        subtitle_height -= subtitle_steps[-1] - subtitle_font.size
    author_height = sum(author_steps)
    if author_lines:
        author_height -= author_steps[-1] - author_font.size
    stack_height = title_height + subtitle_gap + subtitle_height + author_gap + author_height

    y = bleed_px + (cover_h // 2) - (stack_height // 2)
    x_center = front_x0 + front_w // 2
    for line in title_lines:
        draw.text((x_center, y), line, font=title_font, fill=band_text_color, anchor="ma")
        y += int(title_font.size * 1.08)
    if subtitle_lines:
        y += subtitle_gap
        for line in subtitle_lines:
            draw.text((x_center, y), line, font=subtitle_font, fill=band_text_color, anchor="ma")
            y += int(subtitle_font.size * 1.1)
    if author_lines:
        y += author_gap
        for line in author_lines:
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

    spine_rotated = spine_layer.rotate(-90, expand=True)
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

        # Back cover publisher mark and imprint text, inset clear of the decorative border.
        back_safe_x0 = back_x0 + PANEL_BORDER_MARGIN_PX + BACK_FOOTER_BORDER_GUTTER_PX
        back_safe_x1 = back_x0 + front_w - PANEL_BORDER_MARGIN_PX - BACK_FOOTER_BORDER_GUTTER_PX
        back_safe_y1 = bleed_px + cover_h - PANEL_BORDER_MARGIN_PX - BACK_FOOTER_BORDER_GUTTER_PX
        footer_max_h = min(BACK_FOOTER_MAX_HEIGHT_PX, max(160, back_safe_y1 - bleed_px))

        back_logo = logo_img.copy()
        back_logo_max_h = max(40, footer_max_h)
        back_logo_max_w = max(40, min(BACK_LOGO_MAX_SIZE_PX, int(front_w * 0.18)))
        back_logo.thumbnail((back_logo_max_w, back_logo_max_h), RESAMPLE_LANCZOS)

        imprint = (
            "This book has been republished by Out of Print Press. "
            "Our mission is to make every public domain book available in a quality printed format. "
            "Request that any public domain book be added to our catalog at Outofprint.com"
        )
        back_logo_x = back_safe_x0
        text_x0 = back_logo_x + back_logo.width + 42
        text_x1 = back_safe_x1
        imprint_font = load_font(30, bold=False)
        text_max_w = max(120, text_x1 - text_x0)
        lines = wrap_text(draw, imprint, imprint_font, text_max_w)
        line_step = int(imprint_font.size * 1.2)
        text_h = len(lines) * line_step
        while (text_h > footer_max_h or text_x0 >= text_x1 - 120) and imprint_font.size > 14:
            imprint_font = load_font(imprint_font.size - 2, bold=False)
            lines = wrap_text(draw, imprint, imprint_font, text_max_w)
            line_step = int(imprint_font.size * 1.2)
            text_h = len(lines) * line_step
        max_lines = max(1, footer_max_h // max(1, line_step))
        lines = lines[:max_lines]
        text_h = len(lines) * line_step
        footer_h = min(footer_max_h, max(back_logo.height, text_h))
        footer_y0 = back_safe_y1 - footer_h
        back_logo_y = footer_y0 + (footer_h - back_logo.height) // 2
        text_y = footer_y0 + max(0, (footer_h - text_h) // 2)

        cover.paste(back_logo, (back_logo_x, back_logo_y), back_logo)
        for line in lines:
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
        "cover_color": style.color_name,
        "front_border_pattern": style.front_border_pattern,
        "back_border_pattern": style.back_border_pattern,
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
        self.root.title("Automatic Cover Designer V2")
        self.root.geometry("1360x900")
        self.messages: queue.Queue = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.preview_tk: ImageTk.PhotoImage | None = None
        self.current_cover: Image.Image | None = None

        self.title_var = tk.StringVar()
        self.subtitle_var = tk.StringVar()
        self.author_var = tk.StringVar()
        self.spine_title_var = tk.StringVar()
        self.volume_var = tk.StringVar()
        self.manual_spine_width_var = tk.StringVar()
        self.expand_bleed_var = tk.BooleanVar(value=False)
        self.year_var = tk.StringVar(value="1776")
        self.pages_var = tk.StringVar(value="320")
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
        ttk.Label(form, text="Volume label (optional)").grid(row=2, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.volume_var, width=10).grid(row=2, column=3, sticky="w", padx=(8, 8), pady=(6, 0))
        ttk.Label(form, text="Manual spine width in (optional)").grid(row=3, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.manual_spine_width_var, width=10).grid(row=3, column=3, sticky="w", padx=(8, 8), pady=(6, 0))
        ttk.Checkbutton(form, text='Add 0.125" bleed all around', variable=self.expand_bleed_var).grid(
            row=4, column=2, columnspan=2, sticky="w", pady=(6, 0)
        )

        ttk.Label(form, text="Output folder").grid(row=6, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(form, textvariable=self.output_var, width=70).grid(row=6, column=1, columnspan=2, sticky="ew", padx=(8, 8), pady=(10, 0))
        ttk.Button(form, text="Browse", command=self._choose_output_dir).grid(row=6, column=3, sticky="w", pady=(10, 0))
        form.columnconfigure(1, weight=1)

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(12, 6))
        self.generate_button = ttk.Button(controls, text="Generate Cover", command=self.start_generate)
        self.generate_button.grid(row=0, column=0, sticky="w")
        self.save_button = ttk.Button(controls, text="Save Full Cover", command=self.save_cover)
        self.save_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(controls, textvariable=self.status_var).grid(row=0, column=2, sticky="w", padx=(12, 0))

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
            "year": year,
            "page_count": page_count,
            "manual_spine_width_in": manual_spine_width_in,
            "expand_with_bleed": bool(self.expand_bleed_var.get()),
            "output_dir": output_dir,
        }

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self.generate_button.config(state=state)
        self.save_button.config(state="normal" if (not busy and self.current_cover is not None) else "disabled")

    def start_generate(self):
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
        self.progress["maximum"] = 2
        self.status_var.set("Drawing solid-color cover...")
        self.worker_thread = threading.Thread(target=self._generate_worker, args=(cfg,), daemon=True)
        self.worker_thread.start()

    def _generate_worker(self, cfg: dict[str, Any]):
        try:
            style = style_for_year(cfg["year"])
            self.messages.put(("progress", (1, 2)))
            cover, metrics = compose_full_cover(
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
            self.messages.put(("progress", (2, 2)))
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
                        f"Century style: {style.label} | Cover color: {style.color_name} | "
                        f"Front border: {style.front_border_pattern} | Back border: {style.back_border_pattern}"
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
