-- ============================================================
-- Out Of Print Press — Supabase Schema
-- Run this in: Supabase Dashboard > SQL Editor > New Query
-- ============================================================

-- Books table
create table if not exists books (
  id            uuid primary key default gen_random_uuid(),
  slug          text unique,
  title         text not null,
  author        text not null,
  year          int,
  genre         text,
  description   text,
  price_cents   int not null,
  cover_url     text,
  pdf_url       text not null,
  featured      boolean not null default false,
  created_at    timestamptz not null default now()
);

-- If this table already exists from before the GitHub upload pipeline was
-- added, run this to add the new column (safe to re-run):
-- alter table books add column if not exists slug text unique;

-- Submissions table
create table if not exists submissions (
  id                uuid primary key default gen_random_uuid(),
  title             text not null,
  author            text not null,
  year              text,
  genre             text,
  reason            text,
  source_file_url   text,
  submitter_name    text not null,
  submitter_email   text not null,
  status            text not null default 'pending'
                    check (status in ('pending', 'reviewing', 'approved', 'declined')),
  created_at        timestamptz not null default now()
);

-- Orders table
create table if not exists orders (
  id                uuid primary key default gen_random_uuid(),
  book_id           uuid not null references books(id),
  stripe_session_id text not null,
  customer_email    text not null,
  customer_name     text not null,
  shipping_address  jsonb not null default '{}',
  status            text not null default 'pending'
                    check (status in ('pending', 'paid', 'printing', 'shipped', 'delivered')),
  print_job_id      text,
  created_at        timestamptz not null default now()
);

-- ============================================================
-- Multi-volume sets
-- ============================================================

-- A set groups the volumes of one multi-volume work (e.g. Froude's
-- "History of England", Volumes I–XII). Volumes stay in the books table —
-- each is still individually printable and purchasable — and point back
-- here via books.set_id.
create table if not exists book_sets (
  id            uuid primary key default gen_random_uuid(),
  slug          text unique not null,
  title         text not null,
  author        text not null,
  description   text,
  genre         text,
  cover_url     text,
  -- Bundle price for buying every volume at once. Leave null to charge the
  -- sum of the volumes' individual prices (no discount).
  price_cents   int,
  featured      boolean not null default false,
  created_at    timestamptz not null default now()
);

alter table books add column if not exists set_id uuid references book_sets(id);
alter table books add column if not exists volume_number int;
alter table books add column if not exists volume_label text;

create index if not exists books_set_id_idx on books (set_id, volume_number);
create index if not exists book_sets_featured_idx on book_sets (featured);

-- Sets are publicly readable; only the service role writes them
alter table book_sets enable row level security;
drop policy if exists "book_sets_public_read" on book_sets;
create policy "book_sets_public_read" on book_sets for select using (true);

-- One checkout can now cover several volumes, so an order row is per book
-- and a session may produce several of them. Replace the old
-- unique(stripe_session_id) constraint with unique(stripe_session_id, book_id).
alter table orders add column if not exists set_id uuid references book_sets(id);

alter table orders drop constraint if exists orders_stripe_session_id_key;
create unique index if not exists orders_session_book_idx
  on orders (stripe_session_id, book_id);

-- Indexes
create index if not exists books_featured_idx on books (featured);
create index if not exists orders_book_id_idx on orders (book_id);
create index if not exists submissions_status_idx on submissions (status);

-- Row Level Security
-- Books are publicly readable; only service role can write
alter table books enable row level security;
create policy "books_public_read" on books for select using (true);

-- Submissions: anyone can insert; only service role reads
alter table submissions enable row level security;
create policy "submissions_public_insert" on submissions for insert with check (true);

-- Orders: no public access (service role only via supabaseAdmin)
alter table orders enable row level security;

-- Storage buckets (run separately or create in the Supabase UI):
-- 1. "source-files"  — public, for submission uploads
-- 2. "book-covers"   — public, for cover images
-- 3. "book-pdfs"     — PRIVATE, for print-ready PDFs (accessed only server-side)

-- Sample book (remove in production)
insert into books (title, author, year, genre, description, price_cents, pdf_url, featured)
values (
  'The Marsh Chronicles',
  'E.L. Hartwell',
  1891,
  'Fiction',
  'A sweeping tale of family secrets set among the tidal marshes of coastal England. Restored from a single surviving copy held at the British Library.',
  2400,
  'https://your-project.supabase.co/storage/v1/object/public/book-pdfs/marsh-chronicles.pdf',
  true
);
