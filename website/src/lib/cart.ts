/**
 * Shopping cart
 *
 * The cart is per-browser state, not server state: there are no accounts, so it
 * lives in localStorage and holds only what a book *is*, never what it costs.
 * Prices are resolved server-side at checkout from the `books` / `book_sets`
 * rows, so a stale cart can never buy a book at yesterday's price.
 */

import { DEFAULT_FORMAT, isBookFormat, type BookFormat } from "@/lib/formats";

export type CartItemKind = "book" | "set";

export type CartItem = {
  kind: CartItemKind;
  /** books.id or book_sets.id */
  id: string;
  /** A set is bought in one format across every volume */
  format: BookFormat;
  quantity: number;
};

/** What identifies a line in the cart: the same book in two formats is two lines. */
export type CartItemRef = Pick<CartItem, "kind" | "id" | "format">;

export const CART_STORAGE_KEY = "oop.cart.v1";
export const MAX_QUANTITY = 20;

export function cartItemKey(item: CartItemRef): string {
  return `${item.kind}:${item.id}:${item.format}`;
}

export function clampQuantity(quantity: number): number {
  if (!Number.isFinite(quantity)) return 1;
  return Math.min(MAX_QUANTITY, Math.max(1, Math.round(quantity)));
}

/** Drop anything that isn't a usable entry — the cart outlives deploys. */
export function normalizeCart(value: unknown): CartItem[] {
  if (!Array.isArray(value)) return [];

  const seen = new Set<string>();
  const items: CartItem[] = [];

  for (const raw of value) {
    if (!raw || typeof raw !== "object") continue;
    const { kind, id, quantity, format: rawFormat } = raw as Partial<CartItem>;
    if ((kind !== "book" && kind !== "set") || typeof id !== "string" || !id) continue;
    // Carts saved before hardcovers existed hold paperbacks
    const format = isBookFormat(rawFormat) ? rawFormat : DEFAULT_FORMAT;

    const key = cartItemKey({ kind, id, format });
    if (seen.has(key)) continue;
    seen.add(key);

    items.push({ kind, id, format, quantity: clampQuantity(Number(quantity ?? 1)) });
  }

  return items;
}

export function readStoredCart(): CartItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(CART_STORAGE_KEY);
    return raw ? normalizeCart(JSON.parse(raw)) : [];
  } catch {
    // Private browsing, blocked storage, corrupted JSON — an empty cart is
    // better than a broken page.
    return [];
  }
}

export function writeStoredCart(items: CartItem[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(items));
  } catch {
    // Nothing to do — the cart simply won't survive a reload.
  }
}

export function cartCount(items: CartItem[]): number {
  return items.reduce((total, item) => total + item.quantity, 0);
}
