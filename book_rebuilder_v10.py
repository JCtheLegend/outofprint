#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
from openai import OpenAI
from PIL import Image


DEFAULT_MODEL = "gpt-5.4"
DEFAULT_API_KEY = "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"
DEFAULT_DPI = 240
DEFAULT_MAX_IMAGE_SIDE = 2600
DEFAULT_PAGE_BREAK = r"\clearpage"
DEFAULT_NOTES_HEADING = "Notes"

BODY_KINDS = {"paragraph", "quote", "poetry", "list_item", "illustration_caption", "table"}
HEADING_KINDS = {"title", "chapter_title", "section_title", "subtitle"}
NOTE_KINDS = {"footnote", "marginal_note"}
INLINE_NOTE_RE = re.compile(r"\{\{fn:([^{}]+)\}\}")
PRINTED_NUMERIC_NOTE_RE = re.compile(r"(?<![A-Za-z0-9])\((\d{1,3})\.?\)")
MODEL_PRICES_PER_1M: dict[str, dict[str, float]] = {
    "gpt-5.5": {"input": 5.00, "cached_input": 0.50, "output": 30.00},
    "gpt-5.4-mini": {"input": 0.75, "cached_input": 0.075, "output": 4.50},
    "gpt-5.4": {"input": 2.50, "cached_input": 0.25, "output": 15.00},
    "gpt-5.3-codex": {"input": 1.75, "cached_input": 0.175, "output": 14.00},
    "gpt-5.2": {"input": 1.75, "cached_input": 0.175, "output": 14.00},
    "gpt-4.1-mini": {"input": 0.40, "cached_input": 0.10, "output": 1.60},
    "gpt-4.1": {"input": 2.00, "cached_input": 0.50, "output": 8.00},
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
    "gpt-4o": {"input": 2.50, "cached_input": 1.25, "output": 10.00},
}


EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page_index": {"type": "integer"},
                    "printed_page_label": {"type": "string"},
                    "running_header": {"type": "string"},
                    "blocks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {
                                    "type": "string",
                                    "enum": [
                                        "title",
                                        "chapter_title",
                                        "section_title",
                                        "subtitle",
                                        "paragraph",
                                        "quote",
                                        "poetry",
                                        "list_item",
                                        "footnote",
                                        "illustration_caption",
                                        "page_number",
                                        "table",
                                        "other",
                                    ],
                                },
                                "text": {"type": "string"},
                                "footnote_marker": {"type": "string"},
                                "anchor_text": {"type": "string"},
                                "starts_new_paragraph": {"type": "boolean"},
                                "level": {"type": "integer"},
                            },
                            "required": ["kind", "text", "footnote_marker", "anchor_text", "starts_new_paragraph", "level"],
                            "additionalProperties": False,
                        },
                    },
                    "notes": {"type": "string"},
                },
                "required": ["page_index", "printed_page_label", "running_header", "blocks", "notes"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["pages"],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """You extract scanned public-domain book pages into structured JSON for publication-quality rebuilding.

Transcription rules:
- Preserve only visible source text from the page image.
- Keep original spelling, punctuation, capitalization, italics implied by text, and quotation marks when readable.
- Do not paraphrase, summarize, modernize, translate, correct printer errors, or fill missing text from context.
- If a word is split only because it wraps across a printed line, join it and remove the line-break hyphen.
- Preserve true hyphenated compounds.
- If a word or sentence is cut off at the bottom of the scan page, do not complete it from context or from a neighboring page. Transcribe only the visible text on this page and leave the cutoff visible.
- If a page begins with the continuation of a cut-off sentence from the previous page, transcribe only the visible continuation on this page and set starts_new_paragraph=false unless the line is visibly indented as a new paragraph.
- If a character or word is unreadable, omit the unreadable part rather than inventing it.

Block rules:
- Return body text in reading order.
- Exclude running headers and page numbers from body blocks. Put a running header only in running_header.
- Ignore side notes and margin notes completely. Do not transcribe them, do not include them as blocks, and do not let them split or indent body paragraphs.
- Treat text printed below a horizontal footnote separator/rule as footnote text, not body text.
- Older books often have only one or two wide body lines at the top of a page, followed by a horizontal rule and a full page of smaller two-column notes. In that layout, only the text above the rule is body text; every line below the rule is footnote text.
- Smaller type, two-column text below a rule is always footnote text, even if it reads like ordinary prose, cites cases or authors, begins with a capital letter, or continues a sentence from a previous note.
- Footnotes may continue onto following pages, may be printed in multiple columns, and may begin without any marker on the continuation page. Classify every continuation paragraph as kind footnote with an empty footnote_marker.
- A footnote continuation can start with a capital letter or a new sentence; that does not make it body text.
- Do not create a new paragraph because of a scan page break.
- A real paragraph beginning is visible by first-line indentation, except for the first body paragraph after a chapter/title heading.
- Before transcribing body text, inspect the left edge of each printed line and identify every first-line indent.
- Never combine two visibly separate printed paragraphs into one JSON block.
- Every visible first-line indent in the body text starts a new paragraph block, even when it occurs in the middle of the same scan page, even when the previous paragraph ends without extra vertical space, and even when both paragraphs discuss the same subject.
- If a body paragraph is followed by another indented body paragraph on the same image, end the current JSON block before the indented line and start a new paragraph block at that indented line.
- Do not use one long paragraph block for a whole page of body text. A paragraph block must correspond to exactly one printed paragraph, not a section, page, or run of related prose.
- A new paragraph is determined by visible indentation and layout, not by whether the sentence continues the same topic.
- If body text begins at the top of a scanned page and is not visibly first-line indented, it is a continuation of the previous paragraph even when it begins with a capital letter or a new sentence.
- Keep true paragraph boundaries, block quotes, poetry, lists, tables, captions, chapter titles, and section headings distinct.
- Use chapter_title only for a real chapter-opening heading, not for repeated top-of-page headers.
- Bottom notes are footnote blocks. Side or margin notes are page furniture and must be omitted.
- If a page has body text above a separator line and note text below that line, keep the above-line text as body and all below-line text as footnote blocks.
- If the separator line appears high on the page, do not promote the large note area below it to body text. A page may legitimately contain less body text than notes.
- A footnote area may span more than one scan page. Continue classifying the small-print note area as footnote until the main body text resumes above the next separator or at the normal body-text position.
- For paragraph blocks, starts_new_paragraph must be true only when the first line is visibly indented as a new paragraph, or when it is the first body paragraph after a chapter/title heading.
- For a paragraph that continues from previous page text without visible first-line indentation, starts_new_paragraph must be false.
- When starts_new_paragraph is true, that block must not contain text from any later visibly indented paragraph.
- For non-paragraph blocks, starts_new_paragraph must be false.

Footnote rules:
- In body text, replace every visible inline footnote call marker with {{fn:MARKER}}, where MARKER is the original printed marker such as *, dagger, 1, a, or double-dagger.
- Do not leave the original footnote marker in body text outside that placeholder.
- For a footnote block, put the original printed marker in footnote_marker and put the note text without that leading marker in text.
- If a footnote continues without a visible marker, leave footnote_marker empty and transcribe the continuation as a footnote block.
- If a long footnote spans multiple pages, keep returning each continuation paragraph as a footnote block with an empty footnote_marker until the printed footnote area ends.
- For non-note blocks, footnote_marker and anchor_text must be empty.

Return JSON only and follow the schema exactly.
"""


USER_TEMPLATE = """Extract these scanned book pages into structured JSON.

Absolute zero-based PDF page indices in image order: {page_indices}

For each image:
- Use the matching page_index from the list above.
- Transcribe only text visibly present on that image.
- Do not infer missing text from neighboring pages.
- Do not complete a bottom-of-page cutoff using text from a following page.
- Do not move text from a following page into the current page's final paragraph.
- Preserve true paragraph boundaries, but do not preserve printed line breaks inside normal paragraphs.
- One visible printed paragraph equals one paragraph block. Do not merge adjacent indented paragraphs into a single block.
- Before returning JSON, check that each visibly indented first line in the body has become the start of its own paragraph block.
- When a first line is visibly indented, start a new paragraph block there even if there is no extra vertical space before it.
- Exclude running headers, page numbers, side notes, and margin notes from body text.
- Treat all text below a horizontal footnote separator/rule as footnote text, including page-spanning continuations without markers.
- If a horizontal rule separates a short top body area from a large lower note area, the lower area is footnotes even when it occupies most of the page.
- Do not classify smaller two-column note text below a separator as paragraph text.
- Footnote continuations may start with capital letters and may be split into multiple columns; keep them as footnote blocks, not paragraphs.
- Ignore margin notes completely; do not include them in any block and do not allow them to create paragraph breaks or indentation.
- A new paragraph requires a visible first-line indent, except for the first body paragraph after a chapter/title heading.
- If there are several visible indents on the page, return several paragraph blocks.
- If text starts at the top of the scan page without a visible first-line indent, mark starts_new_paragraph=false so it can continue the previous paragraph.
- Replace inline footnote markers in body text with {{{{fn:MARKER}}}} placeholders.
- Keep bottom footnote text as footnote blocks with their source marker when visible.
- For footnote continuation text without a marker, use kind=footnote and footnote_marker="".

Return JSON only.
"""


SPLIT_PAGE_TEMPLATE = """Extract one scanned book page from two ordered crops.

Absolute zero-based PDF page index: {page_index}

Crop 1 is the body area above the horizontal footnote separator.
Crop 2 is the note area below the horizontal footnote separator.

Rules for this split page:
- Return exactly one page object with page_index {page_index}.
- Transcribe only text visibly present in these two crops. Do not complete a bottom cutoff from neighboring pages.
- Do not move text from a following page into this page's final paragraph.
- Extract Crop 1 as body text, headings, running header, and ordinary page content.
- In Crop 1, one visible printed paragraph equals one paragraph block. Do not merge adjacent indented paragraphs into a single block.
- In Crop 1, every visible first-line indent starts a new paragraph block, even when there is no extra vertical space before it.
- Before returning JSON, check Crop 1 line starts and make sure every indented body line has become the start of a separate paragraph block.
- Extract Crop 2 only as footnote blocks. Do not return any paragraph, title, subtitle, quote, list_item, or table blocks from Crop 2.
- Ignore side notes and margin notes in both crops.
- If Crop 2 begins mid-note without a visible marker, use kind=footnote and footnote_marker="".
- If Crop 2 has two columns, read all notes in proper reading order and keep them as footnote blocks.
- Do not infer text that is not visible in either crop.

Return JSON only.
"""


@dataclass
class ExtractionResult:
    pages: list[dict[str, Any]]
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChapterNote:
    number: int
    source_marker: str
    source_page: int
    text_parts: list[str] = field(default_factory=list)
    anchor_text: str = ""
    note_kind: str = "footnote"
    matched: bool = False

    @property
    def text(self) -> str:
        return clean_inline_text(" ".join(part for part in self.text_parts if part).strip())


@dataclass
class ModelUsage:
    model: str
    requests: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def add(self, input_tokens: int, cached_input_tokens: int, output_tokens: int, total_tokens: int, requests: int = 1) -> None:
        self.requests += max(0, requests)
        self.input_tokens += max(0, input_tokens)
        self.cached_input_tokens += max(0, cached_input_tokens)
        self.output_tokens += max(0, output_tokens)
        self.total_tokens += max(0, total_tokens)

    @property
    def uncached_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_input_tokens)

    def estimated_cost_usd(self) -> float | None:
        prices = price_for_model(self.model)
        if not prices:
            return None
        return (
            (self.uncached_input_tokens * prices["input"])
            + (self.cached_input_tokens * prices["cached_input"])
            + (self.output_tokens * prices["output"])
        ) / 1_000_000

    def to_dict(self) -> dict[str, Any]:
        prices = price_for_model(self.model)
        cost = self.estimated_cost_usd()
        return {
            "model": self.model,
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "uncached_input_tokens": self.uncached_input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "prices_per_1m_tokens_usd": prices,
            "estimated_cost_usd": None if cost is None else round(cost, 6),
        }


