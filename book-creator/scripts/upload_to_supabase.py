#!/usr/bin/env python3
"""Upload book cover images, interior PDFs, and metadata to Supabase.

Reads one or more folders under book-creator/books/<slug>/, each containing
a metadata.json plus the PDFs it references. For every book this:

  1. Rasterizes the paperback cover PDF and crops it to the front panel
     (using the bleed/panel-width facts already recorded in metadata.json)
     to produce a plain cover image.
  2. Uploads that cover image to the `book-covers` storage bucket, and both
     print-ready PDFs — the interior and the wraparound paperback cover, which
     is what Lulu prints from — to the private `book-pdfs` storage bucket.
  3. Upserts a row into the `books` table, keyed by slug (the folder name),
     so re-running this script for the same book updates it in place
     instead of creating a duplicate.
  4. For a volume of a multi-volume work (metadata.json carries
     `store_set_slug`), upserts the matching `book_sets` row and points the
     book at it, so the storefront can list the whole set on one page and
     sell either a single volume or the complete set.

Usage:
    python upload_to_supabase.py                # upload every book folder
    python upload_to_supabase.py federalist-papers   # upload just this one
    python upload_to_supabase.py --dry-run federalist-papers  # render only

Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment
(the service role key is required — storage writes and the books table
are locked down to public read-only via row level security).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

BOOKS_DIR = Path(__file__).resolve().parent.parent / "books"

COVER_BUCKET = "book-covers"
PDF_BUCKET = "book-pdfs"
COVER_RENDER_DPI = 300
REQUIRED_STORE_FIELDS = ("store_price_cents", "store_genre", "store_description")

# Words the pipeline puts in front of a volume designation, e.g. "Book IV"
VOLUME_WORDS = ("volume", "vol", "book", "part", "tome", "no")

# Lulu product SKU components after the trim size: black-and-white, standard
# quality, perfect bound, 60# cream stock, matte cover, no linen or foil. A book
# overrides the whole SKU with `store_pod_package_id` in its metadata.json.
POD_PACKAGE_SUFFIX = "BW.STD.PB.060UC444.MXX"

ROMAN_NUMERALS = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
    "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15,
    "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20,
}


def load_metadata(book_dir: Path) -> dict:
    metadata_path = book_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"no metadata.json in {book_dir}")
    return json.loads(metadata_path.read_text())


def render_front_cover(book_dir: Path, metadata: dict) -> bytes:
    """Rasterize the paperback cover PDF and crop out just the front panel.

    The cover PDF is a single wide page laid out (left to right) as
    bleed | back panel | spine | front panel | bleed, with matching bleed
    on the top/bottom edges. We crop using physical inches from the PDF's
    own page size rather than trusting any pixel values in metadata, so
    this stays correct regardless of what DPI the cover was designed at.
    """
    cover_filename = metadata.get("paperback_cover_filename")
    if not cover_filename:
        raise ValueError("metadata.json is missing paperback_cover_filename")
    cover_path = book_dir / cover_filename
    if not cover_path.exists():
        raise FileNotFoundError(f"cover PDF not found: {cover_path}")

    cover_facts = metadata.get("cover_facts", {}).get("paperback", {})
    front_panel_width_in = cover_facts.get("front_panel_width_in")
    bleed_in = cover_facts.get("bleed_in", 0) or 0
    if not front_panel_width_in:
        raise ValueError(
            "metadata.json cover_facts.paperback.front_panel_width_in is required to crop the front cover"
        )

    with fitz.open(cover_path) as doc:
        page = doc[0]
        page_width_in = page.rect.width / 72
        page_height_in = page.rect.height / 72

        crop = fitz.Rect(
            (page_width_in - bleed_in - front_panel_width_in) * 72,
            bleed_in * 72,
            (page_width_in - bleed_in) * 72,
            (page_height_in - bleed_in) * 72,
        )

        matrix = fitz.Matrix(COVER_RENDER_DPI / 72, COVER_RENDER_DPI / 72)
        pix = page.get_pixmap(matrix=matrix, clip=crop, alpha=False)
        png_bytes = pix.tobytes("png")

    # Re-encode as JPEG — smaller for a website thumbnail than the source PNG.
    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


def parse_volume_number(metadata: dict) -> int | None:
    """Volume number as an int, from `volume_number` or whatever `volume` holds.

    The pipeline writes `volume` inconsistently across books — "Volume III",
    "Book IV", "III", "Volume 1" or a bare 1 — so accept a leading volume word
    followed by either digits or a roman numeral.
    """
    raw = metadata.get("volume_number")
    if raw is None:
        raw = metadata.get("volume")
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw

    token = str(raw).strip().lower()
    for word in VOLUME_WORDS:
        if token.startswith(word):
            token = token[len(word):]
            break
    token = token.strip(" .:#")

    if token.isdigit():
        return int(token)
    return ROMAN_NUMERALS.get(token)


def volume_label(metadata: dict) -> str | None:
    """Human label for the volume, e.g. "Volume III" or "Book IV".

    A designation that already names its own unit ("Book IV") keeps that word —
    Carlyle's Friedrich is divided into books, not volumes.
    """
    raw = metadata.get("volume")
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.lower().startswith(VOLUME_WORDS):
            return text
        return f"Volume {text}"

    number = parse_volume_number(metadata)
    return f"Volume {number}" if number is not None else None


def build_pod_package_id(metadata: dict) -> str | None:
    """Lulu's SKU for this book, e.g. "0600X0900.BW.STD.PB.060UC444.MXX".

    Derived from the trim size the pipeline recorded, since everything else
    about the product is fixed by our print spec. Returns None when the trim
    size can't be parsed — the storefront then falls back to LULU_POD_PACKAGE_ID.
    """
    explicit = metadata.get("store_pod_package_id")
    if explicit:
        return explicit

    trim_size = str(metadata.get("trim_size") or "")
    match = re.match(r"\s*([\d.]+)\s*[x\u00d7X]\s*([\d.]+)", trim_size)
    if not match:
        return None

    width, height = (f"{round(float(value) * 100):04d}" for value in match.groups())
    return f"{width}X{height}.{POD_PACKAGE_SUFFIX}"


def build_set_row(metadata: dict) -> dict | None:
    """The `book_sets` row this book belongs to, or None if it stands alone.

    A book joins a set by declaring `store_set_slug` in metadata.json; every
    volume of the same work must use the same slug. `store_set_price_cents`
    is the optional bundle price — leave it out and the storefront charges the
    sum of the volumes.
    """
    set_slug = metadata.get("store_set_slug")
    if not set_slug:
        return None

    authors = metadata.get("authors") or []
    subtitle = metadata.get("subtitle")
    default_title = metadata["title"]

    return {
        "slug": set_slug,
        "title": metadata.get("store_set_title") or default_title,
        "author": ", ".join(authors) if authors else "Unknown",
        "description": metadata.get("store_set_description") or subtitle,
        "genre": metadata.get("store_set_genre") or metadata.get("store_genre"),
        "price_cents": metadata.get("store_set_price_cents"),
        "featured": bool(metadata.get("store_set_featured", False)),
    }


def build_book_row(
    slug: str,
    metadata: dict,
    cover_url: str,
    pdf_url: str,
    cover_pdf_url: str,
    set_id: str | None = None,
) -> dict:
    missing = [field for field in REQUIRED_STORE_FIELDS if metadata.get(field) is None]
    if missing:
        raise ValueError(f"metadata.json is missing required field(s): {', '.join(missing)}")

    authors = metadata.get("authors") or []
    year_raw = metadata.get("publication_year") or metadata.get("original_publication")
    try:
        year = int(str(year_raw)[:4])
    except (TypeError, ValueError):
        year = None

    return {
        "slug": slug,
        "title": metadata["title"],
        "author": ", ".join(authors) if authors else "Unknown",
        "year": year,
        "genre": metadata["store_genre"],
        "description": metadata["store_description"],
        "price_cents": metadata["store_price_cents"],
        "cover_url": cover_url,
        "pdf_url": pdf_url,
        "cover_pdf_url": cover_pdf_url,
        "pod_package_id": build_pod_package_id(metadata),
        "featured": bool(metadata.get("store_featured", False)),
        "set_id": set_id,
        "volume_number": parse_volume_number(metadata),
        "volume_label": volume_label(metadata),
    }


def upsert_set(client, set_row: dict, slug: str) -> str:
    """Create or update the set this volume belongs to and return its id.

    `price_cents` is only written when this book actually declares one, so a
    bundle price set on any one volume (or edited in Supabase) is not wiped
    out by re-uploading a sibling volume that omits it.
    """
    payload = {k: v for k, v in set_row.items() if not (k == "price_cents" and v is None)}
    print(f"[{slug}] upserting book_sets row '{set_row['slug']}'...")
    result = client.table("book_sets").upsert(payload, on_conflict="slug").execute()
    return result.data[0]["id"]


def upload_book(book_dir: Path, dry_run: bool = False) -> None:
    slug = book_dir.name
    metadata = load_metadata(book_dir)

    interior_filename = metadata.get("interior_filename")
    if not interior_filename:
        raise ValueError("metadata.json is missing interior_filename")
    interior_path = book_dir / interior_filename
    if not interior_path.exists():
        raise FileNotFoundError(f"interior PDF not found: {interior_path}")

    print(f"[{slug}] rendering front cover from paperback cover PDF...")
    cover_bytes = render_front_cover(book_dir, metadata)

    if dry_run:
        preview_path = book_dir / "_cover_preview.jpg"
        preview_path.write_bytes(cover_bytes)
        print(f"[{slug}] dry run — wrote {preview_path}, skipping Supabase upload")
        return

    from supabase import create_client

    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    client = create_client(supabase_url, supabase_key)

    cover_object = f"{slug}.jpg"
    pdf_object = f"{slug}.pdf"
    cover_pdf_object = f"{slug}_cover.pdf"

    print(f"[{slug}] uploading cover image ({len(cover_bytes):,} bytes)...")
    client.storage.from_(COVER_BUCKET).upload(
        cover_object, cover_bytes, {"content-type": "image/jpeg", "upsert": "true"}
    )
    cover_url = client.storage.from_(COVER_BUCKET).get_public_url(cover_object)

    pdf_bytes = interior_path.read_bytes()
    print(f"[{slug}] uploading interior PDF ({len(pdf_bytes):,} bytes)...")
    client.storage.from_(PDF_BUCKET).upload(
        pdf_object, pdf_bytes, {"content-type": "application/pdf", "upsert": "true"}
    )
    pdf_url = client.storage.from_(PDF_BUCKET).get_public_url(pdf_object)

    # The wraparound cover PDF is what Lulu wraps around the printed block; the
    # JPEG uploaded above is only the storefront thumbnail cropped out of it.
    cover_pdf_bytes = (book_dir / metadata["paperback_cover_filename"]).read_bytes()
    print(f"[{slug}] uploading print-ready cover PDF ({len(cover_pdf_bytes):,} bytes)...")
    client.storage.from_(PDF_BUCKET).upload(
        cover_pdf_object, cover_pdf_bytes, {"content-type": "application/pdf", "upsert": "true"}
    )
    cover_pdf_url = client.storage.from_(PDF_BUCKET).get_public_url(cover_pdf_object)

    set_row = build_set_row(metadata)
    set_id = upsert_set(client, set_row, slug) if set_row else None

    row = build_book_row(slug, metadata, cover_url, pdf_url, cover_pdf_url, set_id=set_id)
    print(f"[{slug}] upserting books row...")
    client.table("books").upsert(row, on_conflict="slug").execute()

    print(f"[{slug}] done.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "books",
        nargs="*",
        help="Book folder name(s) under book-creator/books/ to upload. Defaults to all folders.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Render the cover locally but skip the Supabase upload.")
    args = parser.parse_args()

    if args.books:
        book_dirs = [BOOKS_DIR / name for name in args.books]
    else:
        book_dirs = sorted(p for p in BOOKS_DIR.iterdir() if p.is_dir())

    failures = []
    for book_dir in book_dirs:
        if not book_dir.is_dir():
            failures.append(book_dir.name)
            print(f"[{book_dir.name}] ERROR: not a directory ({book_dir})", file=sys.stderr)
            continue
        try:
            upload_book(book_dir, dry_run=args.dry_run)
        except Exception as exc:  # surface each book's failure without aborting the rest of the batch
            failures.append(book_dir.name)
            print(f"[{book_dir.name}] ERROR: {exc}", file=sys.stderr)

    if failures:
        print(f"\nFailed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
