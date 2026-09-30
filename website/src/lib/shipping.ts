/**
 * Shipping and sales tax
 *
 * Customers pay what Lulu charges us to deliver an order: its shipping cost
 * for the whole cart, its per-order fulfilment fee, and the sales tax it adds
 * on top of the books, shipping and fee. That tax is set by the destination's
 * local rate, so it is quoted for the customer's own postcode (see
 * lib/shipping-countries.ts) and charged as its own line at checkout.
 *
 * Stripe's hosted Checkout cannot re-price anything once an address is typed
 * in, so the destination is chosen before checkout and Checkout only accepts
 * addresses in that country.
 */

import { LuluApiError, calculateLuluCost, type LuluShippingAddress } from "@/lib/lulu";
import { podPackageIdFor, shippingLevel } from "@/lib/print";
import { formatPodPackageId, type BookFormat } from "@/lib/formats";
import type { Book } from "@/lib/supabase";
import {
  postcodeNoun,
  type ShippingCountry,
  type ShippingDestination,
} from "@/lib/shipping-countries";

/**
 * When a request names only a country (a page cached from before postcodes
 * were asked for), quote to the national library — right for shipping, and
 * the nearest thing to a typical tax rate.
 */
const FALLBACK_ADDRESSES: Record<ShippingCountry, Omit<LuluShippingAddress, "email">> = {
  US: { name: "Quote", street1: "101 Independence Ave SE", city: "Washington", state_code: "DC", country_code: "US", postcode: "20540", phone_number: "2025550100" },
  CA: { name: "Quote", street1: "395 Wellington St", city: "Ottawa", state_code: "ON", country_code: "CA", postcode: "K1A 0N4", phone_number: "2025550100" },
  GB: { name: "Quote", street1: "96 Euston Road", city: "London", country_code: "GB", postcode: "NW1 2DB", phone_number: "2025550100" },
  AU: { name: "Quote", street1: "Parkes Place", city: "Canberra", state_code: "ACT", country_code: "AU", postcode: "2600", phone_number: "2025550100" },
};

/**
 * Lulu taxes by postcode and state and ignores the street; it still requires
 * a street and city, so both are placeholders.
 */
function quoteAddress(destination: ShippingDestination): Omit<LuluShippingAddress, "email"> {
  return {
    name: "Quote",
    street1: "1 Main St",
    city: "-",
    state_code: destination.region,
    country_code: destination.country,
    postcode: destination.postcode.trim().toUpperCase(),
    phone_number: "2025550100",
  };
}

/** "7.69" → 769, rounding any fraction of a cent up. */
function toCents(amount: string): number {
  return Math.ceil(Math.round(Number(amount) * 10000) / 100);
}

export type OrderCharges = {
  /** Shipping plus Lulu's fulfilment fee, before tax */
  shippingCents: number;
  /** Lulu's sales tax on the books, shipping and fee together */
  taxCents: number;
};

export type OrderChargesQuote =
  | ({ ok: true } & OrderCharges)
  /** A book with no page count, which Lulu cannot quote */
  | { ok: false; unpriced: string }
  /** Lulu rejected the destination — almost always a postcode in the wrong state */
  | { ok: false; invalidDestination: string };

/**
 * What Lulu charges to ship these books to `destination` as one print job,
 * and the tax it adds, in US cents.
 */
export async function quoteOrderCharges(
  books: Array<{ book: Book; format: BookFormat; quantity: number }>,
  destination: ShippingDestination | ShippingCountry
): Promise<OrderChargesQuote> {
  const unpriced = books.find(({ book }) => !book.page_count);
  if (unpriced) return { ok: false, unpriced: unpriced.book.title };

  const address =
    typeof destination === "string" ? FALLBACK_ADDRESSES[destination] : quoteAddress(destination);

  let quote;
  try {
    quote = await calculateLuluCost({
      // A hardcover weighs more than a paperback, so the SKU matters to shipping
      line_items: books.map(({ book, format, quantity }) => ({
        page_count: book.page_count!,
        pod_package_id: podPackageIdFor(formatPodPackageId(book, format)),
        quantity,
      })),
      shipping_address: address,
      shipping_option: shippingLevel(),
    });
  } catch (err) {
    if (err instanceof LuluApiError && err.status === 400 && typeof destination !== "string") {
      return {
        ok: false,
        invalidDestination: `That ${postcodeNoun(destination.country)} doesn't match the ${
          destination.region ? "state or province" : "country"
        } you chose — please check it.`,
      };
    }
    throw err;
  }

  if (quote.currency !== "USD") {
    throw new Error(`Lulu quoted in ${quote.currency}, expected USD`);
  }

  return {
    ok: true,
    shippingCents:
      toCents(quote.shipping_cost.total_cost_excl_tax) +
      toCents(quote.fulfillment_cost.total_cost_excl_tax),
    taxCents: toCents(quote.total_tax),
  };
}
