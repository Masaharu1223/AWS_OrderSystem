"use client";

import { useEffect, useState } from "react";
import { fetchMenu, type MenuResponse, type Product } from "@/lib/menu";
import { VariantModal } from "@/components/VariantModal";
import { useCartCount } from "@/components/CartCountProvider";
import { cartItemCount } from "@/lib/cart";

function formatPrice(yen: number): string {
  return `¥${yen.toLocaleString("ja-JP")}`;
}

function ProductRow({ product, onSelect }: { product: Product; onSelect: (product: Product) => void }) {
  const sizes = Object.entries(product.sizeDelta)
    .map(([size, delta]) => `${size}${delta > 0 ? ` +${formatPrice(delta)}` : ""}`)
    .join(" / ");

  return (
    <li className="border-b border-black/10 dark:border-white/10">
      <button
        type="button"
        disabled={!product.available}
        onClick={() => onSelect(product)}
        className="flex w-full flex-col gap-1 py-3 text-left disabled:opacity-40"
      >
        <div className="flex items-baseline justify-between gap-4">
          <span className="font-medium">
            {product.name}
            {!product.available && (
              <span className="ml-2 text-xs text-zinc-500">品切れ</span>
            )}
          </span>
          <span>{formatPrice(product.basePrice)}〜</span>
        </div>
        <span className="text-sm text-zinc-600 dark:text-zinc-400">{sizes}</span>
      </button>
    </li>
  );
}

export function MenuList() {
  const [menu, setMenu] = useState<MenuResponse | null>(null);
  const [error, setError] = useState(false);
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const { setCount } = useCartCount();

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
              <ProductRow key={product.productId} product={product} onSelect={setSelectedProduct} />
            ))}
          </ul>
        </section>
      ))}
      {selectedProduct && (
        <VariantModal
          key={selectedProduct.productId}
          product={selectedProduct}
          onClose={() => setSelectedProduct(null)}
          onAdded={(cart) => {
            setSelectedProduct(null);
            setCount(cartItemCount(cart));
          }}
        />
      )}
    </>
  );
}