@dataclass
class ApiUsage:
    by_model: dict[str, ModelUsage] = field(default_factory=dict)

    def add_tokens(
        self,
        model: str,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        requests: int = 1,
    ) -> None:
        model_usage = self.by_model.setdefault(model, ModelUsage(model=model))
        model_usage.add(input_tokens, cached_input_tokens, output_tokens, total_tokens, requests=requests)

    def add_response_usage(self, model: str, usage: Any) -> None:
        input_tokens, cached_input_tokens, output_tokens, total_tokens = parse_response_usage(usage)
        self.add_tokens(model, input_tokens, cached_input_tokens, output_tokens, total_tokens)

    def add_saved_usage(self, usage: dict[str, Any]) -> None:
        if not usage:
            return
        if "by_model" in usage:
            for model, model_usage in usage.get("by_model", {}).items():
                self.add_tokens(
                    str(model_usage.get("model") or model),
                    int(model_usage.get("input_tokens", 0) or 0),
                    int(model_usage.get("cached_input_tokens", 0) or 0),
                    int(model_usage.get("output_tokens", 0) or 0),
                    int(model_usage.get("total_tokens", 0) or 0),
                    requests=int(model_usage.get("requests", 1) or 1),
                )
            return
        self.add_tokens(
            str(usage.get("model", "unknown")),
            int(usage.get("input_tokens", 0) or 0),
            int(usage.get("cached_input_tokens", 0) or 0),
            int(usage.get("output_tokens", 0) or 0),
            int(usage.get("total_tokens", 0) or 0),
            requests=int(usage.get("requests", 1) or 1),
        )

    @property
    def requests(self) -> int:
        return sum(usage.requests for usage in self.by_model.values())

    @property
    def input_tokens(self) -> int:
        return sum(usage.input_tokens for usage in self.by_model.values())

    @property
    def cached_input_tokens(self) -> int:
        return sum(usage.cached_input_tokens for usage in self.by_model.values())

    @property
    def output_tokens(self) -> int:
        return sum(usage.output_tokens for usage in self.by_model.values())

    @property
    def total_tokens(self) -> int:
        return sum(usage.total_tokens for usage in self.by_model.values())

    def estimated_cost_usd(self) -> float | None:
        costs = [usage.estimated_cost_usd() for usage in self.by_model.values()]
        known_costs = [cost for cost in costs if cost is not None]
        if len(known_costs) != len(costs):
            return None
        return sum(known_costs)

    def summary_line(self) -> str:
        cost = self.estimated_cost_usd()
        cost_text = "unknown price" if cost is None else f"${cost:.4f}"
        return (
            f"API usage: {self.requests} request(s), {self.input_tokens:,} input tokens "
            f"({self.cached_input_tokens:,} cached), {self.output_tokens:,} output tokens, "
            f"{self.total_tokens:,} total tokens, estimated cost {cost_text}."
        )

    def to_dict(self) -> dict[str, Any]:
        cost = self.estimated_cost_usd()
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "uncached_input_tokens": max(0, self.input_tokens - self.cached_input_tokens),
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": None if cost is None else round(cost, 6),
            "by_model": {model: usage.to_dict() for model, usage in sorted(self.by_model.items())},
        }


def log(message: str) -> None:
    print(message, flush=True)


def price_for_model(model: str) -> dict[str, float] | None:
    normalized = (model or "").lower().strip()
    if normalized in MODEL_PRICES_PER_1M:
        return MODEL_PRICES_PER_1M[normalized]
    for name in sorted(MODEL_PRICES_PER_1M, key=len, reverse=True):
        if normalized.startswith(name):
            return MODEL_PRICES_PER_1M[name]
    return None


def usage_value(container: Any, key: str, default: int = 0) -> int:
    if container is None:
        return default
    value: Any
    if isinstance(container, dict):
        value = container.get(key, default)
    else:
        value = getattr(container, key, default)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def parse_response_usage(usage: Any) -> tuple[int, int, int, int]:
    input_tokens = usage_value(usage, "input_tokens") or usage_value(usage, "prompt_tokens")
    output_tokens = usage_value(usage, "output_tokens") or usage_value(usage, "completion_tokens")
    total_tokens = usage_value(usage, "total_tokens") or (input_tokens + output_tokens)

    if isinstance(usage, dict):
        details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    else:
        details = getattr(usage, "input_tokens_details", None) or getattr(usage, "prompt_tokens_details", None) or {}
    cached_input_tokens = usage_value(details, "cached_tokens") or usage_value(details, "cached_input_tokens")
    return input_tokens, cached_input_tokens, output_tokens, total_tokens


