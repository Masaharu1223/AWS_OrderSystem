"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getSessionId } from "@/lib/session";
import { fetchCart, updateQuantity, deleteItem, cartItemCount, type Cart } from "@/lib/cart";
import { useCartCount } from "@/components/CartCountProvider";
import { createOrder, STORE_ID } from "@/lib/orders";
import { ApiError } from "@/lib/api";

function formatPrice(yen: number): string {
  return `¥${yen.toLocaleString("ja-JP")}`;
}

const EMPTY_CART: Cart = { sessionId: "", items: [], subtotal: 0 };

export function CartView() {
  const [cart, setCart] = useState<Cart | null>(null);
  const [error, setError] = useState(false);
  const [pendingItemId, setPendingItemId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  const { setCount } = useCartCount();
  const router = useRouter();
  // ボタン連打・ネットワーク再送で同じ注文が重複作成されないよう、確定ボタン押下時に
  // 1回だけ生成してこのref内で使い回す(カート画面到達時点では発行しない)。
  const idempotencyKeyRef = useRef<string | null>(null);

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

  async function handleCheckout() {
    const sessionId = getSessionId();
    if (!sessionId) return;
    if (!idempotencyKeyRef.current) {
      idempotencyKeyRef.current = crypto.randomUUID();
    }
    setSubmitting(true);
    setCheckoutError(null);
    try {
      const order = await createOrder(sessionId, STORE_ID, idempotencyKeyRef.current);
      setCount(0);
      router.push(`/order?id=${order.orderId}`);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 400 || err.status === 409)) {
        // 入力自体が無効(空カート)・キーの使い回し不可(409)なので、同じキーでの再送は無意味。
        idempotencyKeyRef.current = null;
        setCheckoutError(
          err.status === 400
            ? "カートが空です。商品を追加してから確定してください。"
            : "この注文は既に処理されています。",
        );
      } else {
        // ネットワークエラー・5xxはキーを保持したまま再試行を促す(同じ注文として扱われる)。
        setCheckoutError("注文の確定に失敗しました。時間をおいて再度お試しください。");
      }
      setSubmitting(false);
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
      {checkoutError && <p className="mt-4 text-sm text-red-600">{checkoutError}</p>}
      <button
        type="button"
        disabled={submitting}
        onClick={handleCheckout}
        className="mt-4 w-full rounded bg-black py-3 text-white disabled:opacity-40 dark:bg-white dark:text-black"
      >
        注文を確定する
      </button>
    </>
  );
}
