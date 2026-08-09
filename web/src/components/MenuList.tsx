"use client";

import { useEffect, useState } from "react";
import { fetchMenu, type MenuResponse, type Product } from "@/lib/menu";

function formatPrice(yen: number): string {
  return `¥${yen.toLocaleString("ja-JP")}`;
}

function ProductRow({ product }: { product: Product }) {
  const sizes = Object.entries(product.sizeDelta)
    .map(([size, delta]) => `${size}${delta > 0 ? ` +${formatPrice(delta)}` : ""}`)
    .join(" / ");

  return (
    <li className="flex flex-col gap-1 border-b border-black/10 py-3 dark:border-white/10">
      <div className="flex items-baseline justify-between gap-4">
        <span className="font-medium">{product.name}</span>
        <span>{formatPrice(product.basePrice)}〜</span>
      </div>
      <span className="text-sm text-zinc-600 dark:text-zinc-400">{sizes}</span>
    </li>
  );
}

export function MenuList() {
  const [menu, setMenu] = useState<MenuResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetchMenu()
      .then(setMenu)
      .catch(() => setError(true));
  }, []);

  if (error) {
    return <p className="text-red-600">メニューの取得に失敗しました。時間をおいて再度お試しください。</p>;
  }

  if (!menu) {
    return <p className="text-zinc-600 dark:text-zinc-400">読み込み中...</p>;
  }

  return (
    <>
      {menu.categories.map((category) => (
        <section key={category.category} className="mb-8">
          <h2 className="mb-2 text-lg font-semibold capitalize">{category.category}</h2>
          <ul>
            {category.products.map((product) => (
              <ProductRow key={product.productId} product={product} />
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}
