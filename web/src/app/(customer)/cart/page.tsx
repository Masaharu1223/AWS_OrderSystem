import { CartView } from "@/components/CartView";

export default function CartPage() {
  return (
    <main className="mx-auto max-w-xl px-6 py-16">
      <h1 className="mb-8 text-2xl font-semibold">カート</h1>
      <CartView />
    </main>
  );
}
