"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useOrderStatus } from "@/hooks/useOrderStatus";
import type { OrderStatusResponse } from "@/lib/status";

const STATUS_LABELS: Record<OrderStatusResponse["status"], string> = {
  STORE_ACCEPTED: "受付済み",
  PREPARING: "準備中",
  READY_PICKUP: "できあがりました",
  HANDED_OVER: "お渡し済み",
  CANCELLED: "キャンセル済み",
};

export function OrderConfirmation() {
  const searchParams = useSearchParams();
  const orderId = searchParams.get("id");

  if (!orderId) {
    return <p className="text-red-600">注文情報が見つかりません。</p>;
  }

  return <OrderStatusView orderId={orderId} />;
}

function OrderStatusView({ orderId }: { orderId: string }) {
  const { status, error, cancel } = useOrderStatus(orderId);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState(false);

  async function handleCancel() {
    setCancelling(true);
    setCancelError(false);
    try {
      await cancel();
    } catch {
      setCancelError(true);
    } finally {
      setCancelling(false);
    }
  }

  if (error) {
    return (
      <p className="text-red-600">
        状況の取得に失敗しました。ページを再読み込みしてください。
      </p>
    );
  }

  if (!status) {
    return <p className="text-zinc-600 dark:text-zinc-400">読み込み中...</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">注文番号 {status.orderNumber}</p>
        <p className="text-xl font-semibold">{STATUS_LABELS[status.status]}</p>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          できあがり目安 {status.estimatedReadyMinutes}分
        </p>
      </div>

      <ul>
        {status.lines.map((line) => (
          <li
            key={line.lineId}
            className="flex items-baseline justify-between gap-4 border-b border-black/10 py-3 dark:border-white/10"
          >
            <span>
              {line.name} × {line.quantity}
            </span>
            <span className="text-sm text-zinc-600 dark:text-zinc-400">
              {line.zone}ゾーン / 目安{line.estimatedWaitMinutes}分
            </span>
          </li>
        ))}
      </ul>

      {cancelError && (
        <p className="text-sm text-red-600">キャンセルに失敗しました。時間をおいて再度お試しください。</p>
      )}

      {status.status === "STORE_ACCEPTED" && (
        <button
          type="button"
          disabled={cancelling}
          onClick={handleCancel}
          className="rounded border border-red-600 py-3 text-red-600 disabled:opacity-40"
        >
          注文をキャンセルする
        </button>
      )}
    </div>
  );
}
