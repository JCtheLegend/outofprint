"use client";

import { useEffect, useState } from "react";
import {
  DEFAULT_SHIPPING_COUNTRY,
  POSTCODE_LABELS,
  REGION_LABELS,
  SHIPPING_COUNTRIES,
  isCompleteDestination,
  isShippingCountry,
  postcodeNoun,
  regionsFor,
  type ShippingCountry,
  type ShippingDestination,
} from "@/lib/shipping-countries";

const STORAGE_KEY = "oop.shipTo.v2";
/** Held only the country, before tax needed a postcode */
const LEGACY_STORAGE_KEY = "oop.shipTo.v1";

/** What the customer has filled in so far — possibly not yet complete. */
export type ShipToDraft = { country: ShippingCountry; region: string; postcode: string };

const EMPTY: ShipToDraft = { country: DEFAULT_SHIPPING_COUNTRY, region: "", postcode: "" };

function readStored(): ShipToDraft {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<ShipToDraft>;
      if (isShippingCountry(parsed.country)) {
        return {
          country: parsed.country,
          region: typeof parsed.region === "string" ? parsed.region : "",
          postcode: typeof parsed.postcode === "string" ? parsed.postcode : "",
        };
      }
    }
    const legacy = window.localStorage.getItem(LEGACY_STORAGE_KEY);
    if (isShippingCountry(legacy)) return { ...EMPTY, country: legacy };
  } catch {
    // Blocked storage or bad JSON — start empty
  }
  return EMPTY;
}

/**
 * Where the order is going: checkout quotes shipping and Lulu's sales tax for
 * it. Remembered per browser so a reader fills it in once, not on every book.
 */
export function useShipTo(): [ShipToDraft, (draft: ShipToDraft) => void] {
  const [draft, setDraft] = useState<ShipToDraft>(EMPTY);

  // Read after mount, like the cart, so server and client first render agree
  useEffect(() => {
    setDraft(readStored());
  }, []);

  function update(next: ShipToDraft) {
    setDraft(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Remembered for this page only
    }
  }

  return [draft, update];
}

/** The destination to send to checkout, or a sentence saying what's missing. */
export function shipToDestination(
  draft: ShipToDraft
): { destination: ShippingDestination } | { missing: string } {
  const destination = {
    country: draft.country,
    region: draft.region || undefined,
    postcode: draft.postcode.trim(),
  };
  if (isCompleteDestination(destination)) return { destination };

  const needs = [
    regionsFor(draft.country) && !draft.region ? REGION_LABELS[draft.country]?.toLowerCase() : null,
    !draft.postcode.trim() ? postcodeNoun(draft.country) : null,
  ].filter(Boolean);
  return {
    missing: `Enter your ${needs.join(" and ")} so we can work out shipping and tax.`,
  };
}

const fieldClass =
  "border border-border bg-white px-2 py-1.5 text-sm text-ink outline-none focus:border-rust min-w-0";

export function ShipToFields({
  value,
  onChange,
}: {
  value: ShipToDraft;
  onChange: (draft: ShipToDraft) => void;
}) {
  const regions = regionsFor(value.country);

  return (
    <fieldset className="mb-3">
      <legend className="text-xs text-muted mb-1.5">
        Ship to <span className="text-muted/80">— for shipping and sales tax</span>
      </legend>
      <div className={`grid gap-2 ${regions ? "grid-cols-[1fr_1fr_6.5rem]" : "grid-cols-[1fr_6.5rem]"}`}>
        <select
          aria-label="Country"
          value={value.country}
          // A new country's states and postcodes don't carry over
          onChange={(e) =>
            onChange({ country: e.target.value as ShippingCountry, region: "", postcode: "" })
          }
          className={fieldClass}
        >
          {Object.entries(SHIPPING_COUNTRIES).map(([code, name]) => (
            <option key={code} value={code}>{name}</option>
          ))}
        </select>

        {regions && (
          <select
            aria-label={REGION_LABELS[value.country]}
            value={value.region}
            onChange={(e) => onChange({ ...value, region: e.target.value })}
            className={fieldClass}
          >
            <option value="">{REGION_LABELS[value.country]}…</option>
            {Object.entries(regions).map(([code, name]) => (
              <option key={code} value={code}>{name}</option>
            ))}
          </select>
        )}

        <input
          type="text"
          aria-label={POSTCODE_LABELS[value.country]}
          placeholder={POSTCODE_LABELS[value.country]}
          value={value.postcode}
          onChange={(e) => onChange({ ...value, postcode: e.target.value })}
          autoComplete="postal-code"
          className={`${fieldClass} placeholder:text-muted/60`}
        />
      </div>
    </fieldset>
  );
}
