-- ============================================================
-- Out Of Print Press — Supabase Schema
-- Run this in: Supabase Dashboard > SQL Editor > New Query
-- ============================================================

-- Books table
create table if not exists books (
  id            uuid primary key default gen_random_uuid(),
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
  stripe_session_id text not null unique,
  customer_email    text not null,
  customer_name     text not null,
  shipping_address  jsonb not null default '{}',
  status            text not null default 'pending'
                    check (status in ('pending', 'paid', 'printing', 'shipped', 'delivered')),
  print_job_id      text,
  created_at        timestamptz not null default now()
);

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