def clean_inline_text(text: str) -> str:
    text = str(text or "")
    text = text.replace("\u00ad", "").replace("\ufffe", "").replace("\ufffd", "")
    text = re.sub(r"[\u200b\u200c\u200d]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def paragraph_text(text: str) -> str:
    text = clean_inline_text(text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r" {2,}", " ", text).strip()


def escape_latex(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "%": r"\%",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def normalize_blank_lines(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def is_chapter_label_artifact(text: str) -> bool:
    return bool(re.fullmatch(r"Ch\.?\s*[IVXLCDM0-9]+\.?", paragraph_text(text), re.I))


def is_page_artifact_block(text: str) -> bool:
    text = paragraph_text(text)
    if is_chapter_label_artifact(text):
        return True
    if re.fullmatch(r"PRELIM\.?\s*MARIES\.?", text, re.I):
        return True
    if re.fullmatch(r"VOL\.?\s+[IVXLCDM]+\.?\s+[A-Z]", text, re.I):
        return True
    if re.fullmatch(r"[A-Z]\s*\d+", text):
        return True
    return False


def remove_inline_margin_note_artifacts(text: str) -> str:
    text = re.sub(r"\s*\{\{fn:[^{}]+\}\}\.\s+What\s+", " ", text)
    return re.sub(r" {2,}", " ", text).strip()


def remove_inline_chapter_artifacts(text: str) -> str:
    text = re.sub(r"(?<![A-Za-z])Ch\.?\s*[IVXLCDM0-9]+\.?", " ", text, flags=re.I)
    return re.sub(r" {2,}", " ", text).strip()


def repair_hyphenation(text: str) -> str:
    text = re.sub(r"\b([A-Za-z]{2,})-\n\s*\n([a-z]{2,})\b", r"\1\2", text)
    text = re.sub(r"\b([A-Za-z]{2,})-\n([a-z]{2,})\b", r"\1\2", text)
    text = re.sub(r"\b([A-Za-z]{2,})-[ \t]+([a-z]{2,})\b", r"\1\2", text)
    return text


def should_merge_paragraphs(prev_text: str, next_text: str) -> bool:
    prev = paragraph_text(prev_text)
    nxt = paragraph_text(next_text)
    if not prev or not nxt:
        return False
    if prev.endswith("-"):
        return True
    if re.search(r"[.!?][\"')\]]?$", prev):
        return False
    if re.search(r"[:;,\u2014-][\"')\]]?$", prev):
        return True
    if prev[-1].islower():
        return True
    if nxt[0].islower():
        return True
    if re.match(r"^(and|but|for|nor|or|so|yet|of|to|the|a|an|in|on|with)\b", nxt, re.I):
        return True
    return False


def merge_text(prev_text: str, next_text: str) -> str:
    prev = paragraph_text(prev_text)
    nxt = paragraph_text(next_text)
    if not prev:
        return nxt
    if not nxt:
        return prev
    if prev.endswith("-"):
        return prev[:-1] + nxt
    return prev + " " + nxt


def page_index_from_image_name(path: Path, fallback: int) -> int:
    match = re.search(r"page[_-](\d+)", path.stem, re.I)
    if match:
        return int(match.group(1)) - 1
    return fallback


def data_url_for_image(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def detect_footnote_separator_y(path: Path) -> int | None:
    with Image.open(path) as raw:
        image = raw.convert("L")
        width, height = image.size
        if width < 100 or height < 100:
            return None
        pixels = image.load()
        x0 = int(width * 0.06)
        x1 = int(width * 0.94)
        min_y = int(height * 0.10)
        max_y = int(height * 0.88)
        min_dark_pixels = int(width * 0.55)
        dark_rows: list[tuple[int, int]] = []
        for y in range(min_y, max_y):
            dark_count = 0
            for x in range(x0, x1):
                if pixels[x, y] < 100:
                    dark_count += 1
            if dark_count >= min_dark_pixels:
                dark_rows.append((y, dark_count))

    if not dark_rows:
        return None

    groups: list[list[tuple[int, int]]] = []
    for y, dark_count in dark_rows:
        if not groups or y > groups[-1][-1][0] + 3:
            groups.append([])
        groups[-1].append((y, dark_count))

    candidates: list[tuple[int, int, int]] = []
    for group in groups:
        y = sum(row for row, _ in group) // len(group)
        max_dark = max(dark_count for _, dark_count in group)
        candidates.append((y, max_dark, len(group)))
    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[1], item[0]))
    separator_y = candidates[0][0]
    if separator_y < int(height * 0.12) or separator_y > int(height * 0.82):
        return None
    return separator_y


def crop_page_around_separator(path: Path, separator_y: int, folder: Path) -> tuple[Path, Path]:
    with Image.open(path) as raw:
        image = raw.convert("RGB")
        width, height = image.size
        margin = max(8, int(height * 0.006))
        body_bottom = max(1, separator_y - margin)
        notes_top = min(height - 1, separator_y + margin)
        body = image.crop((0, 0, width, body_bottom))
        notes = image.crop((0, notes_top, width, height))
        body_path = folder / f"{path.stem}_body.png"
        notes_path = folder / f"{path.stem}_notes.png"
        body.save(body_path)
        notes.save(notes_path)
    return body_path, notes_path


def resize_image_if_needed(path: Path, max_side: int) -> None:
    if max_side <= 0:
        return
    with Image.open(path) as raw:
        image = raw.convert("RGB")
        if max(image.size) <= max_side:
            return
        image.thumbnail((max_side, max_side))
        image.save(path)


def render_pdf_pages(
    pdf_path: Path,
    images_dir: Path,
    dpi: int,
    start_page: int,
    page_count: int | None,
    max_image_side: int,
    log_fn=log,
) -> list[Path]:
    images_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    with fitz.open(pdf_path) as doc:
        total_pages = doc.page_count
        start = max(0, start_page)
        end = total_pages if page_count is None else min(total_pages, start + max(0, page_count))
        if start >= end:
            raise ValueError("No PDF pages selected for rendering.")
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        for source_index in range(start, end):
            out_path = images_dir / f"page_{source_index + 1:04d}.png"
            page = doc.load_page(source_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            pix.save(out_path)
            resize_image_if_needed(out_path, max_side=max_image_side)
            paths.append(out_path)
            log_fn(f"Rendered source page {source_index + 1}/{total_pages} -> {out_path.name}")
    return paths


def list_image_pages(images_dir: Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    paths = [path for path in images_dir.iterdir() if path.is_file() and path.suffix.lower() in exts]
    return sorted(paths, key=lambda path: path.name.lower())


class OpenAIPageExtractor:
    def __init__(
        self,
        api_key: str,
        model: str,
        detail: str,
        max_retries: int,
        timeout: float,
        log_fn=log,
    ) -> None:
        self.client = OpenAI(api_key=api_key, timeout=timeout)
        self.model = model
        self.detail = detail
        self.max_retries = max_retries
        self.log_fn = log_fn
        self.usage = ApiUsage()

    def extract_batch(self, page_paths: list[Path], page_indices: list[int]) -> ExtractionResult:
        if len(page_paths) == 1 and len(page_indices) == 1:
            separator_y = detect_footnote_separator_y(page_paths[0])
            if separator_y is not None:
                self.log_fn(f"Detected footnote separator in {page_paths[0].name}; extracting body and note areas separately.")
                return self.extract_split_page(page_paths[0], page_indices[0], separator_y)

        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": USER_TEMPLATE.format(page_indices=page_indices)}
        ]
        for path in page_paths:
            content.append({"type": "input_image", "image_url": data_url_for_image(path), "detail": self.detail})
        return self.extract_with_content(content, page_indices)

    def extract_split_page(self, page_path: Path, page_index: int, separator_y: int) -> ExtractionResult:
        with tempfile.TemporaryDirectory(prefix="book_rebuilder_split_") as tmp:
            body_path, notes_path = crop_page_around_separator(page_path, separator_y, Path(tmp))
            content: list[dict[str, Any]] = [
                {"type": "input_text", "text": SPLIT_PAGE_TEMPLATE.format(page_index=page_index)},
                {"type": "input_text", "text": "Crop 1: body area above the footnote separator."},
                {"type": "input_image", "image_url": data_url_for_image(body_path), "detail": self.detail},
                {"type": "input_text", "text": "Crop 2: note area below the footnote separator. Every transcribed block from this crop must be kind=footnote."},
                {"type": "input_image", "image_url": data_url_for_image(notes_path), "detail": self.detail},
            ]
            return self.extract_with_content(content, [page_index])

    def extract_with_content(self, content: list[dict[str, Any]], page_indices: list[int]) -> ExtractionResult:
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
                {"role": "user", "content": content},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "scanned_book_pages",
                    "strict": True,
                    "schema": EXTRACTION_SCHEMA,
                }
            },
        }

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.responses.create(**payload)
                usage = getattr(response, "usage", None)
                input_tokens, cached_input_tokens, output_tokens, total_tokens = parse_response_usage(usage)
                self.usage.add_tokens(self.model, input_tokens, cached_input_tokens, output_tokens, total_tokens)
                data = json.loads(response.output_text)
                pages = data.get("pages", [])
                if not isinstance(pages, list):
                    raise ValueError("Structured response did not contain a pages list.")
                expected = set(page_indices)
                received = {int(page.get("page_index", -1)) for page in pages}
                if received != expected:
                    raise ValueError(f"Response page indices {sorted(received)} did not match expected {sorted(expected)}.")
                return ExtractionResult(
                    pages=pages,
                    usage={
                        "model": self.model,
                        "input_tokens": input_tokens,
                        "cached_input_tokens": cached_input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": total_tokens,
                    },
                )
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                delay = min(2**attempt, 30)
                self.log_fn(f"OpenAI extraction attempt {attempt} failed: {exc}. Retrying in {delay}s.")
                time.sleep(delay)
        raise RuntimeError(f"Failed to extract batch after {self.max_retries} attempts: {last_error}") from last_error


