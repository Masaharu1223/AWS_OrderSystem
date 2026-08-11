"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCartCount } from "@/components/CartCountProvider";

export function Header() {
  const { count } = useCartCount();
  const pathname = usePathname();
  // trailingSlash: true構成のため、遷移直後は"/cart/"になる(末尾スラッシュ無しの
  // "/cart"も念のため許容しておく)。
  const isCartPage = pathname === "/cart" || pathname === "/cart/";

  return (
    <header className="flex items-center justify-between border-b border-black/10 px-6 py-4 dark:border-white/10">
      <span className="font-semibold">モバイルオーダー</span>
      {isCartPage ? (
        <Link href="/" className="text-sm underline">
          ← メニューに戻る
        </Link>
      ) : (
        <Link href="/cart" className="relative">
          <span aria-hidden>🛒</span>
          <span className="sr-only">カート</span>
          {count > 0 && (
            <span className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full bg-red-600 text-xs text-white">
              {count}
            </span>
          )}
        </Link>
      )}
    </header>
  );
}
