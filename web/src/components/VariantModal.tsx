"use client";

import { useState } from "react";
import type { Product } from "@/lib/menu";
import { addItem, type Cart } from "@/lib/cart";
import { getOrCreateSessionId } from "@/lib/session";

function formatPrice(yen: number): string {
  return `¥${yen.toLocaleString("ja-JP")}`;
}

interface VariantModalProps {
  product: Product;
  onClose: () => void;
  onAdded: (cart: Cart) => void;
}

export function VariantModal({ product, onClose, onAdded }: VariantModalProps) {
  const sizes = Object.keys(product.sizeDelta);
  // 未選択状態を作らないため、開いた時点で選べる中から必ず1つを初期選択にしておく。
  const [temperature, setTemperature] = useState<"hot" | "iced">(
    product.allowHot ? "hot" : "iced",
  );
  const [size, setSize] = useState(sizes[0]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(false);

  const price = product.basePrice + (product.sizeDelta[size] ?? 0);

  async function handleAdd() {
    setSubmitting(true);
    setError(false);
    try {
      const sessionId = getOrCreateSessionId();
      const cart = await addItem(sessionId, {
        productId: product.productId,
        category: product.category,
        variant: { temperature, size },
        quantity: 1,
      });
      onAdded(cart);
    } catch {
      setError(true);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-t-2xl bg-white p-6 sm:rounded-2xl dark:bg-zinc-900"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-baseline justify-between gap-4">
          <h2 className="text-lg font-semibold">{product.name}</h2>
          <span className="text-lg font-semibold">{formatPrice(price)}</span>
        </div>

        {product.allowHot && product.allowIced && (
          <fieldset className="mb-4">
            <legend className="mb-2 text-sm text-zinc-600 dark:text-zinc-400">温度</legend>
            <div className="flex gap-2">
              {(["hot", "iced"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setTemperature(option)}
                  className={`flex-1 rounded border py-2 text-sm ${
                    temperature === option
                      ? "border-black bg-black text-white dark:border-white dark:bg-white dark:text-black"
                      : "border-black/20 dark:border-white/20"
                  }`}
                >
                  {option === "hot" ? "ホット" : "アイス"}
                </button>
              ))}
            </div>
          </fieldset>
        )}

        <fieldset className="mb-6">
          <legend className="mb-2 text-sm text-zinc-600 dark:text-zinc-400">サイズ</legend>
          <div className="flex gap-2">
            {sizes.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setSize(option)}
                className={`flex-1 rounded border py-2 text-sm ${
                  size === option
                    ? "border-black bg-black text-white dark:border-white dark:bg-white dark:text-black"
                    : "border-black/20 dark:border-white/20"
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        </fieldset>

        {error && (
          <p className="mb-4 text-sm text-red-600">
            カートへの追加に失敗しました。時間をおいて再度お試しください。
          </p>
        )}

        <div className="flex gap-3">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 rounded border border-black/20 py-3 dark:border-white/20"
          >
            キャンセル
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={handleAdd}
            className="flex-1 rounded bg-black py-3 text-white disabled:opacity-40 dark:bg-white dark:text-black"
          >
            カートに追加
          </button>
        </div>
      </div>
    </div>
  );
}
