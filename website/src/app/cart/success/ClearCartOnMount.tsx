"use client";

import { useEffect } from "react";
import { useCart } from "@/components/cart/CartProvider";

/** The order is paid for, so the cart that produced it is done. */
export function ClearCartOnMount() {
  const { clear, ready } = useCart();

  useEffect(() => {
    if (ready) clear();
  }, [ready, clear]);

  return null;
}
