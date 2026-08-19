"use client";

import { useStaffAuth } from "@/components/staff/StaffAuthProvider";
import { StaffLoginForm } from "@/components/staff/StaffLoginForm";
import { ZonePicker } from "@/components/staff/ZonePicker";

export default function StaffEntryPage() {
  const { status } = useStaffAuth();

  // sessionStorageからの復元判定中は何も描画しない(ログイン画面が一瞬見えてから
  // ゾーン選択に切り替わる、というちらつきを避けるため)。
  if (status === "loading") return null;
  if (status === "unauthenticated") return <StaffLoginForm />;
  return <ZonePicker />;
}
