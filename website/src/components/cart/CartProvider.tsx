"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  cartCount,
  cartItemKey,
  clampQuantity,
  readStoredCart,
  writeStoredCart,
  CART_STORAGE_KEY,
  type CartItem,
  type CartItemKind,
} from "@/lib/cart";

type CartContextValue = {
  items: CartItem[];
  /** False until localStorage has been read — render counts only once true */
  ready: boolean;
  count: number;
  add: (kind: CartItemKind, id: string, quantity?: number) => void;
  setQuantity: (kind: CartItemKind, id: string, quantity: number) => void;
  remove: (kind: CartItemKind, id: string) => void;
  clear: () => void;
  has: (kind: CartItemKind, id: string) => boolean;
};

const CartContext = createContext<CartContextValue | null>(null);

export function CartProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<CartItem[]>([]);
  const [ready, setReady] = useState(false);

  // The server renders an empty cart, so read storage after mount to keep
  // hydration matching, then persist every change.
  useEffect(() => {
    setItems(readStoredCart());
    setReady(true);
  }, []);

  useEffect(() => {
    if (ready) writeStoredCart(items);
  }, [items, ready]);

  // A cart open in another tab is the same cart
  useEffect(() => {
    function onStorage(event: StorageEvent) {
      if (event.key === null || event.key === CART_STORAGE_KEY) setItems(readStoredCart());
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const add = useCallback((kind: CartItemKind, id: string, quantity = 1) => {
    setItems((current) => {
      const key = cartItemKey({ kind, id });
      const existing = current.find((item) => cartItemKey(item) === key);
      if (!existing) return [...current, { kind, id, quantity: clampQuantity(quantity) }];
      return current.map((item) =>
        cartItemKey(item) === key
          ? { ...item, quantity: clampQuantity(item.quantity + quantity) }
          : item
      );
    });
  }, []);

  const setQuantity = useCallback((kind: CartItemKind, id: string, quantity: number) => {
    const key = cartItemKey({ kind, id });
    setItems((current) =>
      current.map((item) =>
        cartItemKey(item) === key ? { ...item, quantity: clampQuantity(quantity) } : item
      )
    );
  }, []);

  const remove = useCallback((kind: CartItemKind, id: string) => {
    const key = cartItemKey({ kind, id });
    setItems((current) => current.filter((item) => cartItemKey(item) !== key));
  }, []);

  const clear = useCallback(() => setItems([]), []);

  const value = useMemo<CartContextValue>(
    () => ({
      items,
      ready,
      count: cartCount(items),
      add,
      setQuantity,
      remove,
      clear,
      has: (kind, id) => items.some((item) => cartItemKey(item) === cartItemKey({ kind, id })),
    }),
    [items, ready, add, setQuantity, remove, clear]
  );

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart(): CartContextValue {
  const context = useContext(CartContext);
  if (!context) throw new Error("useCart must be used inside a CartProvider");
  return context;
}
