/**
 * Shipping
 *
 * Customers pay what Lulu charges us to ship an order: its shipping cost for
 * the whole cart plus Lulu's per-order fulfilment fee, both before tax. The
 * quote depends on the destination, and Stripe's hosted Checkout cannot
 * re-price shipping once an address is typed in — so the customer picks the
 * country before checkout, we quote against it, and Checkout only accepts
 * addresses in that country.
 */

import { calculateLuluCost, type LuluShippingAddress } from "@/lib/lulu";
import { podPackageIdFor, shippingLevel } from "@/lib/print";
import type { Book } from "@/lib/supabase";
import type { ShippingCountry } from "@/lib/shipping-countries";

/**
 * Lulu needs a full address to quote. Where in the country barely moves the
 * price of standard mail, so each country is quoted to its national library.
 */
const QUOTE_ADDRESSES: Record<ShippingCountry, Omit<LuluShippingAddress, "email">> = {
  US: { name: "Quote", street1: "101 Independence Ave SE", city: "Washington", state_code: "DC", country_code: "US", postcode: "20540", phone_number: "2025550100" },
  CA: { name: "Quote", street1: "395 Wellington St", city: "Ottawa", state_code: "ON", country_code: "CA", postcode: "K1A 0N4", phone_number: "2025550100" },
  GB: { name: "Quote", street1: "96 Euston Road", city: "London", country_code: "GB", postcode: "NW1 2DB", phone_number: "2025550100" },
  AU: { name: "Quote", street1: "Parkes Place", city: "Canberra", state_code: "ACT", country_code: "AU", postcode: "2600", phone_number: "2025550100" },
};

/** "7.69" → 769, rounding any fraction of a cent up. */
function toCents(amount: string): number {
  return Math.ceil(Math.round(Number(amount) * 10000) / 100);
}

/**
 * What Lulu charges to ship these books to `country` as one print job, in
 * US cents. Returns the title of a book with no page count on record instead,
 * since Lulu cannot quote a book without one.
 */
export async function quoteShippingCents(
  books: Array<{ book: Book; quantity: number }>,
  country: ShippingCountry
): Promise<{ cents: number } | { unpriced: string }> {
  const unpriced = books.find(({ book }) => !book.page_count);
  if (unpriced) return { unpriced: unpriced.book.title };

  const quote = await calculateLuluCost({
    line_items: books.map(({ book, quantity }) => ({
      page_count: book.page_count!,
      pod_package_id: podPackageIdFor(book.pod_package_id),
      quantity,
    })),
    shipping_address: QUOTE_ADDRESSES[country],
    shipping_option: shippingLevel(),
  });

  if (quote.currency !== "USD") {
    throw new Error(`Lulu quoted shipping in ${quote.currency}, expected USD`);
  }

  return {
    cents:
      toCents(quote.shipping_cost.total_cost_excl_tax) +
      toCents(quote.fulfillment_cost.total_cost_excl_tax),
  };
}
