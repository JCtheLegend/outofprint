#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import xml.etree.ElementTree as ET

import yaml


LATEX_TEMPLATE = r"""
\documentclass[11pt,twoside]{book}

\usepackage{fontspec}
\usepackage[
  paperwidth=6in,
  paperheight=9in,
  inner=1.0in,
  outer=1.1in,
  marginparwidth=0.75in,
  marginparsep=0.14in,
  top=0.9in,
  bottom=0.95in,
  headheight=14pt
]{geometry}
\usepackage{fancyhdr}
\usepackage{titlesec}
\usepackage{hyperref}
\usepackage{emptypage}
\usepackage{verse}
\usepackage{longtable}
\usepackage{booktabs}
\usepackage{array}
\usepackage{graphicx}
\usepackage{setspace}
\usepackage{xcolor}

\providecommand{\tightlist}{%
  \setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}
}

\reversemarginpar
\setlength{\marginparpush}{12pt}

\setmainfont{Times New Roman}
\setsansfont{Arial}
\setmonofont{Courier New}

\onehalfspacing
\setstretch{1.08}

\pagestyle{fancy}
\fancyhf{}
\fancyhead[CE]{\footnotesize\nouppercase{$title$}}
\fancyhead[CO]{\footnotesize\nouppercase{$author$}}
\fancyfoot[C]{\thepage}
\renewcommand{\headrulewidth}{0pt}

\hypersetup{
  colorlinks=false,
  pdfborder={0 0 0}
}

\newcommand{\booktitle}[1]{{\fontsize{24}{30}\selectfont\bfseries #1}}
\newcommand{\booksubtitle}[1]{{\fontsize{15}{20}\selectfont #1}}
\newcommand{\chapterlabelline}[1]{\begin{center}\Large\bfseries #1\end{center}}
\newcommand{\chaptersubtitleline}[1]{\begin{center}\large\bfseries #1\end{center}}
\newcommand{\displayheading}[1]{\begin{center}\bfseries #1\end{center}}
\newcommand{\sidenoteplain}[1]{\marginpar{\raggedright\footnotesize\itshape #1}}
\newcommand{\scanqualitynote}[1]{\begin{flushright}{\footnotesize\textcolor{gray}{#1}}\end{flushright}}

\begin{document}

$body$

\end{document}
""".strip() + "\n"


BUILD_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail
pandoc \
  book.md \
  --from markdown+raw_tex \
  --template=printer_template.tex \
  --metadata-file=metadata.yaml \
  --pdf-engine=xelatex \
  -o print_ready.pdf
pandoc \
  book.md \
  --from markdown+raw_tex \
  --template=printer_template.tex \
  --metadata-file=metadata.yaml \
  --pdf-engine=xelatex \
  -o print_ready.pdf
