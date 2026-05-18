import { createClient } from "@supabase/supabase-js";

export type Book = {
  id: string;
  title: string;
  author: string;
  year: number;
  genre: string;
  description: string;
  price_cents: number;
  cover_url: string | null;
  pdf_url: string;
  featured: boolean;
  created_at: string;
};

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
