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
npm run build               # next build (hits the real Supabase; prebuild clears the fetch cache)
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
   `/api/webhooks/stripe` → an `orders` row per book, **one Lulu print job for the
   whole checkout** (`lib/print.ts`), and a Resend confirmation email (`lib/email.ts`).

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
  up", and it is capped at that sum, since volume prices move with Lulu's costs. `lib/sets.ts` (`setPriceCents`, `setSavingsCents`) is the only place that
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
  unique on `(stripe_session_id, book_id, format)`, not on `stripe_session_id` alone.

## Shopping cart

The cart is browser state — there are no accounts — held in `localStorage` by
`components/cart/CartProvider.tsx` and shaped by `lib/cart.ts`. It stores only
what a book *is* (`{kind: "book" | "set", id, quantity}`), never what it costs:
prices are resolved server-side at checkout, so a cart left open for weeks can
never buy at a stale price.

- `/cart` re-reads every row from the catalog before showing it, and silently
  drops entries whose book or set no longer exists.
- `/api/checkout` takes `{ items }`, and still accepts the older
  `{ bookId }` / `{ setId }` used by the "Buy now" buttons — both normalize to
  a cart of one. A single-item purchase returns to that book's or set's own
  success page; anything larger lands on `/cart/success`, which clears the cart.
- Each Stripe line item carries its book id in `price_data.product_data.metadata`.
  That is how the webhook knows what was bought: a cart of several books cannot
  fit in session metadata, which Stripe caps at 500 characters per value.
- `orders.quantity` records copies per book; the Lulu line item quantity matches,
  so two copies are one line item of two, not two jobs.

## Print fulfilment (Lulu)

Lulu prints and ships every order. `lib/lulu.ts` is the raw API layer (OAuth
client-credentials token, cached per isolate; `/print-jobs/` endpoints);
`lib/print.ts` maps an order onto it. Set `LULU_API_URL=https://api.sandbox.lulu.com`
to work against the sandbox, which never reaches a real printer.

- One checkout becomes **one print job with a line item per book**, so a set ships
  together. Every order row from that session stores the same `print_job_id`.
- Lulu downloads the PDFs itself, but `book-pdfs` is a private bucket, so
  `lib/storage.ts` signs `books.pdf_url` and `books.cover_pdf_url` at print time.
  Never hand Lulu a stored Storage URL directly — unsigned ones return 400.
- Lulu needs the **wraparound cover PDF** (`cover_pdf_url`), not the JPEG in
  `cover_url`, which is only the storefront thumbnail cropped out of it.
- `books.pod_package_id` is Lulu's product SKU, derived per book by the uploader
  from its trim size; null falls back to `LULU_POD_PACKAGE_ID`.
- A created job is `UNPAID` until Lulu charges the card on file. If print job
  creation fails the orders stay `paid` (not `printing`), which marks them as
  needing a resubmitted print job.
- `npm run lulu:test -- <book-slug>` checks credentials, signed URLs and the
  payload without placing an order; `--submit` creates a sandbox job, and
  `--list` / `--status <id>` report on jobs already sent.
- Lulu requires every font in an interior to be embedded **TrueType**; one
  OpenType face rejects the whole job, after payment. The uploader refuses such
  a book up front (`check_interior_fonts`), so a rejection surfaces at upload
  time instead. `--skip-font-check` overrides it.

## Pricing

A book's price is **Lulu's print cost plus a flat $10**, never typed in by hand.
`book-creator/scripts/lulu_pricing.py` quotes Lulu's `/print-job-cost-calculations/`
for the interior's page count and `pod_package_id` at upload time and writes
`page_count`, `print_cost_cents` and `price_cents` (= cost + `PRICE_MARGIN_CENTS`).
The upload workflow re-prices every book weekly with `--price-only`.

- The storefront keeps treating `price_cents` as the price; nothing on the site
  recomputes it. Static catalog pages only show a new price after a rebuild,
  while checkout always charges the row as it stands.
- A wholesale promo code (any of the comma-separated `WHOLESALE_PROMO_CODES`,
  checked in `lib/pricing.ts`) is entered in the cart and sent to `/api/checkout`
  as `promoCode`. It charges `print_cost_cents` for every book — sets volume by
  volume, with no bundle discount — and tags the Stripe session
  `pricing: wholesale`. An unknown code is a 400, never silently ignored.
- Shipping and sales tax are what Lulu charges for the whole cart, from
  `quoteOrderCharges` in `lib/shipping.ts`: shipping plus its per-order fulfilment
  fee as one Stripe shipping option, and Lulu's `total_tax` (on books, shipping and
  fee) as a separate "Sales tax" line item — promo code or not. Book prices stay
  pre-tax so they match the catalog.
- Lulu taxes at the destination's local rate (0% in Oregon and the UK, over 10% in
  Seattle) and will only quote a postcode together with its state or province.
  Hosted Checkout can't re-price after the address is typed, so the customer fills
  in country, state/province and postcode first (`ShipToFields`, remembered in
  localStorage) and `/api/checkout` takes it as `destination`. A bare `country`
  (from a cached page) is quoted at a fixed national address instead. Checkout
  only accepts addresses in that country; Stripe can't hold the customer to the
  state, so the webhook logs a warning when the address typed differs from the
  postcode tax was quoted for (`taxRegion` / `taxPostcode` in session metadata).
  The country and region lists live in `lib/shipping-countries.ts` so client code
  can import them without the Lulu client.
- Cloudflare in front of Lulu's API rejects Python's default `urllib`
  User-Agent, so the uploader sends its own.

## Formats (paperback and hardcover)

