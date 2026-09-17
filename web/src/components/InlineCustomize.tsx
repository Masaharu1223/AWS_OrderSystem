"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import type { Product } from "@/lib/menu";
import { addItem, type Cart } from "@/lib/cart";
import { getOrCreateSessionId } from "@/lib/session";

function formatPrice(yen: number): string {
  return `¥${yen.toLocaleString("ja-JP")}`;
}

interface InlineCustomizeProps {
  product: Product;
  onAdded: (cart: Cart) => void;
}

// 商品行の直下に半展開するミニカスタム(lazyweb Growth Report「1-Tap Customize」仮説の
// モックアップに準拠)。VariantModal(全画面オーバーレイ)を置き換え、一覧から離脱せず
// サイズ/温度を選んでその場でカートに追加できるようにする。
export function InlineCustomize({ product, onAdded }: InlineCustomizeProps) {
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
      setSubmitting(false);
    }
  }

  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: "auto", opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      className="overflow-hidden"
    >
      <div className="flex flex-col gap-4 pb-4">
        <fieldset>
          <legend className="mb-2 text-sm text-zinc-600 dark:text-zinc-400">サイズ</legend>
          <div className="flex gap-2">
            {sizes.map((option) => {
              const delta = product.sizeDelta[option] ?? 0;
              return (
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
                  {delta > 0 ? ` +${formatPrice(delta)}` : ""}
                </button>
              );
            })}
          </div>
        </fieldset>

        {product.allowHot && product.allowIced && (
          <fieldset>
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

        {error && (
          <p className="text-sm text-red-600">
            カートへの追加に失敗しました。時間をおいて再度お試しください。
          </p>
        )}

        <button
          type="button"
          disabled={submitting}
          onClick={handleAdd}
          className="w-full rounded bg-black py-3 text-white disabled:opacity-40 dark:bg-white dark:text-black"
        >
          {formatPrice(price)}で追加
        </button>
      </div>
    </motion.div>
  );
}
