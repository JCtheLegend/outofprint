# Out Of Print Press — Setup Guide

## What You're Building

A Next.js website with three pages (Home, Catalog, Submit), backed by:

- **Supabase** — database + file storage
- **Stripe** — payments and checkout
- **Resend** — transactional emails
- **Vercel** — hosting
- Your existing book-formatting pipeline and print API

---

## Prerequisites

- Node.js 18+ installed (`node -v` to check)
- A GitHub account
- A credit card (for Stripe and Vercel — both have free tiers)

---

## Step 1 — Install and Run Locally

```bash
# Clone or copy the project folder, then:
cd website
npm install

# Copy the environment template
cp .env.local.example .env.local
```

You'll fill in `.env.local` as you complete the steps below.

---

## Step 2 — Set Up Supabase (Database + Storage)

1. Go to [supabase.com](https://supabase.com) → **New Project**
2. Choose a name (e.g. `out-of-print-press`), set a database password, pick a region close to you
3. Once created, go to **SQL Editor** → **New Query**
4. Paste the entire contents of `supabase-schema.sql` and click **Run**
   (it is safe to re-run on an existing database — it adds the `book_sets`
   table and the multi-volume columns on `books` and `orders` in place)
5. Go to **Storage** → create three buckets:
   - `source-files` — toggle **Public** on
   - `book-covers` — toggle **Public** on
   - `book-pdfs` — leave **Private** (only your server accesses these)
6. Go to **Project Settings → API** and copy:
   - `Project URL` → `NEXT_PUBLIC_SUPABASE_URL`
   - `anon public` key → `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `service_role` key → `SUPABASE_SERVICE_ROLE_KEY`

Paste these into `.env.local`.

---

## Step 3 — Set Up Stripe (Payments)

1. Go to [dashboard.stripe.com](https://dashboard.stripe.com) → create an account if needed
2. Make sure you're in **Test mode** (toggle top-left) while developing
3. Go to **Developers → API keys** and copy:
   - Publishable key → `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`
   - Secret key → `STRIPE_SECRET_KEY`
4. Set up the webhook (needed to trigger print jobs after payment):
   - Go to **Developers → Webhooks → Add endpoint**
   - Endpoint URL: `https://your-domain.com/api/webhooks/stripe`
     (use a temporary URL for now — update after deploying to Vercel)
   - Events to listen for: `checkout.session.completed`
   - Copy the **Signing secret** → `STRIPE_WEBHOOK_SECRET`

**For local testing**, install the Stripe CLI and run:
```bash
stripe listen --forward-to localhost:3000/api/webhooks/stripe
# This gives you a local webhook secret to use in .env.local
```

---

## Step 4 — Set Up Resend (Emails)

1. Go to [resend.com](https://resend.com) → create an account
2. Go to **API Keys → Create API Key** → copy it → `RESEND_API_KEY`
3. Go to **Domains → Add Domain** and follow the DNS instructions for your domain
4. Set `RESEND_FROM_EMAIL` to something like `orders@yourdomain.com`

> Until you verify a domain, Resend lets you send from `onboarding@resend.dev` for testing.

---

## Step 5 — Connect Lulu (Printing and Fulfilment)

Every paid order is sent to [Lulu](https://developers.lulu.com) as a print job:
one line item per book, printed and shipped straight to the customer.

1. Create an account at [developers.lulu.com](https://developers.lulu.com) — and a
   separate one at [developers.sandbox.lulu.com](https://developers.sandbox.lulu.com)
   for testing, since sandbox jobs never reach a real printer.
2. Go to **Profile → API Keys** and copy the client key and secret into
   `LULU_CLIENT_KEY` / `LULU_CLIENT_SECRET`.
3. Set `LULU_API_URL=https://api.sandbox.lulu.com` while testing; switch it to
   `https://api.lulu.com` (with production credentials) to print for real.
4. Set `LULU_CONTACT_EMAIL` (Lulu contacts this address about problem jobs) and
   `LULU_DEFAULT_PHONE` (a fallback for the shipping address — carriers require a
   phone number; Stripe collects the customer's own at checkout).
5. **Put a credit card on file in the Lulu developer portal.** A newly created
   print job stays `UNPAID` until it is paid; with a card on file Lulu pays it and
   moves it to production automatically. Without one, nothing gets printed.

Check the whole path before taking a real order — this resolves the book's signed
PDF URLs, fetches them the way Lulu will, and (with `--submit`) creates a sandbox
print job:

```bash
npm run lulu:test -- federalist-papers
npm run lulu:test -- federalist-papers --submit
```

### Order status updates

Lulu pushes every print job status change to the site, which records it against
the order and emails the customer their tracking link when it ships. Subscribe
the endpoint once per environment:

```bash
npm run lulu:test -- --register-webhook https://outofprintpress.store/api/webhooks/lulu --test
npm run lulu:test -- --webhooks     # confirm it is active
```

Deliveries are signed with your API secret, so no extra configuration is needed.
Lulu deactivates a subscription after five consecutive failed deliveries — if
status updates stop arriving, check `--webhooks` for `INACTIVE`.

### Print product

Books default to `0600X0900.BW.STD.PB.060UC444.MXX` — a 6" x 9" black-and-white
paperback, perfect bound on 60# cream stock with a matte cover. The uploader
derives that SKU per book from its trim size; override it for one book with
`store_pod_package_id` in its `metadata.json`, or globally with
`LULU_POD_PACKAGE_ID`. Lulu's [price calculator](https://developers.lulu.com/price-calculator)
generates the SKU for any other product.

---

## Step 6 — Run Locally

```bash
npm run dev
# Open http://localhost:3000
```

The site will show "No featured books yet" until you add books via Supabase.

### Adding your first book

In Supabase: **Table Editor → books → Insert Row**

Required fields:
| Field | Example |
|-------|---------|
| title | The Marsh Chronicles |
| author | E.L. Hartwell |
| year | 1891 |
| genre | Fiction |
| description | A sweeping tale... |
| price_cents | 2400 (= $24.00) |
| pdf_url | Paste the public URL from your `book-pdfs` bucket |
| featured | true (shows on homepage) |

Upload your print-ready PDF to the `book-pdfs` bucket first, then copy its URL into `pdf_url`.


### 7 — Update Your Stripe Webhook

After deploying:
1. Go back to Stripe → **Developers → Webhooks**
2. Update the endpoint URL to `xyz`
3. Update `STRIPE_WEBHOOK_SECRET` in Vercel's environment variables with the live webhook secret

---

## Step 8 — Custom Domain

### Buy a domain

Good registrars: **Namecheap** (~$10–15/yr), **Cloudflare Registrar** (at-cost pricing), **Google Domains** (now Squarespace).

### Update environment variable

In Vercel, update `NEXT_PUBLIC_SITE_URL` from `https://out-of-print-press.vercel.app` to `https://outofprintpress.com`.

---

## Step 9 — Go Live with Stripe

When you're ready to take real payments:

1. In Stripe, toggle from **Test mode** to **Live mode**
2. Copy the live API keys (they start with `pk_live_` and `sk_live_`)
3. Update `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` and `STRIPE_SECRET_KEY` in Vercel
4. Create a new live webhook endpoint pointing to your domain
5. Update `STRIPE_WEBHOOK_SECRET` with the live signing secret

---

## File Structure Reference

```
website/
├── src/
│   ├── app/
│   │   ├── page.tsx                  ← Home page
│   │   ├── layout.tsx                ← Nav, fonts, footer
│   │   ├── globals.css
│   │   ├── catalog/
│   │   │   ├── page.tsx              ← Catalog listing
│   │   │   ├── CatalogClient.tsx     ← Genre filter (client)
│   │   │   ├── [id]/
│   │   │   │   ├── page.tsx          ← Individual book (or single volume) page
│   │   │   │   ├── CheckoutButton.tsx    ← Buy this book / buy its whole set
│   │   │   │   └── success/page.tsx  ← Post-purchase page
│   │   │   └── set/[slug]/
│   │   │       ├── page.tsx          ← Multi-volume set page
│   │   │       ├── SetPurchasePanel.tsx  ← Pick one volume or the set (client)
│   │   │       └── success/page.tsx  ← Post-purchase page
│   │   ├── orders/[id]/page.tsx      ← Customer order status page
│   │   ├── cart/
│   │   │   ├── page.tsx              ← Cart page
│   │   │   ├── CartClient.tsx        ← Cart UI (client)
│   │   │   └── success/page.tsx      ← Post-purchase, clears the cart
│   │   ├── submit/
│   │   │   ├── page.tsx              ← Submission page
│   │   │   └── SubmissionForm.tsx    ← Form (client)
│   │   └── api/
│   │       ├── checkout/route.ts     ← Creates Stripe session
│   │       ├── submissions/route.ts  ← Saves submission + uploads file
│   │       ├── webhooks/stripe/route.ts  ← Fires print job after payment
│   │       └── webhooks/lulu/route.ts    ← Print status + tracking updates
│   ├── components/
│   │   ├── cart/
│   │   │   ├── CartProvider.tsx      ← localStorage cart + useCart()
│   │   │   └── AddToCartButton.tsx
│   │   ├── layout/Nav.tsx
│   │   └── ui/
│   │       ├── BookCard.tsx
│   │       └── SetCard.tsx           ← One card standing for a whole set
│   └── lib/
│       ├── supabase.ts               ← DB client + types
│       ├── cart.ts                   ← Cart model + storage
│       ├── sets.ts                   ← Volume grouping + set pricing
│       ├── stripe.ts                 ← Stripe client
│       ├── print.ts                  ← Order → Lulu print job
│       ├── lulu.ts                   ← Lulu API client (auth + endpoints)
│       ├── storage.ts                ← Signed URLs for the private PDFs
│       └── email.ts                  ← Resend email helpers
├── supabase-schema.sql               ← Run once in Supabase SQL editor
├── .env.local.example                ← Copy to .env.local and fill in
├── vercel.json
├── tailwind.config.js
└── package.json
```

---

## Environment Variables — where each one goes

Cloudflare keeps **build variables** and **runtime variables** separately, and the
difference is not cosmetic:

- `NEXT_PUBLIC_*` values are **compiled into the bundles** by `next build`. They
  must be **build** variables. Setting them at runtime does nothing at all —
  there is no `process.env` lookup left in the built code to read.
- Everything else is read per request and must be a **runtime** variable.
- Two runtime secrets are *also* needed at build time, because their clients are
  constructed at module scope and `next build` loads those modules:
  `STRIPE_SECRET_KEY` and `RESEND_API_KEY`. Without them the build fails.

### Build variables

| Variable | Type | Value |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Variable | `https://<project>.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Variable | anon key (public by design — it ships in the browser bundle) |
| `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` | Variable | `pk_test_…` / `pk_live_…` |
| `NEXT_PUBLIC_SITE_URL` | Variable | `https://yourdomain.com` — optional; the app falls back to the request origin |
| `STRIPE_SECRET_KEY` | Secret | needed to build, not only to run |
| `RESEND_API_KEY` | Secret | needed to build, not only to run |

### Runtime variables

| Variable | Type | Value |
|---|---|---|
| `STRIPE_SECRET_KEY` | Secret | `sk_test_…` / `sk_live_…` |
| `STRIPE_WEBHOOK_SECRET` | Secret | `whsec_…` from the webhook endpoint **of the same mode** |
| `SUPABASE_SERVICE_ROLE_KEY` | Secret | service role JWT — the anon key cannot write `orders` |
| `RESEND_API_KEY` | Secret | `re_…` |
| `RESEND_FROM_EMAIL` | Variable | a sender on your verified domain. `onboarding@resend.dev` only delivers to the Resend account owner, so real customers get nothing |
| `LULU_CLIENT_KEY` | Variable | must come from the **same Lulu account** as the secret |
| `LULU_CLIENT_SECRET` | Secret | also the key Lulu signs status webhooks with |
| `LULU_API_URL` | Variable | `https://api.sandbox.lulu.com` while testing. **Defaults to production Lulu**, which rejects sandbox credentials with a 401 |
| `LULU_CONTACT_EMAIL` | Variable | where Lulu and the print-failure alert reach you |
| `LULU_DEFAULT_PHONE` | Variable | fallback phone for the carrier when Stripe collected none |

Optional runtime overrides, all with defaults in code: `LULU_POD_PACKAGE_ID`
(6x9 B&W paperback), `LULU_SHIPPING_LEVEL` (`MAIL`),
`LULU_PRODUCTION_DELAY_MINUTES` (120), `LULU_FILE_URL_TTL_SECONDS` (7 days).

`NEXT_PUBLIC_*` variables do **not** need runtime copies — they are already
compiled in. Lulu and Stripe credentials are per environment: sandbox/test
credentials and their webhook subscriptions do not carry over to production.

---

## Going Live

Everything below is test/sandbox until you change it. Work top to bottom — the
non-variable steps are the ones that fail silently.

### Values to change

**Build variables** (Cloudflare → Settings → Build):

| Variable | Change to |
|---|---|
| `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` | `pk_live_…` |
| `STRIPE_SECRET_KEY` | `sk_live_…` — needed at build as well as runtime |
| `NEXT_PUBLIC_SITE_URL` | `https://yourdomain.com` |

`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` and `RESEND_API_KEY`
stay as they are. Delete `RESEND_FROM_EMAIL`, `STRIPE_WEBHOOK_SECRET` and
`SUPABASE_SERVICE_ROLE_KEY` from the build variables — they are never read there.

**Runtime plain variables** (`wrangler.toml` `[vars]`, which replaces the
dashboard's plain variables on every deploy):

| Variable | Change to |
|---|---|
| `LULU_API_URL` | `https://api.lulu.com` |
| `LULU_CLIENT_KEY` | production Lulu account key |

**Runtime secrets** (dashboard):

| Secret | Change to |
|---|---|
| `STRIPE_SECRET_KEY` | `sk_live_…` |
| `STRIPE_WEBHOOK_SECRET` | signing secret of the **live-mode** webhook endpoint |
| `LULU_CLIENT_SECRET` | production Lulu account secret |

`SUPABASE_SERVICE_ROLE_KEY` and `RESEND_API_KEY` are unchanged. Remove any
`NEXT_PUBLIC_*` runtime copies — they are compiled in and never read at runtime.

### Steps that are not variables

1. **Stripe**: activate live payments, then create a **live-mode** webhook
   endpoint at `https://yourdomain.com/api/webhooks/stripe` for
   `checkout.session.completed` and take its signing secret. Endpoints are per
   mode; the test one never fires for live payments.
2. **Lulu**: production credentials are a different account from the sandbox.
   Then, and this is the step that silently stops everything:
   **put a credit card on file**. Without one every job sits at `UNPAID` and
   nothing is ever printed.
3. **Lulu webhook**: register the status subscription again on the production
   account — `npm run lulu:test -- --register-webhook https://yourdomain.com/api/webhooks/lulu`.
   Subscriptions do not carry over between environments.
4. **Clear test orders** from the `orders` table so the first real order is
   unambiguous.
5. **Turn on Workers observability/logs** in Cloudflare. Without it, a failing
   webhook or a rejected print job leaves no trace you can read.

### First live order

Buy one cheap book with a real card. `LULU_PRODUCTION_DELAY_MINUTES` (default
120) is how long Lulu waits before production, and a job can still be canceled
during that window — so you have a safety net. Watch it move `UNPAID` →
`PRODUCTION_DELAYED` → `IN_PRODUCTION` with
`npm run lulu:test -- --status <job id>`, and confirm the confirmation email
arrives with a working `/orders/…` link.

---

## Estimated Monthly Costs (at low volume)

| Service | Free Tier | Paid |
|---------|-----------|------|
| Cloudflare | Unlimited hobby projects | $20/mo (Pro, if needed) |
| Supabase | 500 MB DB, 1 GB storage | $25/mo (Pro) |
| Stripe | No monthly fee | 2.9% + $0.30 per transaction |
| Resend | 3,000 emails/mo free | $20/mo (50k emails) |
| Domain | — | ~$12/yr |

**At launch you'll pay essentially $0/mo** outside of Stripe's per-transaction fee.
