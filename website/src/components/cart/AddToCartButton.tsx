"use client";

import { useState } from "react";
import Link from "next/link";
import { useCart } from "@/components/cart/CartProvider";
import type { CartItemKind } from "@/lib/cart";

export function AddToCartButton({
  kind,
  id,
  label = "Add to Cart",
  className = "btn-outline w-full",
}: {
  kind: CartItemKind;
  id: string;
  label?: string;
  className?: string;
}) {
  const { add, has } = useCart();
  const [justAdded, setJustAdded] = useState(false);

  function handleAdd() {
    add(kind, id);
    setJustAdded(true);
  }

  // Once it's in the cart, the useful next step is going there
  if (justAdded || has(kind, id)) {
    return (
      <div className={className.includes("w-full") ? "w-full" : ""}>
        <Link href="/cart" className={`${className} block text-center`}>
          In Cart — View Cart
        </Link>
      </div>
    );
  }

  return (
    <button type="button" onClick={handleAdd} className={className}>
      {label}
    </button>
  );
}
