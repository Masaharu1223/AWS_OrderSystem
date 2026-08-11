"use client";

import Link from "next/link";
import { useCartCount } from "@/components/CartCountProvider";

export function Header() {
  const { count } = useCartCount();

  return (
    <header className="flex items-center justify-between border-b border-black/10 px-6 py-4 dark:border-white/10">
      <span className="font-semibold">モバイルオーダー</span>
      <Link href="/cart" className="relative">
        <span aria-hidden>🛒</span>
        <span className="sr-only">カート</span>
        {count > 0 && (
          <span className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full bg-red-600 text-xs text-white">
            {count}
          </span>
        )}
      </Link>
    </header>
  );
}
