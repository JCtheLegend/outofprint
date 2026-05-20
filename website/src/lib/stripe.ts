import Stripe from "stripe";

// Server-only — never import this in client components
export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: "2025-02-24.acacia",
});

export { formatPrice } from "@/lib/format";
