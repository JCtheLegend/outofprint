# Out of Print Press

Restores public-domain / out-of-circulation books into print-ready PDFs and sells
physical copies printed to order. Two halves of one repo:

- `book-creator/` — Python book-formatting pipeline plus the uploader that pushes
  finished books into Supabase.
- `website/` — Next.js 15 (App Router, React 19, Tailwind v4) storefront, deployed
  to Cloudflare Workers via `@opennextjs/cloudflare`.

There is no repo-root `package.json`; all npm commands run from `website/`.

## Commands

```bash
cd website
npm run dev                 # local dev server
npx tsc --noEmit            # typecheck — run this before calling work done
npm run build               # next build (hits the real Supabase for static params)
npm run build:cf            # opennextjs-cloudflare build
npm run deploy              # deploy to Cloudflare Workers
```

```bash
cd book-creator
pip install -r scripts/requirements.txt
python scripts/upload_to_supabase.py <folder>            # upload one book
python scripts/upload_to_supabase.py --dry-run <folder>  # render the cover only
```

There is no test suite. Verification is `npx tsc --noEmit`, `npx next lint --dir src`,
and a build.

## Data flow

1. A book lives in `book-creator/books/<slug>/` as `metadata.json` plus its interior
   and cover PDFs. The folder name is the slug and the storage object name.
2. `.github/workflows/upload-books.yml` runs `scripts/upload_to_supabase.py` on every
   push to `main` that touches `book-creator/books/**`. The script crops a front-cover
   JPEG out of the wraparound paperback cover PDF, uploads cover + interior to the
   `book-covers` / `book-pdfs` buckets, and upserts the `books` row **on `slug`**, so
   re-pushing a folder updates that book rather than duplicating it.
3. The storefront reads `books` / `book_sets` with the anon key (public read via RLS),
   and writes only through `supabaseAdmin()` on the server.
4. Purchase → `/api/checkout` creates a Stripe Checkout session → Stripe calls
   `/api/webhooks/stripe` → an `orders` row per book, a print job per book
   (`lib/print.ts`), and a Resend confirmation email (`lib/email.ts`).

`website/supabase-schema.sql` is the source of truth for the database and is written to
be safely re-runnable against an existing project. Schema changes belong there, as
`create table if not exists` / `alter table ... add column if not exists`, and must be
run by hand in the Supabase SQL editor — there is no migration tool.

## Multi-volume sets

A multi-volume work (e.g. Froude's *History of England*) is one `book_sets` row plus one
`books` row per volume, each volume pointing back via `books.set_id` and ordered by
`volume_number`. Volumes stay individually printable and purchasable — a set is a
grouping and a bundle price, never a separate product.

- A volume joins a set purely from metadata: `store_set_slug` in its `metadata.json`.
  Sibling volumes sharing that slug land in the same set. See
  `book-creator/books/README.md` for every `store_set_*` field.
- `book_sets.price_cents` is the optional bundle price. Null means "the volumes added
  up". `lib/sets.ts` (`setPriceCents`, `setSavingsCents`) is the only place that
  decides this — don't recompute set pricing inline.
- The catalog and homepage list one entry per work: `buildCatalogEntries()` replaces a
  set's volumes with a single `SetCard`. A set holding only one volume so far is listed
  as that plain book, so half-restored works don't advertise a set that isn't there.
- `/catalog/set/[slug]` sells either one volume or the whole set;
  `/catalog/[id]` (a single volume) offers the same two choices.
- `/api/checkout` takes `{ bookId }` **or** `{ setId }`. A set becomes one Stripe line
  item per volume, with any bundle discount spread proportionally across them so the
  session total matches the advertised set price to the cent.
- The webhook re-reads the volumes from `set_id` (metadata only carries the set id,
  since Stripe caps a metadata value at 500 characters) and creates one order row and
  one print job per volume — one physical book per print job. `orders` is therefore
  unique on `(stripe_session_id, book_id)`, not on `stripe_session_id` alone.

## Conventions

- Server components fetch data; `"use client"` is reserved for interaction
  (genre filter, checkout buttons, purchase panel).
- Money is integer cents everywhere; render it through `formatPrice` from
  `lib/format.ts` — never hand-format a dollar amount.
- Styling is Tailwind utilities plus the `.btn-primary` / `.btn-outline` /
  `.section-label` / `.input-field` component classes and the `cream`/`ink`/`rust`/
  `muted`/`border` theme colors defined in `app/globals.css`. Stay inside that palette.
- `next/image` is `unoptimized` (Cloudflare runs no image optimizer); remote images are
  allowlisted to `*.supabase.co` in `next.config.js`.
- Secrets live in `website/.env.local` (gitignored) and in GitHub Actions secrets for
  the uploader. Never commit keys, and never import `lib/stripe.ts` or `supabaseAdmin()`
  into a client component.
