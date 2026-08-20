#!/usr/bin/env python3
"""Upload book cover images, interior PDFs, and metadata to Supabase.

Reads one or more folders under book-creator/books/<slug>/, each containing
a metadata.json plus the PDFs it references. For every book this:

  1. Rasterizes the paperback cover PDF and crops it to the front panel
     (using the bleed/panel-width facts already recorded in metadata.json)
     to produce a plain cover image.
  2. Uploads that cover image to the `book-covers` storage bucket and the
     interior PDF to the `book-pdfs` storage bucket.
  3. Upserts a row into the `books` table, keyed by slug (the folder name),
     so re-running this script for the same book updates it in place
     instead of creating a duplicate.

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
import sys
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

BOOKS_DIR = Path(__file__).resolve().parent.parent / "books"

COVER_BUCKET = "book-covers"
PDF_BUCKET = "book-pdfs"
COVER_RENDER_DPI = 300
REQUIRED_STORE_FIELDS = ("store_price_cents", "store_genre", "store_description")


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


def build_book_row(slug: str, metadata: dict, cover_url: str, pdf_url: str) -> dict:
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
        "featured": bool(metadata.get("store_featured", False)),
    }


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

    row = build_book_row(slug, metadata, cover_url, pdf_url)
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
