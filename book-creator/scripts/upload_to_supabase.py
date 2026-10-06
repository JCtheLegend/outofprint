#!/usr/bin/env python3
"""Upload book cover images, interior PDFs, and metadata to Supabase.

Reads one or more folders under book-creator/books/<slug>/, each containing
a metadata.json plus the PDFs it references. For every book this:

  1. Checks the interior PDF's fonts — Lulu rejects any print job whose
     interior embeds OpenType fonts or leaves a font unembedded, so a book
     that would fail in production is refused here instead.
  2. Prices the paperback and the hardcover from Lulu's own print cost for
     the page count and each product SKU, plus a flat margin — see
     lulu_pricing.py.
  3. Rasterizes the paperback cover PDF and crops it to the front panel
     (using the bleed/panel-width facts already recorded in metadata.json)
     to produce a plain cover image, and renders the whole wraparound cover
     and the first interior pages as images for the book page.
  4. Uploads those images to the public `book-covers` storage bucket, and the
     print-ready PDFs — the interior and the paperback and hardcover
     wraparound covers, which is what Lulu prints from — to the private
     `book-pdfs` storage bucket.
  5. Upserts a row into the `books` table, keyed by slug (the folder name),
     so re-running this script for the same book updates it in place
     instead of creating a duplicate.
  6. For a volume of a multi-volume work (metadata.json carries
     `store_set_slug`), upserts the matching `book_sets` row and points the
     book at it, so the storefront can list the whole set on one page and
     sell either a single volume or the complete set.

Usage:
    python upload_to_supabase.py                # upload every book folder
    python upload_to_supabase.py federalist-papers   # upload just this one
    python upload_to_supabase.py --dry-run federalist-papers  # render only
    python upload_to_supabase.py --skip-font-check <book>     # upload despite bad fonts
    python upload_to_supabase.py --price-only                 # re-price from Lulu, upload nothing

Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment
(the service role key is required — storage writes and the books table
are locked down to public read-only via row level security), plus
LULU_CLIENT_KEY and LULU_CLIENT_SECRET to price each book.
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

import lulu_pricing

BOOKS_DIR = Path(__file__).resolve().parent.parent / "books"

COVER_BUCKET = "book-covers"
PDF_BUCKET = "book-pdfs"
COVER_RENDER_DPI = 300

# The book page's "look inside": the first pages of the interior, and the
# whole wraparound cover, as screen-resolution images. The interior PDF itself
# stays in the private bucket.
PREVIEW_PAGES = 12
PREVIEW_DPI = 110
REQUIRED_STORE_FIELDS = ("store_description",)

# The storefront's one list of genres, shared so the two can't drift apart. A
# book outside it would vanish from the catalog as soon as a reader picks a
# genre filter.
GENRES_PATH = Path(__file__).resolve().parents[2] / "website" / "src" / "lib" / "genres.json"
GENRES = tuple(json.loads(GENRES_PATH.read_text()))

# Words the pipeline puts in front of a volume designation, e.g. "Book IV"
VOLUME_WORDS = ("volume", "vol", "book", "part", "tome", "no")

# Lulu product SKU components after the trim size: black-and-white, standard
# quality, perfect bound, 60# cream stock, matte cover, no linen or foil. A book
# overrides the whole SKU with `store_pod_package_id` in its metadata.json.
# The hardcover is the same product bound as a casewrap (CW) instead of a
# perfect-bound paperback (PB); `store_hardcover_pod_package_id` overrides it.
POD_PACKAGE_SUFFIX = "BW.STD.{binding}.060UC444.MXX"

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


def check_interior_fonts(interior_path: Path) -> list[str]:
    """Report the font problems that make Lulu reject a print job.

    Lulu's normalizer requires every font to be embedded and to be TrueType —
    an interior carrying so much as one OpenType face is rejected, which
    otherwise only surfaces after a customer has paid.
    """
    opentype: set[str] = set()
    unembedded: set[str] = set()

    with fitz.open(interior_path) as doc:
        for page in doc:
            for font in page.get_fonts(full=True):
                ext, basefont = font[1], font[3]
                if ext == "otf":
                    opentype.add(basefont)
                elif ext in ("n/a", ""):
                    unembedded.add(basefont)

    problems = []
    if opentype:
        problems.append(
            "OpenType fonts (Lulu requires TrueType): " + ", ".join(sorted(opentype))
        )
    if unembedded:
        problems.append("fonts that are not embedded: " + ", ".join(sorted(unembedded)))
    return problems


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


def build_pod_package_id(metadata: dict, hardcover: bool = False) -> str | None:
    """Lulu's SKU for this book, e.g. "0600X0900.BW.STD.PB.060UC444.MXX".

    Derived from the trim size the pipeline recorded, since everything else
    about the product is fixed by our print spec. Returns None when the trim
    size can't be parsed — the storefront then falls back to LULU_POD_PACKAGE_ID
    for a paperback, and offers no hardcover.
    """
    explicit = metadata.get(
        "store_hardcover_pod_package_id" if hardcover else "store_pod_package_id"
    )
    if explicit:
        return explicit

    trim_size = str(metadata.get("trim_size") or "")
    match = re.match(r"\s*([\d.]+)\s*[x\u00d7X]\s*([\d.]+)", trim_size)
    if not match:
        return None

    width, height = (f"{round(float(value) * 100):04d}" for value in match.groups())
    binding = "CW" if hardcover else "PB"
    return f"{width}X{height}.{POD_PACKAGE_SUFFIX.format(binding=binding)}"


def hardcover_pod_package_id(book_dir: Path, metadata: dict) -> str | None:
    """The hardcover SKU, or None when the book has no hardcover cover to print."""
    filename = metadata.get("hardcover_cover_filename")
    if not filename or not (book_dir / filename).exists():
        return None
    return build_pod_package_id(metadata, hardcover=True)


def render_full_cover(cover_path: Path) -> bytes:
    """The whole wraparound cover — back, spine and front — as a JPEG."""
    with fitz.open(cover_path) as doc:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(PREVIEW_DPI / 72, PREVIEW_DPI / 72), alpha=False)
        return _jpeg(pix.tobytes("png"), quality=85)


def render_preview_pages(interior_path: Path) -> list[bytes]:
    """The first PREVIEW_PAGES interior pages as JPEGs."""
    matrix = fitz.Matrix(PREVIEW_DPI / 72, PREVIEW_DPI / 72)
    with fitz.open(interior_path) as doc:
        return [
            _jpeg(doc[i].get_pixmap(matrix=matrix, alpha=False).tobytes("png"), quality=80)
            for i in range(min(PREVIEW_PAGES, doc.page_count))
        ]


def _jpeg(png_bytes: bytes, quality: int) -> bytes:
    out = io.BytesIO()
    Image.open(io.BytesIO(png_bytes)).convert("RGB").save(out, format="JPEG", quality=quality)
    return out.getvalue()


def _text(value) -> str | None:
    """A plain string, or None — the storefront renders these as text."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _text_list(value) -> list[str]:
    """A list of strings from a string, a list of strings, or a list of works.

    metadata.json is not uniform: most books give `included_scope` as one
    sentence, some as a list of sentences, and one as a list of
    `{title, subtitle, first_publication}` works — which, stored as-is, the
    book page could not render. Every shape comes out as plain strings.
    """
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if isinstance(item, dict):
            title = _text(item.get("title"))
            if not title:
                continue
            subtitle = _text(item.get("subtitle"))
            year = _text(item.get("first_publication"))
            items.append(f"{title}{f': {subtitle}' if subtitle else ''}{f' ({year})' if year else ''}")
        elif _text(item):
            items.append(_text(item))
    return items


