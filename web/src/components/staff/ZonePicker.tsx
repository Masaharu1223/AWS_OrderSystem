"use client";

import { useRouter } from "next/navigation";
import { useStaffAuth } from "@/components/staff/StaffAuthProvider";

// 要件定義書§5.1: 固定の役割や記憶された選択はなく、ログインのたびにA/B/C/Dから選び直す
// フラットな一覧。選択そのものは永続化せず、選んだ先のURL(/staff/zone/{zone})だけが状態を持つ。
const ZONES = ["A", "B", "C", "D"] as const;

export function ZonePicker() {
  const router = useRouter();
  const { logout } = useStaffAuth();

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-8 p-6">
      <h1 className="text-xl font-semibold">担当ゾーンを選択</h1>

      <div className="grid grid-cols-2 gap-4">
        {ZONES.map((zone) => (
          <button
            key={zone}
            type="button"
            onClick={() => router.push(`/staff/zone/${zone}`)}
            className="flex h-28 w-28 items-center justify-center rounded-lg border border-black/10 text-3xl font-semibold dark:border-white/10"
          >
            {zone}
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={logout}
        className="text-sm text-zinc-600 underline dark:text-zinc-400"
      >
        ログアウト
      </button>
    </div>
  );
}
