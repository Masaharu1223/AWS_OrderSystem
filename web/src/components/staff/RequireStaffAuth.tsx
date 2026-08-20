"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useStaffAuth } from "@/components/staff/StaffAuthProvider";

// 未ログイン状態で保護されたページ(ゾーンキュー画面等)へ直接アクセスした場合に
// /staffへリダイレクトするガード。
export function RequireStaffAuth({ children }: { children: ReactNode }) {
  const { status } = useStaffAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/staff");
    }
  }, [status, router]);

  // loading/unauthenticated中は何も描画しない(リダイレクト前のちらつきを避ける)。
  if (status !== "authenticated") return null;
  return <>{children}</>;
}