def build_details(metadata: dict, interior_path: Path) -> dict:
    """Facts about this edition for the book page, all from the pipeline.

    Nothing here is written for the store: it is what the pipeline recorded
    while restoring the book, so a book without a store description still has
    something true to say. The contents come from the interior PDF's own
    top-level bookmarks, when it has them.
    """
    with fitz.open(interior_path) as doc:
        contents = [title.strip() for level, title, _page in doc.get_toc() if level == 1 and title.strip()]

    source_basis = metadata.get("source_basis")
    sources = source_basis.get("sources", []) if isinstance(source_basis, dict) else []
    source_editions = []
    for source in sources:
        if isinstance(source, dict) and source.get("source_edition"):
            if source["source_edition"] not in source_editions:
                source_editions.append(source["source_edition"])

    details = {
        "subtitle": _text(metadata.get("subtitle")),
        "original_publication": _text(metadata.get("original_publication")),
        "language": _text(metadata.get("language")),
        "translator": _text(metadata.get("translator")),
        "editor": _text(metadata.get("editor")),
        "included_scope": _text_list(metadata.get("included_scope")),
        "trim_size": _text(metadata.get("trim_size")),
        "contents": contents,
        "source_editions": source_editions,
        "omitted": _text_list(metadata.get("intentionally_omitted_material")),
    }
    return {k: v for k, v in details.items() if v not in (None, "", [])}


