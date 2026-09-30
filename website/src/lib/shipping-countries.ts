/**
 * Where we ship, and how a destination is described before checkout.
 *
 * Lulu charges us sales tax at the destination's local rate — anywhere from
 * nothing (Oregon, the UK) to over 10% (Seattle) — on the books and, in most
 * places, on shipping. To pass that on exactly, checkout quotes Lulu for the
 * customer's own postcode, and Lulu will only quote a postcode together with
 * the state or province it belongs to. The UK has no regions and charges no
 * tax on books.
 *
 * Kept apart from lib/shipping.ts so the ship-to fields can import it without
 * pulling the Lulu client into the browser bundle.
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

/** State or province codes as Lulu (and Stripe) spell them. */
export const SHIPPING_REGIONS: Partial<Record<ShippingCountry, Record<string, string>>> = {
  US: {
    AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California",
    CO: "Colorado", CT: "Connecticut", DE: "Delaware", DC: "District of Columbia",
    FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho", IL: "Illinois",
    IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky", LA: "Louisiana",
    ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota",
    MS: "Mississippi", MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada",
    NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
    NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon",
    PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina", SD: "South Dakota",
    TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia",
    WA: "Washington", WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming",
  },
  CA: {
    AB: "Alberta", BC: "British Columbia", MB: "Manitoba", NB: "New Brunswick",
    NL: "Newfoundland and Labrador", NS: "Nova Scotia", NT: "Northwest Territories",
    NU: "Nunavut", ON: "Ontario", PE: "Prince Edward Island", QC: "Quebec",
    SK: "Saskatchewan", YT: "Yukon",
  },
  AU: {
    ACT: "Australian Capital Territory", NSW: "New South Wales", NT: "Northern Territory",
    QLD: "Queensland", SA: "South Australia", TAS: "Tasmania", VIC: "Victoria",
    WA: "Western Australia",
  },
};

export const POSTCODE_LABELS: Record<ShippingCountry, string> = {
  US: "ZIP code",
  CA: "Postal code",
  GB: "Postcode",
  AU: "Postcode",
};

/** A postcode label mid-sentence: "ZIP code" keeps its capitals. */
export function postcodeNoun(country: ShippingCountry): string {
  const label = POSTCODE_LABELS[country];
  return label.startsWith("ZIP") ? label : label.toLowerCase();
}

export const REGION_LABELS: Partial<Record<ShippingCountry, string>> = {
  US: "State",
  CA: "Province",
  AU: "State",
};

/** Where an order is going, as far as tax and shipping care. */
export type ShippingDestination = {
  country: ShippingCountry;
  /** State or province code; absent for the UK */
  region?: string;
  postcode: string;
};

export function regionsFor(country: ShippingCountry): Record<string, string> | undefined {
  return SHIPPING_REGIONS[country];
}

/** Whether a destination is complete enough for Lulu to quote tax for. */
export function isCompleteDestination(value: unknown): value is ShippingDestination {
  if (!value || typeof value !== "object") return false;
  const { country, region, postcode } = value as Partial<ShippingDestination>;
  if (!isShippingCountry(country)) return false;
  if (typeof postcode !== "string" || !postcode.trim()) return false;
  const regions = regionsFor(country);
  if (!regions) return true;
  return typeof region === "string" && Object.hasOwn(regions, region);
}

/** "WA 98101, United States" — for the tax line and error messages. */
export function describeDestination(destination: ShippingDestination): string {
  const place = [destination.region, destination.postcode.trim().toUpperCase()]
    .filter(Boolean)
    .join(" ");
  return `${place}, ${SHIPPING_COUNTRIES[destination.country]}`;
}
