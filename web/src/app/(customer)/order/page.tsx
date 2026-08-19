import { Suspense } from "react";
import { OrderConfirmation } from "@/components/OrderConfirmation";

export default function OrderPage() {
  return (
    <main className="mx-auto max-w-xl px-6 py-16">
      <h1 className="mb-8 text-2xl font-semibold">注文状況</h1>
      <Suspense fallback={<p className="text-zinc-600 dark:text-zinc-400">読み込み中...</p>}>
        <OrderConfirmation />
      </Suspense>
    </main>
  );
}