def book_genre(metadata: dict) -> str:
    """The book's genre: its own `store_genre`, else its set's `store_set_genre`.

    Volumes of a set usually declare the genre once, on the set, so they
    inherit it. Refuses anything not in website/src/lib/genres.json.
    """
    genre = (metadata.get("store_genre") or metadata.get("store_set_genre") or "").strip()
    if not genre:
        raise ValueError(
            "metadata.json has no store_genre (nor a store_set_genre to inherit) — "
            f"choose one of: {', '.join(GENRES)}"
        )
    if genre not in GENRES:
        raise ValueError(
            f"store_genre {genre!r} is not a catalog genre — choose one of: {', '.join(GENRES)} "
            "(or add it to website/src/lib/genres.json)"
        )
    return genre


def set_genre(metadata: dict) -> str:
    """The set's genre: `store_set_genre`, else the volume's own."""
    genre = (metadata.get("store_set_genre") or "").strip()
    if genre and genre not in GENRES:
        raise ValueError(
            f"store_set_genre {genre!r} is not a catalog genre — choose one of: {', '.join(GENRES)}"
        )
    return genre or book_genre(metadata)


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
        "genre": set_genre(metadata),
        "price_cents": metadata.get("store_set_price_cents"),
        "featured": bool(metadata.get("store_set_featured", False)),
    }


