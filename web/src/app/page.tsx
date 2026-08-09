import { MenuList } from "@/components/MenuList";

export default function Home() {
  return (
    <main className="mx-auto max-w-xl px-6 py-16">
      <h1 className="mb-8 text-2xl font-semibold">メニュー</h1>
      <MenuList />
    </main>
  );
}
