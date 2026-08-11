"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getSessionId } from "@/lib/session";
import { fetchCart, cartItemCount } from "@/lib/cart";

interface CartCountContextValue {
  count: number;
  setCount: (count: number) => void;
}

const CartCountContext = createContext<CartCountContextValue | null>(null);

export function CartCountProvider({ children }: { children: ReactNode }) {
  const [count, setCount] = useState(0);

  useEffect(() => {
    const sessionId = getSessionId();
    if (!sessionId) return;
    fetchCart(sessionId)
      .then((cart) => setCount(cartItemCount(cart)))
      .catch(() => {});
  }, []);

  return (
    <CartCountContext.Provider value={{ count, setCount }}>
      {children}
    </CartCountContext.Provider>
  );
}

export function useCartCount(): CartCountContextValue {
  const context = useContext(CartCountContext);
  if (!context) {
    throw new Error("useCartCount must be used within a CartCountProvider");
  }
  return context;
}