def build_book_row(
    slug: str,
    metadata: dict,
    cover_url: str,
    pdf_url: str,
    cover_pdf_url: str,
    pricing: dict,
    set_id: str | None = None,
    *,
    hardcover_cover_pdf_url: str | None = None,
    hardcover_pod_package_id: str | None = None,
    full_cover_url: str | None = None,
    preview_urls: list[str] | None = None,
    details: dict | None = None,
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
        "genre": book_genre(metadata),
        "description": metadata["store_description"],
        "cover_url": cover_url,
        "pdf_url": pdf_url,
        "cover_pdf_url": cover_pdf_url,
        "pod_package_id": build_pod_package_id(metadata),
        "featured": bool(metadata.get("store_featured", False)),
        "set_id": set_id,
        "volume_number": parse_volume_number(metadata),
        "volume_label": volume_label(metadata),
        "hardcover_cover_pdf_url": hardcover_cover_pdf_url,
        "hardcover_pod_package_id": hardcover_pod_package_id if hardcover_cover_pdf_url else None,
        "full_cover_url": full_cover_url,
        "preview_urls": preview_urls or [],
        "details": details or {},
        **pricing,
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


def interior_path_for(book_dir: Path, metadata: dict) -> Path:
    interior_filename = metadata.get("interior_filename")
    if not interior_filename:
        raise ValueError("metadata.json is missing interior_filename")
    interior_path = book_dir / interior_filename
    if not interior_path.exists():
        raise FileNotFoundError(f"interior PDF not found: {interior_path}")
    return interior_path


def price_from_lulu(book_dir: Path, metadata: dict, interior_path: Path) -> dict:
    slug = book_dir.name
    page_count = lulu_pricing.interior_page_count(interior_path)
    pricing = lulu_pricing.price_book(
        build_pod_package_id(metadata),
        page_count,
        hardcover_pod_package_id(book_dir, metadata),
    )
    print(
        f"[{slug}] {page_count} pages — paperback costs "
        f"${pricing['print_cost_cents'] / 100:.2f} to print, selling at ${pricing['price_cents'] / 100:.2f}"
    )
    if pricing["hardcover_price_cents"] is not None:
        print(
            f"[{slug}] hardcover costs ${pricing['hardcover_print_cost_cents'] / 100:.2f}, "
            f"selling at ${pricing['hardcover_price_cents'] / 100:.2f}"
        )
    else:
        print(f"[{slug}] no hardcover cover — paperback only")
    return pricing


def supabase_client():
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def reprice_book(book_dir: Path) -> None:
    """Refresh a book's price from Lulu without re-uploading any files.

    Lulu's costs change now and then; this keeps the catalog in step without
    pushing every PDF again. Only updates a book that is already uploaded.
    """
    slug = book_dir.name
    metadata = load_metadata(book_dir)
    if metadata.get("publication_status") == "withdrawn":
        return

    pricing = price_from_lulu(book_dir, metadata, interior_path_for(book_dir, metadata))
    result = supabase_client().table("books").update(pricing).eq("slug", slug).execute()
    if not result.data:
        print(f"[{slug}] not in the books table yet — upload it first")


def upload_book(book_dir: Path, dry_run: bool = False, skip_font_check: bool = False) -> None:
    slug = book_dir.name
    metadata = load_metadata(book_dir)

    if metadata.get('publication_status') == 'withdrawn':
        print(f'[{slug}] withdrawn from publication; preserving archived files without uploading')
        return

    interior_path = interior_path_for(book_dir, metadata)

    # Before anything is uploaded: a book with no catalog genre can't be found
    genre = book_genre(metadata)
    if metadata.get("store_set_slug"):
        set_genre(metadata)
    print(f"[{slug}] genre: {genre}")

    if skip_font_check:
        print(f"[{slug}] skipping the font check (--skip-font-check)")
    else:
        problems = check_interior_fonts(interior_path)
        if problems:
            raise ValueError(
                "interior PDF would be rejected by Lulu — "
                + "; ".join(problems)
                + ". Rebuild it with TrueType fonts (convert the OpenType faces with "
                "fontTools' otf2ttf so the metrics, and so the page count and cover "
                "spine width, stay identical), or pass --skip-font-check to upload anyway."
            )
        print(f"[{slug}] interior fonts OK (all embedded TrueType)")

    # Priced before anything is uploaded, so a book Lulu can't quote never
    # reaches the catalog half-finished.
    if dry_run and not lulu_pricing.credentials_available():
        print(f"[{slug}] no Lulu credentials — skipping the price quote")
        pricing = None
    else:
        pricing = price_from_lulu(book_dir, metadata, interior_path)

    print(f"[{slug}] rendering front cover from paperback cover PDF...")
    cover_bytes = render_front_cover(book_dir, metadata)
    full_cover_bytes = render_full_cover(book_dir / metadata["paperback_cover_filename"])
    preview_pages = render_preview_pages(interior_path)
    details = build_details(metadata, interior_path)
    print(
        f"[{slug}] rendered {len(preview_pages)} preview pages; "
        f"{len(details.get('contents', []))} contents entries"
    )

    if dry_run:
        preview_path = book_dir / "_cover_preview.jpg"
        preview_path.write_bytes(cover_bytes)
        print(f"[{slug}] dry run — wrote {preview_path}, skipping Supabase upload")
        return

    client = supabase_client()

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

    hardcover_sku = hardcover_pod_package_id(book_dir, metadata)
    hardcover_cover_pdf_url = None
    if hardcover_sku:
        hardcover_object = f"{slug}_hardcover_cover.pdf"
        hardcover_bytes = (book_dir / metadata["hardcover_cover_filename"]).read_bytes()
        print(f"[{slug}] uploading hardcover cover PDF ({len(hardcover_bytes):,} bytes)...")
        client.storage.from_(PDF_BUCKET).upload(
            hardcover_object, hardcover_bytes, {"content-type": "application/pdf", "upsert": "true"}
        )
        hardcover_cover_pdf_url = client.storage.from_(PDF_BUCKET).get_public_url(hardcover_object)

    covers = client.storage.from_(COVER_BUCKET)
    full_cover_object = f"{slug}_full_cover.jpg"
    covers.upload(full_cover_object, full_cover_bytes, {"content-type": "image/jpeg", "upsert": "true"})
    full_cover_url = covers.get_public_url(full_cover_object)

    print(f"[{slug}] uploading {len(preview_pages)} preview pages...")
    preview_urls = []
    for number, page_bytes in enumerate(preview_pages, start=1):
        page_object = f"previews/{slug}/{number:02d}.jpg"
        covers.upload(page_object, page_bytes, {"content-type": "image/jpeg", "upsert": "true"})
        preview_urls.append(covers.get_public_url(page_object))

    set_row = build_set_row(metadata)
    set_id = upsert_set(client, set_row, slug) if set_row else None

    row = build_book_row(
        slug,
        metadata,
        cover_url,
        pdf_url,
        cover_pdf_url,
        pricing,
        set_id=set_id,
        hardcover_cover_pdf_url=hardcover_cover_pdf_url,
        hardcover_pod_package_id=hardcover_sku,
        full_cover_url=full_cover_url,
        preview_urls=preview_urls,
        details=details,
    )
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
    parser.add_argument(
        "--skip-font-check",
        action="store_true",
        help="Upload even if the interior's fonts would be rejected by Lulu.",
    )
    parser.add_argument(
        "--price-only",
        action="store_true",
        help="Re-price already-uploaded books from Lulu's current costs; upload no files.",
    )
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
            if args.price_only:
                reprice_book(book_dir)
            else:
                upload_book(book_dir, dry_run=args.dry_run, skip_font_check=args.skip_font_check)
        except Exception as exc:  # surface each book's failure without aborting the rest of the batch
            failures.append(book_dir.name)
            print(f"[{book_dir.name}] ERROR: {exc}", file=sys.stderr)

    if failures:
        print(f"\nFailed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
