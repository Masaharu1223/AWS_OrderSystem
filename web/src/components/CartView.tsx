"use client";

import { useEffect, useState } from "react";
import { getSessionId } from "@/lib/session";
import { fetchCart, updateQuantity, deleteItem, cartItemCount, type Cart } from "@/lib/cart";
import { useCartCount } from "@/components/CartCountProvider";

function formatPrice(yen: number): string {
  return `¥${yen.toLocaleString("ja-JP")}`;
}

const EMPTY_CART: Cart = { sessionId: "", items: [], subtotal: 0 };

export function CartView() {
  const [cart, setCart] = useState<Cart | null>(null);
  const [error, setError] = useState(false);
  const [pendingItemId, setPendingItemId] = useState<string | null>(null);
  const { setCount } = useCartCount();

  useEffect(() => {
    const sessionId = getSessionId();
    // まだ一度もカートを操作していない訪問者はAPIを叩かず空カート扱いにする。
    const cartPromise = sessionId ? fetchCart(sessionId) : Promise.resolve(EMPTY_CART);
    cartPromise
      .then((cart) => {
        setCart(cart);
        setCount(cartItemCount(cart));
      })
      .catch(() => setError(true));
  }, [setCount]);

  async function runMutation(itemId: string, mutate: (sessionId: string) => Promise<Cart>) {
    const sessionId = getSessionId();
    if (!sessionId) return;
    setPendingItemId(itemId);
    try {
      const updated = await mutate(sessionId);
      setCart(updated);
      setCount(cartItemCount(updated));
    } catch {
      setError(true);
    } finally {
      setPendingItemId(null);
    }
  }

  if (error) {
    return (
      <p className="text-red-600">カートの取得に失敗しました。時間をおいて再度お試しください。</p>
    );
  }

  if (!cart) {
    return <p className="text-zinc-600 dark:text-zinc-400">読み込み中...</p>;
  }

  if (cart.items.length === 0) {
    return <p className="text-zinc-600 dark:text-zinc-400">カートは空です。</p>;
  }

  return (
    <>
      <ul>
        {cart.items.map((item) => {
          const pending = pendingItemId === item.itemId;
          return (
            <li
              key={item.itemId}
              className="flex flex-col gap-2 border-b border-black/10 py-4 dark:border-white/10"
            >
              <div className="flex items-baseline justify-between gap-4">
                <span className="font-medium">{item.name}</span>
                <span>{formatPrice(item.lineTotal)}</span>
              </div>
              <span className="text-sm text-zinc-600 dark:text-zinc-400">
                {item.variant.temperature === "hot" ? "ホット" : "アイス"} / {item.variant.size}
                （{formatPrice(item.unitPrice)}）
              </span>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  disabled={pending || item.quantity <= 1}
                  onClick={() =>
                    runMutation(item.itemId, (sessionId) =>
                      updateQuantity(sessionId, item.itemId, item.quantity - 1),
                    )
                  }
                  className="h-8 w-8 rounded border border-black/20 disabled:opacity-40 dark:border-white/20"
                >
                  −
                </button>
                <span className="w-6 text-center tabular-nums">{item.quantity}</span>
                <button
                  type="button"
                  disabled={pending || item.quantity >= 10}
                  onClick={() =>
                    runMutation(item.itemId, (sessionId) =>
                      updateQuantity(sessionId, item.itemId, item.quantity + 1),
                    )
                  }
                  className="h-8 w-8 rounded border border-black/20 disabled:opacity-40 dark:border-white/20"
                >
                  +
                </button>
                <button
                  type="button"
                  disabled={pending}
                  onClick={() =>
                    runMutation(item.itemId, (sessionId) => deleteItem(sessionId, item.itemId))
                  }
                  className="ml-auto text-sm text-red-600 disabled:opacity-40"
                >
                  削除
                </button>
              </div>
            </li>
          );
        })}
      </ul>
      <div className="mt-6 flex items-baseline justify-between text-lg font-semibold">
        <span>小計</span>
        <span>{formatPrice(cart.subtotal)}</span>
      </div>
    </>
  );
}