echo "Wrote print_ready.pdf"
"""


START_MARKER_RE = re.compile(r"\*\*\*\s*START OF (?:THIS|THE) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.IGNORECASE)
END_MARKER_RE = re.compile(r"\*\*\*\s*END OF (?:THIS|THE) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.IGNORECASE)
CHAPTER_HEADING_RE = re.compile(
    r"^(?:BOOK|CHAPTER|CHAP\.|PART|VOLUME)\s+([IVXLCDM]+|\d+)(?:[.:]|$)",
    re.IGNORECASE,
)
FOOTNOTE_RE = re.compile(r"^(?:\[(\d+|[A-Za-z]+)\]\s*|Footnote\s+(\d+)\s*[:.)-]\s*)(.+)$", re.IGNORECASE)


@dataclass
class SourceText:
    text: str
    source_label: str
    title: str = ""
    author: str = ""
    publication_date: str = ""
    source_type: str = "text"


class HTMLTextExtractor(HTMLParser):
    BLOCK_TAGS = {
        "p",
        "div",
        "section",
        "article",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "pre",
        "ul",
        "ol",
        "li",
        "table",
        "tr",
        "td",
        "th",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "head"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "br":
            self.parts.append("\n")
            return
        if tag == "li":
            self.parts.append("\n- ")
            return
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in {"script", "style", "head"} and self.skip_depth > 0:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str):
        if self.skip_depth:
            return
        if data:
            self.parts.append(data)

    def as_text(self) -> str:
        text = "".join(self.parts)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def clean_inline_text(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\ufffe", "").replace("\ufffd", "")
    text = re.sub(r"[\u200b\u200c\u200d]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def repair_hyphenation(text: str) -> str:
    text = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", text)
    text = re.sub(r"([A-Za-z])￾([a-zA-Z])", r"\1\2", text)
    return text


def fix_minor_ocr_noise(text: str) -> str:
    replacements = {
        "popu lation": "population",
        "com monwealth": "commonwealth",
        "employ ment": "employment",
        "re dundancy": "redundancy",
        "ex tream": "extream",
        "go vernment": "government",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"([A-Za-z])\uFFFE([A-Za-z])", r"\1\2", text)
    text = re.sub(r"([A-Za-z])\uFFFD([A-Za-z])", r"\1\2", text)
    return text


def normalize_blank_lines(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def escape_latex_text(text: str) -> str:
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
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def build_title_page_markdown(title: str, author: str, volume: str, publication_date: str) -> str:
    pieces = [
        r"\thispagestyle{empty}",
        r"\begin{titlepage}",
        r"\centering",
        r"\vspace*{1.4in}",
        rf"\booktitle{{{escape_latex_text(title)}}}\\[1.2em]",
    ]
    if volume:
        pieces.append(rf"\booksubtitle{{{escape_latex_text(volume)}}}\\[2.2em]")
    if author:
        pieces.append(r"{\Large by}\\[0.7em]")
        pieces.append(rf"{{\Large {escape_latex_text(author)}}}\\[3.0em]")
    if publication_date:
        pieces.append(rf"{{\large Originally published {escape_latex_text(publication_date)}}}\\[0.6em]")
    pieces += [
        r"\vfill",
        r"{\large Reformatted public-domain edition}\\[0.6em]",
        r"\end{titlepage}",
        r"\clearpage",
    ]
    return "\n".join(pieces) + "\n"


def write_print_assets(output_dir: Path, title: str, author: str, volume: str, publication_date: str):
    metadata: dict[str, str] = {
        "title": title,
        "author": author,
        "rights": "Public domain source; this reformatted edition prepared from Project Gutenberg text.",
    }
    if volume:
        metadata["subtitle"] = volume
    if publication_date:
        metadata["date"] = publication_date
    (output_dir / "metadata.yaml").write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
    (output_dir / "printer_template.tex").write_text(LATEX_TEMPLATE, encoding="utf-8")
    build_path = output_dir / "build_print_pdf.sh"
    build_path.write_text(BUILD_SCRIPT, encoding="utf-8")
    build_path.chmod(0o755)


def build_pdf(output_dir: Path):
    if not shutil.which("pandoc"):
        raise RuntimeError("Pandoc was not found. Install pandoc and try again.")
    if not shutil.which("xelatex"):
        raise RuntimeError("XeLaTeX was not found. Install a TeX distribution with xelatex and try again.")
    subprocess.run(["bash", str(output_dir / "build_print_pdf.sh")], cwd=output_dir, check=True)


def decode_text_bytes(payload: bytes, encoding_hint: str = "") -> str:
    encodings = []
    if encoding_hint:
        encodings.append(encoding_hint.strip().lower())
    encodings.extend(["utf-8-sig", "utf-8", "cp1252", "latin-1"])
    for enc in encodings:
        if not enc:
            continue
        try:
            return payload.decode(enc)
        except Exception:
            continue
    return payload.decode("utf-8", errors="replace")


def extract_charset_from_content_type(content_type: str) -> str:
    match = re.search(r"charset=([^\s;]+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip("\"'") if match else ""


def html_to_text(html: str) -> str:
    parser = HTMLTextExtractor()
    parser.feed(html)
    parser.close()
    return parser.as_text()


def strip_html_toc_section(html: str) -> tuple[str, int]:
    contents_heading = re.search(r"<h[1-6][^>]*>\s*contents\s*</h[1-6]>", html, flags=re.IGNORECASE)
    if not contents_heading:
        return html, 0

    tail = html[contents_heading.end() :]

    # Project Gutenberg HTML often places a named body anchor right after TOC.
    body_anchor = re.search(
        r'<a\s+name\s*=\s*"(?:link2H[^"]*|chapter[^"]*|chap[^"]*)"\s+id\s*=\s*"[^"]*"\s*>',
        tail,
        flags=re.IGNORECASE,
    )
    if body_anchor and body_anchor.start() < 120000:
        cut_start = contents_heading.start()
        cut_end = contents_heading.end() + body_anchor.start()
        removed = cut_end - cut_start
        if removed > 0:
            return html[:cut_start] + html[cut_end:], removed

    # Fallback for simpler TOCs.
    table_match = re.search(r"<table\b[^>]*>.*?</table>", tail, flags=re.IGNORECASE | re.DOTALL)
    if table_match and table_match.start() < 30000:
        cut_start = contents_heading.start()
        cut_end = contents_heading.end() + table_match.end()
        removed = cut_end - cut_start
        if removed > 0:
            return html[:cut_start] + html[cut_end:], removed

    return html, 0


def fetch_url(url: str, timeout: int = 35) -> tuple[str, str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Book Rebuilder Gutenberg GUI)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
        charset = extract_charset_from_content_type(content_type)
        text = decode_text_bytes(raw, charset)
        return text, content_type.lower(), response.geturl()


def parse_gutenberg_id(value: str) -> str:
    cleaned = value.strip()
    if re.fullmatch(r"\d{2,8}", cleaned):
        return cleaned
    patterns = [
        r"/ebooks/(\d+)",
        r"/files/(\d+)(?:/|$)",
        r"/cache/epub/(\d+)(?:/|$)",
        r"gutenberg\.org/[^ ]*?(\d{2,8})",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def gutenberg_candidate_urls(book_id: str, prefer_html: bool) -> list[tuple[str, str]]:
    txt_urls = [
        (f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt", "txt"),
        (f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}-0.txt", "txt"),
        (f"https://www.gutenberg.org/files/{book_id}/{book_id}-0.txt", "txt"),
        (f"https://www.gutenberg.org/files/{book_id}/{book_id}.txt", "txt"),
        (f"https://www.gutenberg.org/ebooks/{book_id}.txt.utf-8", "txt"),
    ]
    html_urls = [
        (f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}-images.html", "html"),
        (f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.html", "html"),
        (f"https://www.gutenberg.org/files/{book_id}/{book_id}-h/{book_id}-h.htm", "html"),
        (f"https://www.gutenberg.org/files/{book_id}/{book_id}-h/{book_id}-h.html", "html"),
    ]
    return html_urls + txt_urls if prefer_html else txt_urls + html_urls


def strip_gutenberg_boilerplate(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    start_match = START_MARKER_RE.search(text)
    end_match = END_MARKER_RE.search(text)
    if start_match and end_match and end_match.start() > start_match.end():
        text = text[start_match.end() : end_match.start()]
    else:
        end_alt = re.search(r"End of (?:the )?Project Gutenberg", text, flags=re.IGNORECASE)
        if end_alt:
            text = text[: end_alt.start()]
    text = text.strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def strip_redundant_front_metadata(text: str, title: str, author: str) -> str:
    lines = text.splitlines()
    title_norm = clean_inline_text(title).lower()
    author_norm = clean_inline_text(author).lower()
    scan_limit = min(len(lines), 120)
    i = 0
    removed_any = False

    while i < scan_limit:
        line = clean_inline_text(lines[i])
        if not line:
            i += 1
            continue

        raw_lower = line.lower().strip()
        line_norm = re.sub(r"[\s\W_]+", " ", raw_lower).strip()
        by_author_norm = f"by {author_norm}".strip() if author_norm else ""
        metadata_prefix = (
            raw_lower.startswith("title:")
            or raw_lower.startswith("author:")
            or raw_lower.startswith("release date:")
            or raw_lower.startswith("posting date:")
            or raw_lower.startswith("language:")
            or raw_lower.startswith("produced by")
            or raw_lower.startswith("transcribed from")
            or raw_lower.startswith("note:")
            or line_norm.startswith("title ")
            or line_norm.startswith("author ")
        )
        same_title = bool(title_norm) and line_norm == re.sub(r"[\s\W_]+", " ", title_norm).strip()
        same_author = bool(author_norm) and (
            line_norm == re.sub(r"[\s\W_]+", " ", author_norm).strip()
            or (by_author_norm and line_norm == re.sub(r"[\s\W_]+", " ", by_author_norm).strip())
        )

        if metadata_prefix or same_title or same_author:
            removed_any = True
            i += 1
            continue
        break

    if not removed_any:
        return text
    return "\n".join(lines[i:]).lstrip()


def is_toc_heading(line: str) -> bool:
    normalized = re.sub(r"[\W_]+", " ", clean_inline_text(line)).strip().lower()
    return normalized in {"contents", "table of contents", "contents of the volume"}


def looks_like_toc_entry(line: str) -> bool:
    text = clean_inline_text(line)
    if not text:
        return False
    if re.search(r"\.{3,}\s*(\d+|[ivxlcdm]+)\s*$", text, flags=re.IGNORECASE):
        return True
    if re.search(r"\s{2,}(\d+|[ivxlcdm]+)\s*$", text, flags=re.IGNORECASE):
        return True
    if re.search(r"\b(?:page|p\.)\s*(\d+|[ivxlcdm]+)\s*$", text, flags=re.IGNORECASE):
        return True
    return False


def strip_table_of_contents(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    if not lines:
        return text, 0

    search_limit = min(len(lines), 900)
    heading_idx = -1
    for idx in range(search_limit):
        if is_toc_heading(lines[idx]):
            heading_idx = idx
            break
    if heading_idx < 0:
        return text, 0

    toc_entry_count = 0
    end_idx = heading_idx + 1
    i = heading_idx + 1
    while i < len(lines):
        line = clean_inline_text(lines[i])
        if not line:
            end_idx = i + 1
            i += 1
            continue

        words = line.split()
        letters = re.sub(r"[^A-Za-z]", "", line)
        upper_ratio = (sum(1 for ch in letters if ch.isupper()) / len(letters)) if letters else 0.0
        starts_headingish = bool(
            re.match(r"^(?:book|chapter|part|volume)\b", line, flags=re.IGNORECASE)
            or re.match(r"^\d+\.\s+", line)
            or re.match(r"^[IVXLCDM]+\.\s+", line, flags=re.IGNORECASE)
        )
        is_short_headingish = len(words) <= 18 and (upper_ratio > 0.68 or starts_headingish)
        is_toc_like = looks_like_toc_entry(line) or is_short_headingish

        if is_toc_like:
            toc_entry_count += 1
            end_idx = i + 1
            i += 1
            continue

        prose_like = (
            len(words) >= 9
            and upper_ratio < 0.55
            and not starts_headingish
            and re.search(r"[a-z]{3,}", line) is not None
        )
        if toc_entry_count >= 4 and prose_like:
            # Body prose likely begins here; keep from this line onward.
            break

        # If we are already inside TOC, allow a handful of odd transitional lines.
        if toc_entry_count >= 4 and len(words) <= 24 and upper_ratio > 0.35:
            end_idx = i + 1
            i += 1
            continue

        # Bail out when confidence is low.
        break

    if toc_entry_count < 4:
        return text, 0

    removed = end_idx - heading_idx
    kept = lines[:heading_idx] + lines[end_idx:]
    return "\n".join(kept).lstrip(), removed


def strip_front_matter_before_first_chapter(text: str, scan_limit: int = 260) -> tuple[str, int]:
    lines = text.splitlines()
    limit = min(len(lines), max(1, scan_limit))
    first_chapter_idx = -1
    for idx in range(limit):
        if looks_like_chapter_heading(lines[idx]):
            first_chapter_idx = idx
            break
    if first_chapter_idx <= 0:
        return text, 0
    removed = first_chapter_idx
    return "\n".join(lines[first_chapter_idx:]).lstrip(), removed


def infer_metadata_from_text(text: str) -> dict[str, str]:
    lines = [line.strip() for line in text.splitlines()[:400] if line.strip()]
    title = ""
    author = ""
    publication_date = ""

    for line in lines:
        if not title:
            match = re.match(r"^Title:\s*(.+)$", line, flags=re.IGNORECASE)
            if match:
                title = clean_inline_text(match.group(1))
                continue
        if not author:
            match = re.match(r"^Author:\s*(.+)$", line, flags=re.IGNORECASE)
            if match:
                author = clean_inline_text(match.group(1))
                continue
        if not publication_date:
            match = re.match(r"^(?:Release Date|Posting Date):\s*(.+)$", line, flags=re.IGNORECASE)
            if match:
                publication_date = clean_inline_text(match.group(1))
                continue

    if not title:
        for line in lines[:80]:
            if len(line) < 8 or len(line) > 140:
                continue
            low = line.lower()
            if low.startswith(("project gutenberg", "produced by", "release date", "language:", "encoding:")):
                continue
            if re.match(r"^[\W_]+$", line):
                continue
            title = clean_inline_text(line)
            break

    return {
        "title": title,
        "author": author,
        "publication_date": publication_date,
    }


def looks_like_chapter_heading(line: str) -> bool:
    text = clean_inline_text(line)
    if not text or len(text) > 120:
        return False
    if CHAPTER_HEADING_RE.match(text):
        return True
    if re.fullmatch(r"(?:BOOK|PART|VOLUME)\s+[IVXLCDM]+", text, flags=re.IGNORECASE):
        return True
    if re.fullmatch(r"CHAPTER\s+[IVXLCDM]+\.", text, flags=re.IGNORECASE):
        return True
    return False


def looks_like_display_heading(line: str) -> bool:
    text = clean_inline_text(line)
    if not text or len(text) > 90:
        return False
    if text.endswith((".", "?", "!", ";", ":")):
        return False
    letters = re.sub(r"[^A-Za-z]", "", text)
    if not letters:
        return False
    upper_ratio = sum(1 for ch in letters if ch.isupper()) / max(1, len(letters))
    title_case = text == text.title()
    return upper_ratio > 0.78 or (title_case and len(text.split()) <= 9)


def join_paragraph_lines(lines: list[str]) -> str:
    if not lines:
        return ""
    parts: list[str] = []
    for idx, line in enumerate(lines):
        text = clean_inline_text(line)
        if not text:
            continue
        if idx == 0:
            parts.append(text)
            continue
        if parts[-1].endswith("-") and text and text[0].islower():
            parts[-1] = parts[-1][:-1] + text
        else:
            parts.append(text)
    paragraph = " ".join(parts)
    paragraph = fix_minor_ocr_noise(paragraph)
    paragraph = re.sub(r"\s+", " ", paragraph).strip()
    return paragraph


def parse_text_to_markdown_body(text: str) -> tuple[str, dict[str, int]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    md_lines: list[str] = []
    para_buffer: list[str] = []
    footnotes: list[str] = []
    chapter_count = 0
    heading_count = 0

    def flush_paragraph():
        if not para_buffer:
            return
        paragraph = join_paragraph_lines(para_buffer)
        para_buffer.clear()
        if paragraph:
            md_lines.append(f"{paragraph}\n")

    i = 0
    while i < len(lines):
        raw = lines[i].rstrip()
        line = clean_inline_text(raw)
        if not line:
            flush_paragraph()
            i += 1
            continue

        prev_blank = i == 0 or not clean_inline_text(lines[i - 1])
        next_blank = i + 1 >= len(lines) or not clean_inline_text(lines[i + 1])

        footnote_match = FOOTNOTE_RE.match(line)
        if footnote_match and prev_blank:
            flush_paragraph()
            footnote_text = clean_inline_text(footnote_match.group(3))
            if footnote_text:
                footnotes.append(footnote_text)
            i += 1
            continue

        if prev_blank and looks_like_chapter_heading(line):
            flush_paragraph()
            chapter_count += 1
            chapter_label = clean_inline_text(line)
            chapter_subtitle = ""

            probe = i + 1
            while probe < len(lines) and not clean_inline_text(lines[probe]):
                probe += 1
            if probe < len(lines):
                candidate = clean_inline_text(lines[probe])
                if candidate and looks_like_display_heading(candidate) and not looks_like_chapter_heading(candidate):
                    next_after_probe_blank = probe + 1 >= len(lines) or not clean_inline_text(lines[probe + 1])
                    if next_after_probe_blank:
                        chapter_subtitle = candidate
                        i = probe

            md_lines.append(rf"\chapterlabelline{{{escape_latex_text(chapter_label)}}}")
            if chapter_subtitle:
                md_lines.append(rf"\chaptersubtitleline{{{escape_latex_text(chapter_subtitle)}}}")
            md_lines.append("")
            i += 1
            continue

        if prev_blank and next_blank and looks_like_display_heading(line):
            flush_paragraph()
            heading_count += 1
            md_lines.append(rf"\displayheading{{{escape_latex_text(line)}}}")
            md_lines.append("")
            i += 1
            continue

        para_buffer.append(line)
        i += 1

    flush_paragraph()

    if footnotes:
        md_lines.append(r"\displayheading{Source Notes}")
        md_lines.append("")
        for idx, note in enumerate(footnotes, start=1):
            md_lines.append(rf"\noindent[{idx}]: {escape_latex_text(note)}\par")
        md_lines.append("")

    body = "\n\n".join(md_lines)
    body = repair_hyphenation(body)
    body = fix_minor_ocr_noise(body)
    body = normalize_blank_lines(body)
    return body, {
        "chapters_detected": chapter_count,
        "display_headings_detected": heading_count,
        "footnotes_collected": len(footnotes),
    }


def assemble_markdown(title: str, author: str, volume: str, publication_date: str, source_text: str) -> tuple[str, dict[str, int]]:
    body, stats = parse_text_to_markdown_body(source_text)
    front = build_title_page_markdown(title, author, volume, publication_date)
    markdown = normalize_blank_lines(front + "\n" + body)
    return markdown, stats


def parse_epub_text(epub_path: Path) -> SourceText:
    with zipfile.ZipFile(epub_path, "r") as archive:
        try:
            container_xml = archive.read("META-INF/container.xml")
        except KeyError as exc:
            raise RuntimeError("EPUB is missing META-INF/container.xml.") from exc
        container_root = ET.fromstring(container_xml)
        rootfile_path = ""
        for element in container_root.iter():
            if element.tag.endswith("rootfile"):
                rootfile_path = element.attrib.get("full-path", "")
                if rootfile_path:
                    break
        if not rootfile_path:
            raise RuntimeError("EPUB container.xml did not provide a package path.")
        opf_data = archive.read(rootfile_path)
        opf_root = ET.fromstring(opf_data)
        opf_dir = PurePosixPath(rootfile_path).parent

        title = ""
        author = ""
        publication_date = ""
        for element in opf_root.iter():
            local = element.tag.split("}")[-1].lower()
            if local == "title" and not title and element.text:
                title = clean_inline_text(element.text)
            elif local == "creator" and not author and element.text:
                author = clean_inline_text(element.text)
            elif local == "date" and not publication_date and element.text:
                publication_date = clean_inline_text(element.text)

        manifest_by_id: dict[str, tuple[str, str]] = {}
        for element in opf_root.iter():
            if element.tag.split("}")[-1].lower() == "item":
                item_id = element.attrib.get("id", "")
                href = element.attrib.get("href", "")
                media_type = element.attrib.get("media-type", "")
                if item_id and href:
                    manifest_by_id[item_id] = (href, media_type)

        spine_items: list[str] = []
        for element in opf_root.iter():
            if element.tag.split("}")[-1].lower() == "itemref":
                idref = element.attrib.get("idref", "")
                if idref:
                    spine_items.append(idref)

        html_chunks: list[str] = []
        for idref in spine_items:
            href, media_type = manifest_by_id.get(idref, ("", ""))
            if not href:
                continue
            if "html" not in media_type and not href.lower().endswith((".xhtml", ".html", ".htm")):
                continue
            item_path = str((opf_dir / href).as_posix())
            try:
                html_data = archive.read(item_path)
            except KeyError:
                continue
            html_text = decode_text_bytes(html_data)
            html_text, _ = strip_html_toc_section(html_text)
            html_chunks.append(html_to_text(html_text))

        if not html_chunks:
            raise RuntimeError("EPUB did not contain readable HTML/XHTML spine content.")

    merged = "\n\n".join(chunk.strip() for chunk in html_chunks if chunk.strip())
    merged = normalize_blank_lines(merged)
    return SourceText(
        text=merged,
        source_label=str(epub_path),
        title=title,
        author=author,
        publication_date=publication_date,
        source_type="epub",
    )


def fetch_gutenberg_by_id(book_id: str, prefer_html: bool) -> SourceText:
    errors: list[str] = []
    for url, kind in gutenberg_candidate_urls(book_id, prefer_html):
        try:
            body, content_type, final_url = fetch_url(url)
        except urllib.error.HTTPError as exc:
            errors.append(f"{url} -> HTTP {exc.code}")
            continue
        except Exception as exc:
            errors.append(f"{url} -> {exc}")
            continue
        if not body or len(body.strip()) < 800:
            errors.append(f"{url} -> content too short")
            continue
        if kind == "html" or "text/html" in content_type or final_url.lower().endswith((".html", ".htm")):
            body, _ = strip_html_toc_section(body)
            body = html_to_text(body)
        body = normalize_blank_lines(body)
        inferred = infer_metadata_from_text(body)
        return SourceText(
            text=body,
            source_label=final_url,
            title=inferred.get("title", ""),
            author=inferred.get("author", ""),
            publication_date=inferred.get("publication_date", ""),
            source_type=kind,
        )
    joined = "\n".join(errors[-8:]) if errors else "No candidate URLs succeeded."
    raise RuntimeError(f"Could not fetch Gutenberg book {book_id}.\n\n{joined}")


def read_local_source(path: Path) -> SourceText:
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return parse_epub_text(path)
    payload = path.read_bytes()
    text = decode_text_bytes(payload)
    source_type = "txt"
    if suffix in {".html", ".htm", ".xhtml"}:
        text, _ = strip_html_toc_section(text)
        text = html_to_text(text)
        source_type = "html"
    text = normalize_blank_lines(text)
    inferred = infer_metadata_from_text(text)
    return SourceText(
        text=text,
        source_label=str(path),
        title=inferred.get("title", ""),
        author=inferred.get("author", ""),
        publication_date=inferred.get("publication_date", ""),
        source_type=source_type,
    )


def load_source_text(source_input: str, prefer_html: bool) -> SourceText:
    source = source_input.strip()
    if not source:
        raise ValueError("Enter a Gutenberg ID/URL or choose a local source file.")

    source_path = Path(source)
    if source_path.exists() and source_path.is_file():
        return read_local_source(source_path)

    if source.startswith(("http://", "https://")):
        body, content_type, final_url = fetch_url(source)
        if "html" in content_type or final_url.lower().endswith((".html", ".htm", ".xhtml")):
            body, _ = strip_html_toc_section(body)
            body = html_to_text(body)
            source_type = "html"
        else:
            source_type = "txt"
        body = normalize_blank_lines(body)
        inferred = infer_metadata_from_text(body)
        return SourceText(
            text=body,
            source_label=final_url,
            title=inferred.get("title", ""),
            author=inferred.get("author", ""),
            publication_date=inferred.get("publication_date", ""),
            source_type=source_type,
        )

    book_id = parse_gutenberg_id(source)
    if not book_id:
        raise ValueError(
            "Source input was not a file path, URL, or Gutenberg numeric ID.\n"
            "Example IDs: 1342, 11, 1661"
        )
    return fetch_gutenberg_by_id(book_id, prefer_html=prefer_html)


class GutenbergToPDFGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Gutenberg to Print PDF")
        self.root.geometry("980x840")
        self.messages: queue.Queue = queue.Queue()
        self.worker_thread: threading.Thread | None = None

        self.source_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=str(Path.cwd()))
        self.title_var = tk.StringVar()
        self.author_var = tk.StringVar()
        self.volume_var = tk.StringVar()
        self.publication_date_var = tk.StringVar()
        self.prefer_html_var = tk.BooleanVar(value=False)
        self.save_source_copy_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self.root.after(150, self._poll_queue)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        row = 0
        ttk.Label(main, text="Gutenberg ID / URL / local file").grid(row=row, column=0, sticky="w")
        ttk.Entry(main, textvariable=self.source_var, width=82).grid(row=row, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(main, text="Browse file", command=self._choose_source_file).grid(row=row, column=2, sticky="ew")

        row += 1
        ttk.Label(main, text="Output folder").grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(main, textvariable=self.output_dir_var, width=82).grid(row=row, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
        ttk.Button(main, text="Browse", command=self._choose_output_dir).grid(row=row, column=2, sticky="ew", pady=(8, 0))

        row += 1
        ttk.Separator(main).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)

        row += 1
        ttk.Label(main, text="Title (optional override)").grid(row=row, column=0, sticky="w")
        ttk.Entry(main, textvariable=self.title_var, width=60).grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        row += 1
        ttk.Label(main, text="Author (optional override)").grid(row=row, column=0, sticky="w")
        ttk.Entry(main, textvariable=self.author_var, width=60).grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        row += 1
        ttk.Label(main, text="Volume / subtitle").grid(row=row, column=0, sticky="w")
        ttk.Entry(main, textvariable=self.volume_var, width=60).grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        row += 1
        ttk.Label(main, text="Publication date").grid(row=row, column=0, sticky="w")
        ttk.Entry(main, textvariable=self.publication_date_var, width=30).grid(row=row, column=1, sticky="w", padx=(8, 8))

        row += 1
        options = ttk.Frame(main)
        options.grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Checkbutton(options, text="Prefer Gutenberg HTML when available", variable=self.prefer_html_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(options, text="Save downloaded/cleaned source copy", variable=self.save_source_copy_var).grid(
            row=0, column=1, sticky="w", padx=(18, 0)
        )

        row += 1
        ttk.Separator(main).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)

        row += 1
        controls = ttk.Frame(main)
        controls.grid(row=row, column=0, columnspan=3, sticky="ew")
        self.run_button = ttk.Button(controls, text="Fetch, Convert, and Build PDF", command=self.start_run)
        self.run_button.grid(row=0, column=0, sticky="w")
        self.rebuild_button = ttk.Button(controls, text="Rebuild from existing book.md", command=self.start_rebuild_from_md)
        self.rebuild_button.grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(controls, textvariable=self.status_var).grid(row=0, column=2, sticky="w", padx=(12, 0))

        row += 1
        self.progress = ttk.Progressbar(main, mode="determinate")
        self.progress.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8, 8))

        row += 1
        ttk.Label(main, text="Log").grid(row=row, column=0, sticky="w")
        row += 1
        self.log_text = tk.Text(main, height=28, wrap="word")
        self.log_text.grid(row=row, column=0, columnspan=3, sticky="nsew")
        log_scroll = ttk.Scrollbar(main, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=row, column=3, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        main.columnconfigure(1, weight=1)
        main.rowconfigure(row, weight=1)

    def log(self, text: str):
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")

    def _choose_source_file(self):
        filename = filedialog.askopenfilename(
            title="Choose source file",
            filetypes=[
                ("Supported source files", "*.txt *.text *.html *.htm *.xhtml *.epub"),
                ("All files", "*.*"),
            ],
        )
        if filename:
            self.source_var.set(filename)

    def _choose_output_dir(self):
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.output_dir_var.set(folder)

    def _collect_config(self) -> dict[str, Any]:
        source_input = self.source_var.get().strip()
        if not source_input:
            raise ValueError("Enter a Gutenberg ID/URL or choose a local source file.")

        output_dir = Path(self.output_dir_var.get().strip())
        if not output_dir:
            raise ValueError("Choose an output folder.")

        return {
            "source_input": source_input,
            "output_dir": output_dir,
            "title_override": self.title_var.get().strip(),
            "author_override": self.author_var.get().strip(),
            "volume": self.volume_var.get().strip(),
            "publication_date_override": self.publication_date_var.get().strip(),
            "prefer_html": bool(self.prefer_html_var.get()),
            "save_source_copy": bool(self.save_source_copy_var.get()),
        }

    def _collect_rebuild_config(self) -> dict[str, Any]:
        output_dir = Path(self.output_dir_var.get().strip())
        if not output_dir:
            raise ValueError("Choose an output folder.")
        book_md = output_dir / "book.md"
        if not book_md.exists():
            raise ValueError(f"No book.md found in output folder:\n\n{book_md}")

        existing_metadata: dict[str, Any] = {}
        metadata_path = output_dir / "metadata.yaml"
        if metadata_path.exists():
            try:
                loaded = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing_metadata = loaded
            except Exception:
                existing_metadata = {}

        title = self.title_var.get().strip() or str(existing_metadata.get("title", "")).strip()
        author = self.author_var.get().strip() or str(existing_metadata.get("author", "")).strip()
        volume = self.volume_var.get().strip() or str(existing_metadata.get("subtitle", "")).strip()
        publication_date = self.publication_date_var.get().strip() or str(existing_metadata.get("date", "")).strip()
        if not title:
            raise ValueError("Enter a title (or ensure metadata.yaml contains one).")
        return {
            "output_dir": output_dir,
            "title": title,
            "author": author,
            "volume": volume,
            "publication_date": publication_date,
        }

    def start_run(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Already running", "A job is already running.")
            return
        try:
            cfg = self._collect_config()
        except ValueError as exc:
            messagebox.showerror("Input error", str(exc))
            return
        self.run_button.config(state="disabled")
        self.rebuild_button.config(state="disabled")
        self.progress["value"] = 0
        self.status_var.set("Starting...")
        self.log_text.delete("1.0", "end")
        self.worker_thread = threading.Thread(target=self._run_pipeline, args=(cfg,), daemon=True)
        self.worker_thread.start()

    def start_rebuild_from_md(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Already running", "A job is already running.")
            return
        try:
            cfg = self._collect_rebuild_config()
        except ValueError as exc:
            messagebox.showerror("Input error", str(exc))
            return
        self.run_button.config(state="disabled")
        self.rebuild_button.config(state="disabled")
        self.progress["value"] = 0
        self.status_var.set("Rebuilding...")
        self.log_text.delete("1.0", "end")
        self.worker_thread = threading.Thread(target=self._run_rebuild_from_md, args=(cfg,), daemon=True)
        self.worker_thread.start()

    def _queue_log(self, text: str):
        self.messages.put(("log", text))

    def _queue_status(self, text: str):
        self.messages.put(("status", text))

    def _queue_progress(self, value: int, maximum: int):
        self.messages.put(("progress", (value, maximum)))

    def _queue_done(self, success: bool, message: str):
        self.messages.put(("done", (success, message)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "log":
                    self.log(str(payload))
                elif kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "progress":
                    value, maximum = payload
                    self.progress["maximum"] = max(1, int(maximum))
                    self.progress["value"] = int(value)
                elif kind == "done":
                    success, message = payload
                    self.run_button.config(state="normal")
                    self.rebuild_button.config(state="normal")
                    self.status_var.set("Finished" if success else "Failed")
                    if success:
                        messagebox.showinfo("Done", message)
                    else:
                        messagebox.showerror("Error", message)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)

    def _run_pipeline(self, cfg: dict[str, Any]):
        try:
            output_dir: Path = cfg["output_dir"]
            output_dir.mkdir(parents=True, exist_ok=True)
            total_steps = 6

            self._queue_progress(1, total_steps)
            self._queue_status("Fetching source...")
            self._queue_log(f"Source input: {cfg['source_input']}")
            source = load_source_text(cfg["source_input"], prefer_html=cfg["prefer_html"])
            self._queue_log(f"Loaded source from: {source.source_label}")
            self._queue_log(f"Source format: {source.source_type}")

            self._queue_progress(2, total_steps)
            self._queue_status("Cleaning Project Gutenberg wrappers...")
            cleaned = strip_gutenberg_boilerplate(source.text)
            cleaned = normalize_blank_lines(cleaned)
            if len(cleaned) < 1200:
                raise RuntimeError(
                    "Source text is too short after cleanup. "
                    "Try a different URL/ID or use a local source file."
                )

            inferred = infer_metadata_from_text(cleaned)
            title = cfg["title_override"] or source.title or inferred.get("title", "") or "Untitled"
            author = cfg["author_override"] or source.author or inferred.get("author", "")
            publication_date = cfg["publication_date_override"] or source.publication_date or inferred.get("publication_date", "")
            volume = cfg["volume"]
            cleaned = strip_redundant_front_metadata(cleaned, title=title, author=author)
            cleaned, toc_lines_removed = strip_table_of_contents(cleaned)
            cleaned, front_matter_lines_removed = strip_front_matter_before_first_chapter(cleaned)
            self._queue_log(f"Resolved title: {title}")
            self._queue_log(f"Resolved author: {author or '(empty)'}")
            self._queue_log(f"Resolved publication date: {publication_date or '(empty)'}")
            self._queue_log(f"TOC lines removed: {toc_lines_removed}")
            self._queue_log(f"Pre-chapter front-matter lines removed: {front_matter_lines_removed}")

            self._queue_progress(3, total_steps)
            self._queue_status("Converting to structured markdown...")
            markdown, stats = assemble_markdown(title, author, volume, publication_date, cleaned)
            (output_dir / "book.md").write_text(markdown, encoding="utf-8")
            self._queue_log("Wrote book.md")
            self._queue_log(
                f"Detected chapters: {stats['chapters_detected']} | "
                f"display headings: {stats['display_headings_detected']} | "
                f"footnotes: {stats['footnotes_collected']}"
            )

            if cfg["save_source_copy"]:
                (output_dir / "source_cleaned.txt").write_text(cleaned, encoding="utf-8")
                self._queue_log("Wrote source_cleaned.txt")

            conversion_report = {
                "source_input": cfg["source_input"],
                "source_label": source.source_label,
                "source_type": source.source_type,
                "resolved_metadata": {
                    "title": title,
                    "author": author,
                    "volume": volume,
                    "publication_date": publication_date,
                },
                "stats": stats,
                "toc_lines_removed": toc_lines_removed,
                "front_matter_lines_removed": front_matter_lines_removed,
            }
            (output_dir / "gutenberg_conversion.json").write_text(
                json.dumps(conversion_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._queue_log("Wrote gutenberg_conversion.json")

            self._queue_progress(4, total_steps)
            self._queue_status("Writing print assets...")
            write_print_assets(output_dir, title, author, volume, publication_date)
            self._queue_log("Wrote metadata.yaml")
            self._queue_log("Wrote printer_template.tex")
            self._queue_log("Wrote build_print_pdf.sh")

            self._queue_progress(5, total_steps)
            self._queue_status("Building PDF with Pandoc/XeLaTeX...")
            build_pdf(output_dir)
            self._queue_log("Wrote print_ready.pdf")

            self._queue_progress(6, total_steps)
            self._queue_done(True, f"Finished successfully.\n\nFinal PDF:\n{output_dir / 'print_ready.pdf'}")
        except subprocess.CalledProcessError as exc:
            self._queue_done(False, f"PDF build failed.\n\n{exc}")
        except Exception as exc:
            self._queue_done(False, str(exc))

    def _run_rebuild_from_md(self, cfg: dict[str, Any]):
        try:
            output_dir: Path = cfg["output_dir"]
            self._queue_progress(1, 3)
            self._queue_status("Preparing print assets...")
            write_print_assets(output_dir, cfg["title"], cfg["author"], cfg["volume"], cfg["publication_date"])
            self._queue_log("Wrote metadata.yaml")
            self._queue_log("Wrote printer_template.tex")
            self._queue_log("Wrote build_print_pdf.sh")

            self._queue_progress(2, 3)
            self._queue_status("Building final PDF...")
            build_pdf(output_dir)

            self._queue_progress(3, 3)
            self._queue_done(True, f"Rebuild finished successfully.\n\nFinal PDF:\n{output_dir / 'print_ready.pdf'}")
        except subprocess.CalledProcessError as exc:
            self._queue_done(False, f"PDF build failed.\n\n{exc}")
        except Exception as exc:
            self._queue_done(False, str(exc))


def main():
    root = tk.Tk()
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    GutenbergToPDFGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