def load_or_extract_batches(
    extractor: OpenAIPageExtractor,
    page_paths: list[Path],
    json_dir: Path,
    pages_per_batch: int,
    resume: bool,
    log_fn=log,
) -> list[dict[str, Any]]:
    json_dir.mkdir(parents=True, exist_ok=True)
    all_pages: list[dict[str, Any]] = []
    batches = list(range(0, len(page_paths), pages_per_batch))
    total_batches = len(batches)

    for batch_number, start in enumerate(batches, start=1):
        batch_paths = page_paths[start : start + pages_per_batch]
        batch_indices = [page_index_from_image_name(path, fallback=start + offset) for offset, path in enumerate(batch_paths)]
        batch_file = json_dir / f"batch_{batch_number:04d}.json"
        if resume and batch_file.exists():
            payload = json.loads(batch_file.read_text(encoding="utf-8"))
            if payload.get("page_indices") == batch_indices:
                log_fn(f"Reusing {batch_file.name}")
                extractor.usage.add_saved_usage(payload.get("usage", {}))
                all_pages.extend(payload["pages"])
                continue
            log_fn(f"Ignoring {batch_file.name}; saved pages do not match the current selection.")

        first_page = batch_indices[0] + 1
        last_page = batch_indices[-1] + 1
        log_fn(f"Extracting batch {batch_number}/{total_batches} (source pages {first_page}-{last_page})")
        result = extractor.extract_batch(batch_paths, batch_indices)
        batch_payload = {"page_indices": batch_indices, "pages": result.pages, "usage": result.usage}
        batch_file.write_text(json.dumps(batch_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        all_pages.extend(result.pages)

    all_pages.sort(key=lambda page: int(page.get("page_index", 0)))
    return all_pages


def normalize_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pages = sorted(pages, key=lambda page: int(page.get("page_index", 0)))
    for page in pages:
        cleaned_blocks: list[dict[str, Any]] = []
        for block in page.get("blocks", []):
            kind = str(block.get("kind", "other"))
            text = clean_inline_text(block.get("text", ""))
            if not text and kind not in NOTE_KINDS:
                continue
            if kind in {"page_number"}:
                continue
            if kind in BODY_KINDS | {"other"} and is_page_artifact_block(text):
                continue
            if kind in BODY_KINDS:
                text = remove_inline_chapter_artifacts(text)
                text = remove_inline_margin_note_artifacts(text)
            if kind == "other" and not text:
                continue
            normalized = {
                "kind": kind,
                "text": text,
                "footnote_marker": clean_inline_text(block.get("footnote_marker", "")),
                "anchor_text": clean_inline_text(block.get("anchor_text", "")),
                "starts_new_paragraph": bool(block.get("starts_new_paragraph", True if kind == "paragraph" else False)),
                "level": int(block.get("level", 0) or 0),
            }
            cleaned_blocks.append(normalized)
        page["blocks"] = merge_adjacent_heading_blocks(cleaned_blocks)
    return merge_page_break_paragraphs(pages)


def merge_adjacent_heading_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for block in blocks:
        kind = block.get("kind")
        text = paragraph_text(block.get("text", ""))
        if (
            merged
            and kind in {"title", "chapter_title", "section_title", "subtitle"}
            and merged[-1].get("kind") == kind
            and text
        ):
            prev_text = paragraph_text(merged[-1].get("text", ""))
            separator = " " if prev_text and not prev_text.endswith("-") else ""
            merged[-1]["text"] = (prev_text.rstrip("-") + separator + text).strip()
            continue
        merged.append(block)
    return merged


def merge_page_break_paragraphs(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changed = True
    while changed:
        changed = False
        for index in range(len(pages)):
            current_blocks = pages[index].get("blocks", [])
            current_i = None
            for i in range(len(current_blocks) - 1, -1, -1):
                kind = current_blocks[i].get("kind")
                if kind == "paragraph" and paragraph_text(current_blocks[i].get("text", "")):
                    current_i = i
                    break
                if kind in HEADING_KINDS:
                    break
            if current_i is None:
                continue

            target: tuple[list[dict[str, Any]], int] | None = None
            for next_page in pages[index:]:
                next_blocks = next_page.get("blocks", [])
                start_at = current_i + 1 if next_page is pages[index] else 0
                for i, block in enumerate(next_blocks[start_at:], start=start_at):
                    kind = block.get("kind")
                    if kind in HEADING_KINDS:
                        target = None
                        break
                    if kind == "paragraph" and paragraph_text(block.get("text", "")):
                        target = (next_blocks, i)
                        break
                if target is not None:
                    break
                if any(block.get("kind") in HEADING_KINDS for block in next_blocks[start_at:]):
                    break

            if target is None:
                continue
            target_blocks, target_i = target
            prev_text = current_blocks[current_i].get("text", "")
            next_text = target_blocks[target_i].get("text", "")
            starts_new = bool(target_blocks[target_i].get("starts_new_paragraph", True))
            if not starts_new:
                current_blocks[current_i]["text"] = merge_text(prev_text, next_text)
                target_blocks.pop(target_i)
                changed = True
                break
    return pages


def escape_markdown_heading(text: str) -> str:
    text = paragraph_text(text)
    return text.replace("\n", " ").strip()


def raw_center_heading(text: str, size: str = r"\Large", shape: str = r"\scshape") -> str:
    heading = escape_latex(escape_markdown_heading(text))
    return "\n".join([
        r"\begin{center}",
        rf"{{{size} {shape} {heading}}}",
        r"\end{center}",
    ])


def raw_notes_heading(text: str = DEFAULT_NOTES_HEADING) -> str:
    return "\n".join([
        r"\par\bigskip",
        r"\begin{center}",
        rf"{{\large\scshape {escape_latex(text)}}}",
        r"\end{center}",
        r"\smallskip",
    ])


def is_major_division_heading(text: str) -> bool:
    text = paragraph_text(text)
    if not text:
        return False
    normalized = re.sub(r"\s+", " ", text).strip(" .").upper()
    if normalized in {"PREFACE", "INTRODUCTION", "PROLOGUE", "THE LAW OF NATIONS"}:
        return True
    if normalized.startswith("PRELIMINARIES"):
        return True
    if re.fullmatch(r"(BOOK|PART|VOLUME|VOL)\.?\s+([IVXLCDM]+|\d+)", normalized):
        return True
    return False


def raw_title_page(title: str = "", subtitle: str = "", author: str = "", publication_date: str = "", rights: str = "") -> str:
    parts: list[str] = [
        r"\begin{titlepage}",
        r"\thispagestyle{empty}",
        r"\centering",
        r"\vspace*{1.3in}",
    ]
    if title:
        parts.extend([
            rf"{{\fontsize{{24}}{{30}}\selectfont\bfseries {escape_latex(title)}\par}}",
            r"\vspace{0.35in}",
        ])
    if subtitle:
        parts.extend([
            rf"{{\fontsize{{15}}{{20}}\selectfont {escape_latex(subtitle)}\par}}",
            r"\vspace{0.65in}",
        ])
    else:
        parts.append(r"\vspace{0.3in}")
    if author:
        parts.extend([
            rf"{{\large {escape_latex(author)}\par}}",
            r"\vspace{0.35in}",
        ])
    if publication_date:
        parts.extend([
            rf"{{\normalsize {escape_latex(publication_date)}\par}}",
            r"\vfill",
        ])
    else:
        parts.append(r"\vfill")
    if rights:
        parts.append(rf"{{\footnotesize {escape_latex(rights)}\par}}")
    parts.extend([
        r"\end{titlepage}",
        r"\clearpage",
    ])
    return "\n".join(parts)


def format_quote(text: str) -> str:
    lines = [line.strip() for line in clean_inline_text(text).splitlines()]
    lines = lines or [paragraph_text(text)]
    return "\n".join(f"> {line}" if line else ">" for line in lines)


def format_poetry(text: str) -> str:
    lines = clean_inline_text(text).splitlines()
    if len(lines) <= 1:
        return paragraph_text(text)
    return "\n".join(line.rstrip() + "  " if line.strip() else "" for line in lines).rstrip()


def find_note_for_marker(
    notes: list[ChapterNote],
    marker: str,
    page_index: int,
    preferred_anchor: str = "",
) -> int | None:
    marker_norm = marker_key(marker)
    unmatched = [i for i, note in enumerate(notes) if not note.matched]
    if not unmatched:
        return None

    same_marker = [i for i in unmatched if marker_key(notes[i].source_marker) == marker_norm]
    if same_marker:
        same_or_prior_page = [i for i in same_marker if notes[i].source_page <= page_index]
        if same_or_prior_page:
            return same_or_prior_page[0]
        return same_marker[0]

    if preferred_anchor:
        anchor = preferred_anchor.lower()
        anchored = [
            i
            for i in unmatched
            if notes[i].anchor_text and (notes[i].anchor_text.lower() in anchor or anchor in notes[i].anchor_text.lower())
        ]
        if anchored:
            return anchored[0]

    if marker_norm and marker_norm != "?":
        return None

    same_page = [i for i in unmatched if notes[i].source_page == page_index]
    if same_page:
        return same_page[0]
    return unmatched[0]


def looks_like_note_continuation(text: str) -> bool:
    text = paragraph_text(text)
    if not text:
        return False
    if text[0].islower() or text[0] in ",;:)]}":
        return True
    return False


def marker_key(marker: str) -> str:
    marker = clean_inline_text(marker).lower()
    marker = marker.strip("()[]{} \t\n\r.")
    marker = re.sub(r"\s+", "", marker)
    return marker


def note_text_can_continue(text: str) -> bool:
    text = paragraph_text(text)
    if not text:
        return False
    if text.endswith("-"):
        return True
    if re.search(r"[,;:\u2014][\"')\]]?$", text):
        return True
    return False


def assemble_markdown(
    pages: list[dict[str, Any]],
    page_break: str = DEFAULT_PAGE_BREAK,
    include_source_comments: bool = False,
    include_marginal_notes: bool = False,
    title: str = "",
    subtitle: str = "",
    author: str = "",
    publication_date: str = "",
    rights: str = "",
) -> tuple[str, dict[str, Any]]:
    pages = normalize_pages(pages)
    lines: list[str] = []
    notes: list[ChapterNote] = []
    footnote_number = 1
    chapter_count = 0
    unresolved_references = 0
    orphan_notes = 0
    suppress_next_paragraph_indent = False

    def emit(text: str = "") -> None:
        lines.append(text)

    def emit_body_paragraph(text: str) -> None:
        nonlocal suppress_next_paragraph_indent
        text = paragraph_text(text)
        if suppress_next_paragraph_indent:
            emit(r"\noindent " + text)
            suppress_next_paragraph_indent = False
        else:
            emit(text)
        emit("")

    if any(clean_inline_text(value) for value in [title, subtitle, author, publication_date, rights]):
        emit(raw_title_page(title=title, subtitle=subtitle, author=author, publication_date=publication_date, rights=rights))
        emit("")

    def flush_notes() -> None:
        nonlocal notes, footnote_number, unresolved_references, suppress_next_paragraph_indent
        if not notes:
            footnote_number = 1
            return
        suppress_next_paragraph_indent = False
        emit("")
        emit(raw_notes_heading())
        emit("")
        emit(r"\begin{list}{}{%")
        emit(r"  \setlength{\leftmargin}{2.8em}%")
        emit(r"  \setlength{\labelwidth}{2.1em}%")
        emit(r"  \setlength{\labelsep}{0.45em}%")
        emit(r"  \setlength{\itemindent}{0pt}%")
        emit(r"  \setlength{\itemsep}{0.35\baselineskip}%")
        emit(r"  \setlength{\parsep}{0pt}%")
        emit(r"  \setlength{\topsep}{0.4\baselineskip}%")
        emit(r"}")
        for note in notes:
            note_text = note.text
            if not note_text:
                note_text = "[Footnote text not found in extracted scan.]"
                unresolved_references += 1
            emit(rf"\item[{{[{note.number}]}}] {escape_latex(note_text)}")
        emit(r"\end{list}")
        emit("")
        notes = []
        footnote_number = 1

    def make_note_ref(marker: str, page_index: int, anchor_text: str = "", note_kind: str = "footnote") -> str:
        nonlocal footnote_number
        marker = clean_inline_text(marker) or "?"
        normalized_marker = marker_key(marker)
        for note in reversed(notes):
            if not note.matched and note.source_page == page_index and marker_key(note.source_marker) == normalized_marker:
                return f"[{note.number}]"
        number = footnote_number
        footnote_number += 1
        notes.append(
            ChapterNote(
                number=number,
                source_marker=marker,
                source_page=page_index,
                anchor_text=paragraph_text(anchor_text),
                note_kind=note_kind,
            )
        )
        return f"[{number}]"

    def replace_inline_refs(text: str, page_index: int, page_marker_keys: set[str]) -> str:
        def repl(match: re.Match[str]) -> str:
            marker = match.group(1)
            if marker_key(marker) not in page_marker_keys:
                return ""
            return make_note_ref(marker, page_index)

        return INLINE_NOTE_RE.sub(repl, text)

    def replace_printed_numeric_refs(text: str, page_index: int, page_marker_keys: set[str]) -> str:
        def repl(match: re.Match[str]) -> str:
            marker = marker_key(match.group(1))
            if marker not in page_marker_keys:
                return match.group(0)
            return make_note_ref(marker, page_index)

        return PRINTED_NUMERIC_NOTE_RE.sub(repl, text)

    def replace_all_refs(text: str, page_index: int, page_marker_keys: set[str]) -> str:
        text = replace_inline_refs(text, page_index, page_marker_keys)
        return replace_printed_numeric_refs(text, page_index, page_marker_keys)

    def last_note_with_text_index() -> int | None:
        for index in range(len(notes) - 1, -1, -1):
            if notes[index].text_parts or notes[index].matched:
                return index
        if notes:
            return len(notes) - 1
        return None

    def continuation_note_index() -> int | None:
        for index in range(len(notes) - 1, -1, -1):
            if notes[index].text_parts and note_text_can_continue(notes[index].text):
                return index
        return last_note_with_text_index()

    def append_note_continuation(index: int, text: str) -> None:
        notes[index].text_parts.append(text)
        notes[index].matched = True

    def add_note_block(block: dict[str, Any], page_index: int) -> None:
        nonlocal footnote_number, orphan_notes
        kind = block.get("kind", "footnote")
        text = paragraph_text(block.get("text", ""))
        marker = clean_inline_text(block.get("footnote_marker", ""))
        anchor = paragraph_text(block.get("anchor_text", ""))

        if kind == "marginal_note" and anchor:
            ref_index = find_note_for_marker(notes, marker or "?", page_index, preferred_anchor=anchor)
            if ref_index is None or notes[ref_index].matched:
                make_note_ref(marker or "marginal", page_index, anchor_text=anchor, note_kind=kind)
                ref_index = len(notes) - 1
            notes[ref_index].text_parts.append("Sidenote: " + text)
            notes[ref_index].matched = True
            return

        if not marker and notes:
            continuation_index = continuation_note_index()
            if continuation_index is not None:
                append_note_continuation(continuation_index, text)
                return

        ref_index = find_note_for_marker(notes, marker or "?", page_index)
        if ref_index is not None:
            notes[ref_index].text_parts.append(text)
            notes[ref_index].matched = True
            return

        if marker and notes:
            continuation_index = continuation_note_index()
            if continuation_index is not None:
                previous_text = notes[continuation_index].text
                if looks_like_note_continuation(text) or note_text_can_continue(previous_text):
                    append_note_continuation(continuation_index, text)
                    return

        number = footnote_number
        footnote_number += 1
        orphan_notes += 1
        notes.append(
            ChapterNote(
                number=number,
                source_marker=marker or "?",
                source_page=page_index,
                text_parts=[text],
                anchor_text=anchor,
                note_kind=kind,
                matched=True,
            )
        )

    for page in pages:
        page_index = int(page.get("page_index", 0))
        page_marker_keys = {
            marker_key(block.get("footnote_marker", ""))
            for block in page.get("blocks", [])
            if block.get("kind") in NOTE_KINDS and marker_key(block.get("footnote_marker", ""))
        }
        if include_source_comments:
            printed = clean_inline_text(page.get("printed_page_label", "")) or str(page_index + 1)
            emit(f"<!-- source page {page_index + 1}, printed {printed} -->")
            emit("")

        for block in page.get("blocks", []):
            kind = block.get("kind", "other")
            text = clean_inline_text(block.get("text", ""))
            if not text and kind not in NOTE_KINDS:
                continue
            heading_text = paragraph_text(text)
            major_heading = kind in HEADING_KINDS and is_major_division_heading(heading_text)

            if kind == "chapter_title" or major_heading:
                flush_notes()
                already_waiting_for_first_paragraph = suppress_next_paragraph_indent
                previous_nonblank = next((line.strip() for line in reversed(lines) if line.strip()), "")
                previous_last_line = previous_nonblank.splitlines()[-1].strip() if previous_nonblank else ""
                already_after_page_break = previous_last_line in {page_break, r"\clearpage", r"\newpage"}
                if lines and page_break and not already_after_page_break and not already_waiting_for_first_paragraph:
                    emit(page_break)
                    emit("")
                chapter_count += 1
                suppress_next_paragraph_indent = True
                emit(raw_center_heading(replace_all_refs(heading_text, page_index, page_marker_keys), size=r"\Large", shape=r"\scshape"))
                emit("")
                continue

            if kind == "title":
                suppress_next_paragraph_indent = False
                emit(raw_center_heading(replace_all_refs(heading_text, page_index, page_marker_keys), size=r"\Large", shape=r"\scshape"))
                emit("")
                continue

            if kind == "section_title":
                if chapter_count == 0:
                    suppress_next_paragraph_indent = False
                emit(raw_center_heading(replace_all_refs(heading_text, page_index, page_marker_keys), size=r"\large", shape=r"\itshape"))
                emit("")
                continue

            if kind == "subtitle":
                if chapter_count == 0:
                    suppress_next_paragraph_indent = False
                emit(raw_center_heading(replace_all_refs(heading_text, page_index, page_marker_keys), size=r"\normalsize", shape=r"\itshape"))
                emit("")
                continue

            if kind == "paragraph":
                emit_body_paragraph(replace_all_refs(heading_text, page_index, page_marker_keys))
                continue

            if kind == "quote":
                emit(replace_all_refs(format_quote(text), page_index, page_marker_keys))
                emit("")
                continue

            if kind == "poetry":
                emit(replace_all_refs(format_poetry(text), page_index, page_marker_keys))
                emit("")
                continue

            if kind == "list_item":
                emit(f"- {replace_all_refs(paragraph_text(text), page_index, page_marker_keys)}")
                continue

            if kind == "illustration_caption":
                emit(f"*{replace_all_refs(paragraph_text(text), page_index, page_marker_keys)}*")
                emit("")
                continue

            if kind == "table":
                emit("```")
                emit(clean_inline_text(text))
                emit("```")
                emit("")
                continue

            if kind == "marginal_note" and not include_marginal_notes:
                continue

            if kind in NOTE_KINDS:
                add_note_block(block, page_index)
                continue

            if kind == "other" and text:
                emit(replace_all_refs(paragraph_text(text), page_index, page_marker_keys))
                emit("")

    flush_notes()
    markdown = normalize_blank_lines(repair_hyphenation("\n".join(lines)))
    stats = {
        "chapters": chapter_count,
        "footnotes": sum(1 for line in markdown.splitlines() if re.match(r"^\\item\[\{\[\d+\]\}\]", line)),
        "orphan_notes": orphan_notes,
        "unresolved_references": unresolved_references,
    }
    return markdown, stats


def write_outputs(
    output_dir: Path,
    pages: list[dict[str, Any]],
    markdown: str,
    stats: dict[str, Any],
    args: argparse.Namespace,
    log_fn=log,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    book_md = output_dir / "book.md"
    extraction_json = output_dir / "book_extraction.json"
    book_md.write_text(markdown, encoding="utf-8")
    extraction_json.write_text(
        json.dumps(
            {
                "source_pdf": str(args.pdf) if args.pdf else "",
                "source_images": str(args.images) if args.images else "",
                "model": args.model,
                "title": getattr(args, "pdf_title", ""),
                "subtitle": getattr(args, "pdf_subtitle", ""),
                "short_title": getattr(args, "short_title", ""),
                "author": getattr(args, "pdf_author", ""),
                "publication_date": getattr(args, "publication_date", ""),
                "rights": getattr(args, "pdf_rights", ""),
                "selected_source_pages": getattr(args, "selected_source_pages", []),
                "pages": pages,
                "stats": stats,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log_fn(f"Wrote {book_md}")
    log_fn(f"Wrote {extraction_json}")


def build_pdf_from_markdown(
    output_dir: Path,
    title: str = "",
    subtitle: str = "",
    short_title: str = "",
    author: str = "",
    publication_date: str = "",
    rights: str = "",
    template_path: Path | None = None,
    pdf_engine: str = "xelatex",
    output_name: str = "print_ready.pdf",
    log_fn=log,
) -> Path:
    book_md = output_dir / "book.md"
    if not book_md.exists():
        raise FileNotFoundError(f"Markdown file not found: {book_md}")

    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise RuntimeError("Pandoc is not installed or not on PATH; book.md was created but PDF was not built.")

    if pdf_engine and not shutil.which(pdf_engine):
        raise RuntimeError(f"{pdf_engine} is not installed or not on PATH; book.md was created but PDF was not built.")

    template = template_path
    if template is None:
        local_template = Path(__file__).resolve().with_name("printer_template.tex")
        template = local_template if local_template.exists() else None

    out_pdf = output_dir / output_name
    command = [
        pandoc,
        str(book_md),
        "--from",
        "markdown+raw_tex",
        "--pdf-engine",
        pdf_engine,
        "-o",
        str(out_pdf),
    ]
    if template:
        command.extend(["--template", str(template)])
    if title:
        command.extend(["-M", f"title={title}"])
    if subtitle:
        command.extend(["-M", f"subtitle={subtitle}"])
    if short_title:
        command.extend(["-M", f"short-title={short_title}"])
    if author:
        command.extend(["-M", f"author={author}"])
    if publication_date:
        command.extend(["-M", f"publication-date={publication_date}"])
    if rights:
        command.extend(["-M", f"rights={rights}"])

    log_fn("Building print-ready PDF with pandoc.")
    result = subprocess.run(command, cwd=output_dir, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Pandoc PDF build failed: {detail}")

    log_fn(f"Wrote {out_pdf}")
    return out_pdf


def rebuild_book_from_page_paths(
    args: argparse.Namespace,
    page_paths: list[Path],
    log_fn=log,
) -> tuple[Path, dict[str, Any], Path | None]:
    output_dir = args.output_dir.expanduser().resolve()
    json_dir = output_dir / "json"

    if not args.api_key:
        raise ValueError("Provide an OpenAI API key or set OPENAI_API_KEY.")

    if not page_paths:
        raise ValueError("No pages were selected for extraction.")

    if args.pdf:
        selected_pages = [page_index_from_image_name(path, fallback=index) + 1 for index, path in enumerate(page_paths)]
        setattr(args, "selected_source_pages", selected_pages)
        if len(selected_pages) <= 12:
            selected_text = ", ".join(str(page) for page in selected_pages)
        else:
            selected_text = f"{selected_pages[0]}-{selected_pages[-1]} with exclusions"
        log_fn(f"Selected {len(page_paths)} page(s) for extraction: {selected_text}")

    extractor = OpenAIPageExtractor(
        api_key=args.api_key,
        model=args.model,
        detail=args.detail,
        max_retries=args.max_retries,
        timeout=args.timeout,
        log_fn=log_fn,
    )
    pages = load_or_extract_batches(
        extractor=extractor,
        page_paths=page_paths,
        json_dir=json_dir,
        pages_per_batch=args.pages_per_batch,
        resume=args.resume,
        log_fn=log_fn,
    )
    markdown, stats = assemble_markdown(
        pages,
        page_break=args.chapter_page_break,
        include_source_comments=args.include_source_comments,
        include_marginal_notes=args.include_marginal_notes,
        title=getattr(args, "pdf_title", ""),
        subtitle=getattr(args, "pdf_subtitle", ""),
        author=getattr(args, "pdf_author", ""),
        publication_date=getattr(args, "publication_date", ""),
        rights=getattr(args, "pdf_rights", ""),
    )
    stats["api_usage"] = extractor.usage.to_dict()
    stats["selected_source_pages"] = getattr(args, "selected_source_pages", [])
    write_outputs(output_dir=output_dir, pages=pages, markdown=markdown, stats=stats, args=args, log_fn=log_fn)
    log_fn(extractor.usage.summary_line())

    pdf_path: Path | None = None
    if getattr(args, "build_pdf", False):
        pdf_path = build_pdf_from_markdown(
            output_dir=output_dir,
            title=getattr(args, "pdf_title", ""),
            subtitle=getattr(args, "pdf_subtitle", ""),
            short_title=getattr(args, "short_title", ""),
            author=getattr(args, "pdf_author", ""),
            publication_date=getattr(args, "publication_date", ""),
            rights=getattr(args, "pdf_rights", ""),
            template_path=getattr(args, "template", None),
            pdf_engine=getattr(args, "pdf_engine", "xelatex"),
            log_fn=log_fn,
        )

    return output_dir, stats, pdf_path


def rebuild_book(args: argparse.Namespace, log_fn=log) -> tuple[Path, dict[str, Any], Path | None]:
    output_dir = args.output_dir.expanduser().resolve()
    images_dir = output_dir / "images"

    if args.pdf:
        pdf_path = args.pdf.expanduser().resolve()
        if not pdf_path.exists():
            raise FileNotFoundError(f"Source PDF not found: {pdf_path}")
        output_dir.mkdir(parents=True, exist_ok=True)
        page_paths = render_pdf_pages(
            pdf_path=pdf_path,
            images_dir=images_dir,
            dpi=args.dpi,
            start_page=args.skip_pages,
            page_count=args.pages,
            max_image_side=args.max_image_side,
            log_fn=log_fn,
        )
    else:
        images_source = args.images.expanduser().resolve()
        if not images_source.exists() or not images_source.is_dir():
            raise FileNotFoundError(f"Image folder not found: {images_source}")
        page_paths = list_image_pages(images_source)
        if not page_paths:
            raise ValueError(f"No supported image files found in {images_source}")

    return rebuild_book_from_page_paths(args, page_paths, log_fn=log_fn)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild a scanned public-domain book into publication-quality Markdown text.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pdf", type=Path, help="Source scanned PDF to render and extract.")
    source.add_argument("--images", type=Path, help="Folder of already-rendered page images.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Folder for images, batch JSON, and book.md.")
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", DEFAULT_API_KEY), help="OpenAI API key. Defaults to the built-in key, unless OPENAI_API_KEY is set.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"OpenAI vision-capable model to use. Default: {DEFAULT_MODEL}.")
    parser.add_argument("--detail", choices=["low", "high", "auto"], default="high", help="Image detail level for the model.")
    parser.add_argument("--dpi", type=positive_int, default=DEFAULT_DPI, help=f"Render DPI for PDF input. Default: {DEFAULT_DPI}.")
    parser.add_argument("--max-image-side", type=nonnegative_int, default=DEFAULT_MAX_IMAGE_SIDE, help="Resize rendered images so the longest side is at most this many pixels. Use 0 to disable.")
    parser.add_argument("--skip-pages", type=nonnegative_int, default=0, help="Number of initial PDF pages to skip.")
    parser.add_argument("--pages", type=positive_int, default=None, help="Number of PDF pages to process after --skip-pages. Defaults to all remaining pages.")
    parser.add_argument("--pages-per-batch", type=positive_int, default=1, help="Images to send per API request. Use 1 for best OCR reliability.")
    parser.add_argument("--resume", action="store_true", help="Reuse existing json/batch_*.json files when present.")
    parser.add_argument("--include-source-comments", action="store_true", help="Include HTML comments marking source scan pages in book.md.")
    parser.add_argument("--include-marginal-notes", action="store_true", help="Include side and margin notes in the chapter-end note apparatus. Default is to exclude them.")
    parser.add_argument("--chapter-page-break", default=DEFAULT_PAGE_BREAK, help="Text inserted before each chapter after the first content. Use an empty string to disable.")
    parser.add_argument("--build-pdf", action="store_true", help="Build print_ready.pdf from book.md with pandoc after extraction.")
    parser.add_argument("--pdf-title", default="", help="Title printed on the generated title page and used as PDF metadata.")
    parser.add_argument("--pdf-subtitle", default="", help="Subtitle printed on the generated title page.")
    parser.add_argument("--short-title", default="", help="Optional shortened title for running headers.")
    parser.add_argument("--pdf-author", default="", help="Author printed on the generated title page and used as PDF metadata.")
    parser.add_argument("--publication-date", default="", help="Publication date printed on the generated title page.")
    parser.add_argument("--pdf-rights", default="", help="Rights line printed on the generated title page and used as PDF metadata.")
    parser.add_argument("--pdf-engine", default="xelatex", help="Pandoc PDF engine used when --build-pdf is enabled. Default: xelatex.")
    parser.add_argument("--template", type=Path, default=None, help="Pandoc LaTeX template used when --build-pdf is enabled. Defaults to printer_template.tex next to this script.")
    parser.add_argument("--max-retries", type=positive_int, default=5, help="Retries per OpenAI batch.")
    parser.add_argument("--timeout", type=float, default=240.0, help="OpenAI request timeout in seconds.")
    return parser.parse_args(argv)


def launch_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        from PIL import ImageTk
    except Exception as exc:
        print(f"Error: Tkinter GUI is not available: {exc}", file=sys.stderr)
        return 2

    class BookRebuilderApp:
        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self.root.title("Book Rebuilder v10")
            self.root.minsize(840, 660)
            self.messages: queue.Queue[tuple[str, Any]] = queue.Queue()
            self.worker: threading.Thread | None = None

            project_dir = Path(__file__).resolve().parent
            default_test_dir = project_dir / "test"
            built_in_key = os.environ.get("OPENAI_API_KEY", DEFAULT_API_KEY)

            self.pdf_var = tk.StringVar()
            self.start_page_var = tk.StringVar(value="1")
            self.end_page_var = tk.StringVar(value="")
            self.model_var = tk.StringVar(value=DEFAULT_MODEL)
            self.api_key_var = tk.StringVar(value=built_in_key)
            self.output_dir_var = tk.StringVar(value=str(default_test_dir))
            self.title_var = tk.StringVar()
            self.subtitle_var = tk.StringVar()
            self.short_title_var = tk.StringVar()
            self.author_var = tk.StringVar()
            self.publication_date_var = tk.StringVar()
            self.rights_var = tk.StringVar(value="Public domain source; reconstruction from scanned pages.")
            self.detail_var = tk.StringVar(value="high")
            self.dpi_var = tk.StringVar(value=str(DEFAULT_DPI))
            self.max_side_var = tk.StringVar(value=str(DEFAULT_MAX_IMAGE_SIDE))
            self.batch_var = tk.StringVar(value="1")
            self.resume_var = tk.BooleanVar(value=True)
            self.build_pdf_var = tk.BooleanVar(value=True)

            self._custom_output = False
            self._build_layout()
            self.root.after(100, self._poll_messages)

        def _build_layout(self) -> None:
            style = ttk.Style(self.root)
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass
            style.configure("TButton", padding=(12, 6), foreground="#111111", background="#e8ecef")
            style.map(
                "TButton",
                foreground=[("disabled", "#777777"), ("active", "#111111"), ("pressed", "#111111")],
                background=[("disabled", "#d8d8d8"), ("active", "#dde4ea"), ("pressed", "#cfd8e0")],
            )
            style.configure("Accent.TButton", padding=(14, 7), foreground="#ffffff", background="#245a8d")
            style.map(
                "Accent.TButton",
                foreground=[("disabled", "#eeeeee"), ("active", "#ffffff"), ("pressed", "#ffffff")],
                background=[("disabled", "#9ca8b3"), ("active", "#2f6ea8"), ("pressed", "#1f4e7b")],
            )

            main = ttk.Frame(self.root, padding=14)
            main.grid(row=0, column=0, sticky="nsew")
            self.root.columnconfigure(0, weight=1)
            self.root.rowconfigure(0, weight=1)
            main.columnconfigure(1, weight=1)
            main.rowconfigure(7, weight=1)

            ttk.Label(main, text="Source PDF").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
            ttk.Entry(main, textvariable=self.pdf_var).grid(row=0, column=1, sticky="ew", pady=5)
            ttk.Button(main, text="Browse", command=self._browse_pdf).grid(row=0, column=2, sticky="ew", padx=(8, 0), pady=5)

            pages = ttk.Frame(main)
            pages.grid(row=1, column=1, sticky="w", pady=5)
            ttk.Label(main, text="Pages").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=5)
            ttk.Label(pages, text="Start").grid(row=0, column=0, sticky="w")
            ttk.Entry(pages, textvariable=self.start_page_var, width=8).grid(row=0, column=1, padx=(6, 14))
            ttk.Label(pages, text="End").grid(row=0, column=2, sticky="w")
            ttk.Entry(pages, textvariable=self.end_page_var, width=8).grid(row=0, column=3, padx=(6, 0))
            self.start_page_var.trace_add("write", lambda *_: self._refresh_default_output())
            self.end_page_var.trace_add("write", lambda *_: self._refresh_default_output())

            ttk.Label(main, text="Model").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=5)
            model_box = ttk.Combobox(
                main,
                textvariable=self.model_var,
                values=[
                    DEFAULT_MODEL,
                    "gpt-5.4-mini",
                    "gpt-5.3-codex",
                    "gpt-5.2",
                    "gpt-4.1",
                    "gpt-4.1-mini",
                    "gpt-4o",
                ],
            )
            model_box.grid(row=2, column=1, sticky="ew", pady=5)

            ttk.Label(main, text="Output Folder").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=5)
            ttk.Entry(main, textvariable=self.output_dir_var).grid(row=3, column=1, sticky="ew", pady=5)
            ttk.Button(main, text="Browse", command=self._browse_output).grid(row=3, column=2, sticky="ew", padx=(8, 0), pady=5)

            meta = ttk.LabelFrame(main, text="PDF Metadata", padding=10)
            meta.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 5))
            meta.columnconfigure(1, weight=1)
            meta.columnconfigure(3, weight=1)
            ttk.Label(meta, text="Title").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
            ttk.Entry(meta, textvariable=self.title_var).grid(row=0, column=1, sticky="ew", pady=3)
            ttk.Label(meta, text="Subtitle").grid(row=0, column=2, sticky="w", padx=(14, 8), pady=3)
            ttk.Entry(meta, textvariable=self.subtitle_var).grid(row=0, column=3, sticky="ew", pady=3)
            ttk.Label(meta, text="Shortened title").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
            ttk.Entry(meta, textvariable=self.short_title_var).grid(row=1, column=1, sticky="ew", pady=3)
            ttk.Label(meta, text="Author").grid(row=1, column=2, sticky="w", padx=(14, 8), pady=3)
            ttk.Entry(meta, textvariable=self.author_var).grid(row=1, column=3, sticky="ew", pady=3)
            ttk.Label(meta, text="Publication date").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=3)
            ttk.Entry(meta, textvariable=self.publication_date_var).grid(row=2, column=1, sticky="ew", pady=3)
            ttk.Label(meta, text="Rights").grid(row=2, column=2, sticky="w", padx=(14, 8), pady=3)
            ttk.Entry(meta, textvariable=self.rights_var).grid(row=2, column=3, sticky="ew", pady=3)

            options = ttk.LabelFrame(main, text="Options", padding=10)
            options.grid(row=5, column=0, columnspan=3, sticky="ew", pady=5)
            for col in range(8):
                options.columnconfigure(col, weight=1 if col in {1, 3, 5, 7} else 0)
            ttk.Label(options, text="Detail").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
            ttk.Combobox(options, textvariable=self.detail_var, values=["high", "auto", "low"], width=8, state="readonly").grid(row=0, column=1, sticky="w", pady=3)
            ttk.Label(options, text="DPI").grid(row=0, column=2, sticky="w", padx=(14, 6), pady=3)
            ttk.Entry(options, textvariable=self.dpi_var, width=8).grid(row=0, column=3, sticky="w", pady=3)
            ttk.Label(options, text="Max side").grid(row=0, column=4, sticky="w", padx=(14, 6), pady=3)
            ttk.Entry(options, textvariable=self.max_side_var, width=8).grid(row=0, column=5, sticky="w", pady=3)
            ttk.Label(options, text="Batch").grid(row=0, column=6, sticky="w", padx=(14, 6), pady=3)
            ttk.Entry(options, textvariable=self.batch_var, width=8).grid(row=0, column=7, sticky="w", pady=3)
            ttk.Checkbutton(options, text="Resume existing batches", variable=self.resume_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
            ttk.Checkbutton(options, text="Build PDF", variable=self.build_pdf_var).grid(row=1, column=3, columnspan=2, sticky="w", pady=(6, 0))

            actions = ttk.Frame(main)
            actions.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 6))
            actions.columnconfigure(0, weight=1)
            self.start_button = ttk.Button(actions, text="Run Rebuild", command=self._start, style="Accent.TButton")
            self.start_button.grid(row=0, column=1, sticky="e")

            self.log_text = tk.Text(main, height=14, wrap="word")
            self.log_text.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(4, 0))
            scrollbar = ttk.Scrollbar(main, command=self.log_text.yview)
            scrollbar.grid(row=7, column=3, sticky="ns", pady=(4, 0))
            self.log_text.configure(yscrollcommand=scrollbar.set)

        def _browse_pdf(self) -> None:
            path = filedialog.askopenfilename(
                title="Choose scanned PDF",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            )
            if not path:
                return
            self.pdf_var.set(path)
            if not self.title_var.get().strip():
                self.title_var.set(Path(path).stem.replace("_", " ").replace("-", " ").title())
            try:
                with fitz.open(path) as doc:
                    self.end_page_var.set(str(doc.page_count))
            except Exception:
                self.end_page_var.set("")
            self._custom_output = False
            self._refresh_default_output()

        def _browse_output(self) -> None:
            path = filedialog.askdirectory(title="Choose output folder")
            if path:
                self._custom_output = True
                self.output_dir_var.set(path)

        def _refresh_default_output(self) -> None:
            if self._custom_output:
                return
            pdf_text = self.pdf_var.get().strip()
            if not pdf_text:
                return
            project_dir = Path(__file__).resolve().parent
            start = self.start_page_var.get().strip() or "1"
            end = self.end_page_var.get().strip() or "all"
            folder = f"{Path(pdf_text).stem}_pages_{start}_{end}_v10"
            self.output_dir_var.set(str(project_dir / "test" / folder))

        def _append_log(self, text: str) -> None:
            self.log_text.insert("end", text.rstrip() + "\n")
            self.log_text.see("end")

        def _review_pages(self, page_paths: list[Path]) -> list[Path] | None:
            dialog = tk.Toplevel(self.root)
            dialog.title("Review Pages")
            dialog.transient(self.root)
            dialog.grab_set()
            dialog.geometry("820x720")
            dialog.columnconfigure(0, weight=1)
            dialog.rowconfigure(1, weight=1)

            heading = ttk.Label(
                dialog,
                text="Review rendered pages before OCR. Press i to include, e to exclude, then Start OCR.",
            )
            heading.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))

            canvas = tk.Canvas(dialog, highlightthickness=0)
            scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
            rows_frame = ttk.Frame(canvas)
            rows_frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas_window = canvas.create_window((0, 0), window=rows_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.grid(row=1, column=0, sticky="nsew", padx=(12, 0), pady=6)
            scrollbar.grid(row=1, column=1, sticky="ns", pady=6, padx=(0, 12))
            canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))

            controls = ttk.Frame(dialog)
            controls.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(6, 12))
            controls.columnconfigure(0, weight=1)

            included: list[tk.BooleanVar] = []
            status_labels: list[ttk.Label] = []
            row_frames: list[tk.Frame] = []
            thumbnails: list[Any] = []
            selected_index = tk.IntVar(value=0)
            result: dict[str, list[Path] | None] = {"paths": None}

            def status_text(index: int) -> str:
                return "Include" if included[index].get() else "Exclude"

            def refresh_row(index: int) -> None:
                is_current = selected_index.get() == index
                bg = "#eaf2fb" if is_current else "#ffffff"
                if not included[index].get():
                    bg = "#f4e9e9" if not is_current else "#eadadb"
                row_frames[index].configure(bg=bg, highlightbackground="#245a8d" if is_current else "#d2d8de")
                status_labels[index].configure(text=status_text(index))

            def refresh_all() -> None:
                for idx in range(len(row_frames)):
                    refresh_row(idx)

            def set_current(index: int) -> None:
                if not row_frames:
                    return
                selected_index.set(max(0, min(index, len(row_frames) - 1)))
                refresh_all()
                dialog.focus_set()

            def set_included(index: int, value: bool) -> None:
                included[index].set(value)
                refresh_row(index)

            def toggle(index: int) -> None:
                set_included(index, not included[index].get())

            def key_press(event: tk.Event) -> None:
                idx = selected_index.get()
                key = str(event.keysym).lower()
                if key == "i":
                    set_included(idx, True)
                elif key == "e":
                    set_included(idx, False)
                elif key in {"down", "j"}:
                    set_current(idx + 1)
                elif key in {"up", "k"}:
                    set_current(idx - 1)

            for index, path in enumerate(page_paths):
                included.append(tk.BooleanVar(value=True))
                source_page = page_index_from_image_name(path, fallback=index) + 1
                row = tk.Frame(rows_frame, bg="#ffffff", highlightthickness=1, highlightbackground="#d2d8de")
                row.grid(row=index, column=0, sticky="ew", pady=5)
                row.columnconfigure(1, weight=1)
                row_frames.append(row)

                with Image.open(path) as raw:
                    thumb = raw.convert("RGB")
                    thumb.thumbnail((125, 175))
                    photo = ImageTk.PhotoImage(thumb)
                    thumbnails.append(photo)

                image_label = tk.Label(row, image=photo, bg="#ffffff")
                image_label.grid(row=0, column=0, rowspan=2, padx=8, pady=8)
                ttk.Label(row, text=f"Source page {source_page}").grid(row=0, column=1, sticky="w", padx=8, pady=(10, 2))
                status = ttk.Label(row, text="Include", width=10)
                status.grid(row=0, column=2, sticky="e", padx=8, pady=(10, 2))
                status_labels.append(status)
                ttk.Button(row, text="Include", command=lambda idx=index: set_included(idx, True)).grid(row=1, column=1, sticky="e", padx=4, pady=(2, 10))
                ttk.Button(row, text="Exclude", command=lambda idx=index: set_included(idx, False)).grid(row=1, column=2, sticky="e", padx=8, pady=(2, 10))
                row.bind("<Button-1>", lambda _event, idx=index: set_current(idx))
                image_label.bind("<Button-1>", lambda _event, idx=index: set_current(idx))
                status.bind("<Button-1>", lambda _event, idx=index: toggle(idx))

            def include_all() -> None:
                for idx in range(len(included)):
                    included[idx].set(True)
                refresh_all()

            def exclude_all() -> None:
                for idx in range(len(included)):
                    included[idx].set(False)
                refresh_all()

            def accept() -> None:
                selected = [path for path, var in zip(page_paths, included) if var.get()]
                if not selected:
                    messagebox.showerror("Book Rebuilder", "Include at least one page before starting OCR.", parent=dialog)
                    return
                result["paths"] = selected
                dialog.destroy()

            def cancel() -> None:
                result["paths"] = None
                dialog.destroy()

            ttk.Button(controls, text="Include All", command=include_all).grid(row=0, column=1, padx=4)
            ttk.Button(controls, text="Exclude All", command=exclude_all).grid(row=0, column=2, padx=4)
            ttk.Button(controls, text="Cancel", command=cancel).grid(row=0, column=3, padx=4)
            ttk.Button(controls, text="Start OCR", style="Accent.TButton", command=accept).grid(row=0, column=4, padx=(10, 0))

            dialog.bind("<Key>", key_press)
            dialog.protocol("WM_DELETE_WINDOW", cancel)
            refresh_all()
            dialog.focus_set()
            self.root.wait_window(dialog)
            return result["paths"]

        def _validated_args(self) -> argparse.Namespace:
            pdf_path = Path(self.pdf_var.get().strip()).expanduser()
            if not pdf_path.exists():
                raise ValueError("Choose an existing source PDF.")

            start = int(self.start_page_var.get().strip())
            end = int(self.end_page_var.get().strip())
            if start <= 0 or end <= 0 or end < start:
                raise ValueError("Enter a valid 1-based inclusive page range.")

            api_key = self.api_key_var.get().strip()
            if not api_key:
                raise ValueError("Enter an OpenAI API key or set OPENAI_API_KEY before launching the GUI.")

            return argparse.Namespace(
                pdf=pdf_path,
                images=None,
                output_dir=Path(self.output_dir_var.get().strip()).expanduser(),
                api_key=api_key,
                model=self.model_var.get().strip() or DEFAULT_MODEL,
                detail=self.detail_var.get().strip() or "high",
                dpi=int(self.dpi_var.get().strip()),
                max_image_side=int(self.max_side_var.get().strip()),
                skip_pages=start - 1,
                pages=end - start + 1,
                pages_per_batch=int(self.batch_var.get().strip()),
                resume=bool(self.resume_var.get()),
                include_source_comments=False,
                include_marginal_notes=False,
                chapter_page_break=DEFAULT_PAGE_BREAK,
                build_pdf=bool(self.build_pdf_var.get()),
                pdf_title=self.title_var.get().strip(),
                pdf_subtitle=self.subtitle_var.get().strip(),
                short_title=self.short_title_var.get().strip(),
                pdf_author=self.author_var.get().strip(),
                publication_date=self.publication_date_var.get().strip(),
                pdf_rights=self.rights_var.get().strip(),
                pdf_engine="xelatex",
                template=None,
                max_retries=5,
                timeout=240.0,
            )

        def _start(self) -> None:
            if self.worker and self.worker.is_alive():
                return
            try:
                args = self._validated_args()
            except Exception as exc:
                messagebox.showerror("Book Rebuilder", str(exc))
                return

            self.start_button.configure(state="disabled")
            self._append_log("")
            self._append_log("Rendering pages for review.")
            self.worker = threading.Thread(target=self._run_worker, args=(args,), daemon=True)
            self.worker.start()

        def _run_worker(self, args: argparse.Namespace) -> None:
            def gui_log(message: str) -> None:
                self.messages.put(("log", message))

            try:
                output_dir = args.output_dir.expanduser().resolve()
                images_dir = output_dir / "images"
                pdf_path = args.pdf.expanduser().resolve()
                output_dir.mkdir(parents=True, exist_ok=True)
                page_paths = render_pdf_pages(
                    pdf_path=pdf_path,
                    images_dir=images_dir,
                    dpi=args.dpi,
                    start_page=args.skip_pages,
                    page_count=args.pages,
                    max_image_side=args.max_image_side,
                    log_fn=gui_log,
                )
                self.messages.put(("select_pages", (args, page_paths)))
            except Exception as exc:
                self.messages.put(("error", str(exc)))

        def _run_extraction_worker(self, args: argparse.Namespace, page_paths: list[Path]) -> None:
            def gui_log(message: str) -> None:
                self.messages.put(("log", message))

            try:
                output_dir, stats, pdf_path = rebuild_book_from_page_paths(args, page_paths, log_fn=gui_log)
                self.messages.put(("done", (output_dir, stats, pdf_path)))
            except Exception as exc:
                self.messages.put(("error", str(exc)))

        def _poll_messages(self) -> None:
            try:
                while True:
                    kind, payload = self.messages.get_nowait()
                    if kind == "log":
                        self._append_log(str(payload))
                    elif kind == "select_pages":
                        args, page_paths = payload
                        selected = self._review_pages(page_paths)
                        if selected is None:
                            self._append_log("Page review canceled.")
                            self.start_button.configure(state="normal")
                            continue
                        excluded_count = len(page_paths) - len(selected)
                        self._append_log(f"Starting OCR with {len(selected)} included page(s); {excluded_count} excluded.")
                        self.worker = threading.Thread(target=self._run_extraction_worker, args=(args, selected), daemon=True)
                        self.worker.start()
                    elif kind == "done":
                        output_dir, stats, pdf_path = payload
                        self._append_log(
                            f"Done. Chapters: {stats['chapters']} | Footnotes: {stats['footnotes']} | Orphan notes: {stats['orphan_notes']}"
                        )
                        api_usage = stats.get("api_usage", {})
                        if api_usage:
                            cost = api_usage.get("estimated_cost_usd")
                            cost_text = "unknown" if cost is None else f"${float(cost):.4f}"
                            self._append_log(
                                "API total: "
                                f"{int(api_usage.get('requests', 0))} request(s), "
                                f"{int(api_usage.get('total_tokens', 0)):,} tokens, "
                                f"estimated cost {cost_text}"
                            )
                        if stats["unresolved_references"]:
                            self._append_log(f"Warning: {stats['unresolved_references']} inline footnote reference(s) had no extracted note text.")
                        if pdf_path:
                            self._append_log(f"PDF: {pdf_path}")
                        self._append_log(f"Output: {output_dir}")
                        self.start_button.configure(state="normal")
                        messagebox.showinfo("Book Rebuilder", f"Finished rebuilding pages into:\n{output_dir}")
                    elif kind == "error":
                        self._append_log(f"Error: {payload}")
                        self.start_button.configure(state="normal")
                        messagebox.showerror("Book Rebuilder", str(payload))
            except queue.Empty:
                pass
            self.root.after(100, self._poll_messages)

    root = tk.Tk()
    BookRebuilderApp(root)
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if not raw_argv or raw_argv == ["--gui"]:
        return launch_gui()

    args = parse_args(raw_argv)
    try:
        _, stats, _ = rebuild_book(args, log_fn=log)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    log(f"Chapters: {stats['chapters']} | Footnotes: {stats['footnotes']} | Orphan notes: {stats['orphan_notes']}")
    if stats["unresolved_references"]:
        log(f"Warning: {stats['unresolved_references']} inline footnote reference(s) had no extracted note text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
