"use client";

import { useState } from "react";
import { AddToCartButton } from "@/components/cart/AddToCartButton";
import { FormatPicker } from "@/components/cart/FormatPicker";
import { DEFAULT_FORMAT, type BookFormat } from "@/lib/formats";
import { CheckoutButton, type SetOption } from "./CheckoutButton";

/** Format choice, then add to cart or buy now in that format. */
export function BookPurchasePanel({
  bookId,
  prices,
  setOption,
}: {
  bookId: string;
  prices: Partial<Record<BookFormat, number>>;
  setOption?: SetOption;
}) {
  const [format, setFormat] = useState<BookFormat>(DEFAULT_FORMAT);

  return (
    <div>
      <FormatPicker prices={prices} value={format} onChange={setFormat} />
      <div className="mb-3">
        {/* Keyed on format so switching resets "In Cart" to the new choice */}
        <AddToCartButton key={format} kind="book" id={bookId} format={format} className="btn-primary w-full" />
      </div>
      <CheckoutButton bookId={bookId} format={format} setOption={setOption} />
    </div>
  );
}
