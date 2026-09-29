"use client";

import { useEffect, useState } from "react";
import {
  DEFAULT_SHIPPING_COUNTRY,
  SHIPPING_COUNTRIES,
  isShippingCountry,
  type ShippingCountry,
} from "@/lib/shipping-countries";

const STORAGE_KEY = "oop.shipTo.v1";

/**
 * The country checkout quotes shipping for. Remembered per browser so a
 * reader abroad picks it once, not on every book.
 */
export function useShipTo(): [ShippingCountry, (country: ShippingCountry) => void] {
  const [country, setCountry] = useState<ShippingCountry>(DEFAULT_SHIPPING_COUNTRY);

  // Read after mount, like the cart, so server and client first render agree
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (isShippingCountry(stored)) setCountry(stored);
    } catch {
      // Blocked storage — the default stands
    }
  }, []);

  function choose(next: ShippingCountry) {
    setCountry(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Remembered for this page only
    }
  }

  return [country, choose];
}

export function ShipToSelect({
  value,
  onChange,
}: {
  value: ShippingCountry;
  onChange: (country: ShippingCountry) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 text-xs text-muted mb-3">
      Ship to
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as ShippingCountry)}
        className="border border-border bg-white px-2 py-1 text-sm text-ink outline-none focus:border-rust"
      >
        {Object.entries(SHIPPING_COUNTRIES).map(([code, name]) => (
          <option key={code} value={code}>{name}</option>
        ))}
      </select>
    </label>
  );
}
