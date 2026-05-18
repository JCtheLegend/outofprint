# Reprint Press — Setup Guide

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

## Step 5 — Connect Your Print API

Open `src/lib/print.ts`. The `createPrintJob` function currently makes a generic REST call. Adapt it to match your print provider's actual API:

- **Lulu Direct**: [developers.lulu.com](https://developers.lulu.com)
- **Printful**: [developers.printful.com](https://developers.printful.com)
- **Custom/in-house**: replace the fetch call with whatever your pipeline expects

Set `PRINT_API_KEY` and `PRINT_API_URL` in `.env.local` accordingly.

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

---

## Step 7 — Deploy to Vercel

### 7a — Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
# Create a repo at github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/reprint-press.git
git push -u origin main
```

### 7c — Update Your Stripe Webhook

After deploying:
1. Go back to Stripe → **Developers → Webhooks**
2. Update the endpoint URL to `https://reprint-press.vercel.app/api/webhooks/stripe`
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
│   │   │   └── [id]/
│   │   │       ├── page.tsx          ← Individual book page
│   │   │       ├── CheckoutButton.tsx
│   │   │       └── success/page.tsx  ← Post-purchase page
│   │   ├── submit/
│   │   │   ├── page.tsx              ← Submission page
│   │   │   └── SubmissionForm.tsx    ← Form (client)
│   │   └── api/
│   │       ├── checkout/route.ts     ← Creates Stripe session
│   │       ├── submissions/route.ts  ← Saves submission + uploads file
│   │       └── webhooks/stripe/route.ts  ← Fires print job after payment
│   ├── components/
│   │   ├── layout/Nav.tsx
│   │   └── ui/BookCard.tsx
│   └── lib/
│       ├── supabase.ts               ← DB client + types
│       ├── stripe.ts                 ← Stripe client
│       ├── print.ts                  ← Print API integration
│       └── email.ts                  ← Resend email helpers
├── supabase-schema.sql               ← Run once in Supabase SQL editor
├── .env.local.example                ← Copy to .env.local and fill in
├── vercel.json
├── tailwind.config.js
└── package.json
```

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
