/**
 * Where we ship. Kept apart from lib/shipping.ts so the country picker can
 * import it without pulling the Lulu client into the browser bundle.
 */

export const SHIPPING_COUNTRIES = {
  US: "United States",
  CA: "Canada",
  GB: "United Kingdom",
  AU: "Australia",
} as const;

export type ShippingCountry = keyof typeof SHIPPING_COUNTRIES;

export const DEFAULT_SHIPPING_COUNTRY: ShippingCountry = "US";

export function isShippingCountry(value: unknown): value is ShippingCountry {
  return typeof value === "string" && Object.hasOwn(SHIPPING_COUNTRIES, value);
}
