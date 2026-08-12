"use client";

import { useSearchParams } from "next/navigation";

export function OrderConfirmation() {
  const searchParams = useSearchParams();
  const orderId = searchParams.get("id");

  if (!orderId) {
    return <p className="text-red-600">注文情報が見つかりません。</p>;
  }

  // ポーリングでの状況表示・キャンセルボタンは別途実装予定。
  return (
    <p className="text-zinc-600 dark:text-zinc-400">
      ご注文を受け付けました(注文ID: {orderId})。
    </p>
  );
}
