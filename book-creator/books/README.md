# books/

Each subfolder here is one book, uploaded to Supabase automatically by
`.github/workflows/upload-books.yml` whenever it changes on `main` (or on
demand via **Actions → Upload Books to Supabase → Run workflow**).

## Folder layout

```
books/
  <slug>/                  ← folder name becomes the book's slug and storage filename
    metadata.json
    <interior>.pdf         ← filename referenced by metadata.json's interior_filename
    <paperback-cover>.pdf  ← filename referenced by paperback_cover_filename
    <hardcover-cover>.pdf  ← optional, referenced by hardcover_cover_filename
```

`<slug>` should be a short kebab-case name (e.g. `federalist-papers`) — it's
used as the object name in Supabase Storage and as the unique key the
uploader upserts the `books` table row on, so pushing the same folder again
updates that book instead of creating a duplicate.

## metadata.json

Besides whatever the book-formatting pipeline already writes into
`metadata.json` (title, authors, cover_facts, etc.), the uploader needs
four extra fields that the storefront requires but the pipeline doesn't
produce — add these by hand before pushing:

| field                 | example                              |
|-----------------------|---------------------------------------|
| `store_price_cents`   | `2400` (= $24.00)                     |
| `store_genre`         | `"Political Philosophy"`              |
| `store_description`   | one or two sentences for the catalog  |
| `store_featured`      | `true` / `false` — shows on homepage  |

### Multi-volume sets

A volume joins a set by declaring `store_set_slug`. Every volume of the same
work must use the same slug — the uploader upserts one `book_sets` row per
slug and points each book at it, and the storefront then lists the whole work
on `/catalog/set/<store_set_slug>` where a customer picks a single volume or
the complete set.

| field                      | example                                        |
|----------------------------|------------------------------------------------|
| `store_set_slug`           | `"froude-history-of-england"` (required to group) |
| `store_set_title`          | `"History of England"` (defaults to `title`)   |
| `store_set_description`    | a sentence about the whole work                 |
| `store_set_genre`          | defaults to `store_genre`                       |
| `store_set_price_cents`    | `12000` — bundle price for **all** volumes; omit to charge the volumes' sum |
| `store_set_featured`       | `true` / `false` — shows the set on the homepage |

The volume's own number comes from the pipeline's `volume_number`, or is
parsed from `volume` (`"Volume III"`, `"Volume 1"` and a bare `1` all work).
It orders the volumes on the set page and prints as the badge on the cover.

`store_set_price_cents` is only written to `book_sets` when a volume actually
declares it, so setting a bundle price on one volume (or editing it directly
in Supabase) survives re-uploading a sibling volume that omits it. Until a
bundle price exists, "buy the complete set" simply charges every volume.

The uploader also uses `interior_filename` and `paperback_cover_filename`
(to know which PDFs to upload/crop), `authors`, `publication_year`, and
`cover_facts.paperback.{front_panel_width_in,bleed_in}` (to crop a plain
front-cover image out of the print-ready wraparound cover PDF).

## Running it locally

```bash
cd book-creator
pip install -r scripts/requirements.txt
export SUPABASE_URL=https://your-project.supabase.co
export SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
python scripts/upload_to_supabase.py federalist-papers   # one book
python scripts/upload_to_supabase.py                     # all books
python scripts/upload_to_supabase.py --dry-run federalist-papers  # just check the cover crop
```

## One-time setup

1. In Supabase, run `website/supabase-schema.sql` so the `books` table has the
   `slug`, `set_id`, `volume_number` and `volume_label` columns and the
   `book_sets` table exists, and that the `book-covers` (public) and
   `book-pdfs` (private) storage buckets exist.
2. In the GitHub repo: **Settings → Secrets and variables → Actions**, add:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY` (service role key — bypasses RLS, keep secret)
