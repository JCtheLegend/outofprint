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

1. In Supabase, make sure the `books` table has the `slug` column (see
   `website/supabase-schema.sql`) and that the `book-covers` (public) and
   `book-pdfs` (private) storage buckets exist.
2. In the GitHub repo: **Settings → Secrets and variables → Actions**, add:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY` (service role key — bypasses RLS, keep secret)
