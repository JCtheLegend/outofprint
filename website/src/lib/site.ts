import type { NextRequest } from "next/server";

/**
 * Absolute base URL for links we hand to Stripe, Lulu or a customer's inbox.
 *
 * NEXT_PUBLIC_* values are inlined at build time, so a deploy built without
 * NEXT_PUBLIC_SITE_URL would otherwise produce "undefined/orders/...". The
 * request always knows the real origin, so the configured value is used only
 * when it is a usable absolute URL.
 */
export function resolveSiteUrl(req: NextRequest): string {
  const configured = process.env.NEXT_PUBLIC_SITE_URL;
  if (configured && /^https?:\/\//i.test(configured)) {
    return configured.replace(/\/+$/, "");
  }
  return new URL(req.url).origin;
}

/** Where a customer can follow their order. */
export function orderStatusUrl(siteUrl: string, orderId: string): string {
  return `${siteUrl}/orders/${orderId}`;
}
