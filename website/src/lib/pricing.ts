/**
 * Wholesale pricing
 *
 * A book's retail price is Lulu's print cost plus a flat margin, both worked
 * out by the uploader (book-creator/scripts/lulu_pricing.py) and stored on the
 * row. A wholesale promo code drops the margin, charging `print_cost_cents`
 * alone — for us to buy our own books at cost.
 *
 * Codes live in WHOLESALE_PROMO_CODES (comma-separated, server-only), so one
 * can be given to each developer and revoked on its own.
 */

function wholesaleCodes(): string[] {
  return (process.env.WHOLESALE_PROMO_CODES ?? "")
    .split(",")
    .map((code) => code.trim().toUpperCase())
    .filter(Boolean);
}

/** Compare without exiting early on the first differing character. */
function sameCode(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let mismatch = 0;
  for (let i = 0; i < a.length; i++) mismatch |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return mismatch === 0;
}

export function isWholesaleCode(code: string): boolean {
  const given = code.trim().toUpperCase();
  if (!given) return false;
  return wholesaleCodes().reduce((found, valid) => sameCode(given, valid) || found, false);
}

