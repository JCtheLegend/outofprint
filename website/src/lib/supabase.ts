import { createClient } from "@supabase/supabase-js";

export type Book = {
  id: string;
  slug: string | null;
  title: string;
  author: string;
  year: number;
  genre: string;
  description: string;
  price_cents: number;
  cover_url: string | null;
  pdf_url: string;
  // Print-ready wraparound cover PDF and Lulu product SKU — see lib/print.ts
  cover_pdf_url: string | null;
  pod_package_id: string | null;
  featured: boolean;
  created_at: string;
  // Set membership — null for standalone books
  set_id: string | null;
  volume_number: number | null;
  volume_label: string | null;
};

// A multi-volume work. Its volumes live in `books` and point back via set_id.
export type BookSet = {
  id: string;
  slug: string;
  title: string;
  author: string;
  description: string | null;
  genre: string | null;
  cover_url: string | null;
  // Bundle price for every volume at once; null means "sum of the volumes"
  price_cents: number | null;
  featured: boolean;
  created_at: string;
};

// A set together with its volumes, ordered by volume number
export type BookSetWithVolumes = BookSet & { volumes: Book[] };

export type Submission = {
  id: string;
  title: string;
  author: string;
  year: string | null;
  genre: string | null;
  reason: string | null;
  source_file_url: string | null;
  submitter_name: string;
  submitter_email: string;
  status: "pending" | "reviewing" | "approved" | "declined";
  created_at: string;
};

export type Order = {
  id: string;
  book_id: string;
  set_id: string | null;
  stripe_session_id: string;
  customer_email: string;
  customer_name: string;
  shipping_address: Record<string, string>;
  status: "pending" | "paid" | "printing" | "shipped" | "delivered";
  print_job_id: string | null;
  created_at: string;
};

// Browser client (uses anon key — safe to expose)
export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);

// Server-only admin client (uses service role key — never expose to browser)
export const supabaseAdmin = () =>
  createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { auth: { autoRefreshToken: false, persistSession: false } }
  );