Every book is a perfect-bound paperback; most are also a casewrap hardcover. The
paperback keeps the columns `books` always had (`price_cents`, `print_cost_cents`,
`cover_pdf_url`, `pod_package_id`); the hardcover has `hardcover_` counterparts,
null when the book folder has no `hardcover_cover_filename`. `lib/formats.ts` is
the only place that picks a column by format — go through it.

- A cart item, a Stripe line item's product metadata (`{ bookId, format }`) and an
  order row all carry `format`; anything without one is a paperback, so older carts
  and sessions still work. The same book in both formats is two cart lines and two
  order rows.
- A hardcover prints from its own wraparound (`hardcover_cover_pdf_url`) and SKU
  (the paperback SKU with `CW` for `PB`). `hasFormat` requires all three hardcover
  columns so a hardcover can never fall back to the paperback's cover or SKU.
- A set is bought in one format across every volume, and only in a format every
  volume has (`commonFormats`). The bundle price is a paperback price; a hardcover
  set is its volumes' hardcover prices added up.

## Book page

`/catalog/[id]` shows the edition's own facts, not marketing copy: most books
have no `store_description`, so the uploader stores what the pipeline recorded
in `books.details` (subtitle, original publication, language, translator,
sources, what was omitted, and contents from the interior PDF's top-level
bookmarks). It also renders the first 12 interior pages and the whole wraparound
cover into the **public** `book-covers` bucket (`preview_urls`, `full_cover_url`).
The interior PDF itself stays private — never link to it from the site.

- `details` comes from hand-written metadata and is not uniform (`included_scope`
  is a sentence in one book, a list of `{title, subtitle}` works in another).
  Always read it through `readBookDetails` (`lib/details.ts`), which keeps only
  strings and string lists — rendering an object crashes the page. The uploader
  flattens it too (`_text` / `_text_list`), but the page must not trust that.

## Builds and errors

- Next caches every Supabase response a static page fetches in
  `.next/cache/fetch-cache`, and **reuses it on the next build** — builds were
  serving weeks-old catalog data, and corrupted entries baked 65 working books
  into the build as 404s. The `prebuild` script deletes that directory, and
  `npm run build:cf` runs `npm run build`, so deploys read the live catalog.
- Page data loaders (`getBook`, `getSetBySlug`) return null only for a genuinely
  missing row (`PGRST116`) and **throw on any other error**, so a failed query
  fails the build loudly instead of quietly publishing a 404.
- `app/error.tsx` catches a page that throws (inside the normal layout, showing
  the error digest as a reference), `app/global-error.tsx` a failed root layout,
  and `app/not-found.tsx` a missing book, set or order.

## Order tracking

Lulu is a B2B printer: print jobs live in our developer portal behind our login,
and there is no page a customer can be linked to. So the customer-facing view is
ours — `/orders/<order id>`, linked from every confirmation email.

- The order id is an unguessable UUID and is the only key, like a Shopify order
  status link. The page shows the books, their stage and any tracking links, and
  deliberately never the shipping address or email.
- It shows every row sharing the order's `stripe_session_id`, so one link covers
  a whole cart.
- `/api/webhooks/lulu` receives `PRINT_JOB_STATUS_CHANGED`. Lulu signs the raw
  body with HMAC-SHA256 keyed on `LULU_CLIENT_SECRET` and sends the hex digest in
  `Lulu-HMAC-SHA256`; `verifyLuluWebhook` checks it with WebCrypto.
- The route maps Lulu's status onto `orders.status`, stores tracking on the row
  whose id matches the line item's `external_id`, and emails the carrier link on
  the transition into `shipped` — only that transition, so redeliveries are quiet.
- Never fail the route for anything but a real error: Lulu retries five times and
  then deactivates the subscription.
- `npm run lulu:test -- --webhooks` lists subscriptions;
  `--register-webhook <url>` creates one (add `--test` for a dummy submission).
  Subscriptions are per environment, like Stripe's.

## Cancellation and refunds

`LULU_PRODUCTION_DELAY_MINUTES` (1440 — 24 hours) is how long Lulu holds a job
before production **and** how long a customer has to cancel, so the published
policy and the printer's behaviour are the same number and cannot drift.

- `/orders/<id>` offers cancellation while the window is open; `/api/orders/<id>/cancel`
  does the work, keyed only on the order id, the same capability that opens the page.
- Order of operations is deliberate: **stop the printer, then refund, then record it.**
- The refund is what was paid **less Stripe's processing fee**, read from the charge's
  balance transaction (`lib/refunds.ts`). Stripe keeps its fee on a refund, so a full
  refund cost us the fee. `/policies`, the cancel button and the email all say so, and
  `orders.refund_cents` records the amount.
  A refund against a book already printing is the expensive mistake; a canceled job
  whose refund or bookkeeping failed is recoverable by retrying.
- Lulu allows `CREATED`, `UNPAID`, `PAYMENT_IN_PROGRESS` and `PRODUCTION_DELAYED`
  to be canceled, nothing later — `cancelPrintJob` returns null when it is too late
  and the route answers 409 rather than refunding a book that will still ship.
- One checkout is one print job, so cancelling covers every book in that session.
- `/policies` states the window and derives it from the same setting.

## Submissions

A reader asking for a book posts to `/api/submissions`, which saves the row and
sends two emails: an acknowledgement to them, and an alert to the team at
`SUBMISSIONS_NOTIFY_EMAIL` with the request and a `replyTo` of the submitter, so
answering is a reply rather than a copy-paste out of the database.

- Both sends are **awaited**. A promise left floating when the response returns
  can be cancelled along with the isolate, so "non-blocking" mail is mail that
  may never leave — that is why the first real submission was never acknowledged.
- A failed send never loses the request: the row is already saved, and failures
  are logged rather than returned.

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
