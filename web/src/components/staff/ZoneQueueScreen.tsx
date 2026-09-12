"use client";

import { useCallback, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { useRouter } from "next/navigation";
import { RequireStaffAuth } from "@/components/staff/RequireStaffAuth";
import { UndoBanner } from "@/components/staff/UndoBanner";
import { ZoneLineCard, LINE_ACTION_LABELS } from "@/components/staff/ZoneLineCard";
import { useStaffAuth } from "@/components/staff/StaffAuthProvider";
import { useZoneLines } from "@/hooks/useZoneLines";
import { nextLineStatus, updateLineStatus, type LineStatus, type Zone, type ZoneLine } from "@/lib/staff";

interface PendingAction {
  line: ZoneLine;
  toStatus: LineStatus;
}

// lineIdは注文ごとのローカル連番(services/src/domain/order/service.py)で、ゾーン内の別注文と
// 衝突しうる(どの注文も1件目は"001")。ゾーンキューは複数注文を横断して1覧にまとめるため、
// ReactのkeyやpendingActionsのキーにはorderIdと組み合わせた複合キーを使う。
function lineKey(line: ZoneLine): string {
  return `${line.orderId}:${line.lineId}`;
}

export function ZoneQueueScreen({ zone }: { zone: Zone }) {
  return (
    <RequireStaffAuth>
      <ZoneQueueContent zone={zone} />
    </RequireStaffAuth>
  );
}

function ZoneQueueContent({ zone }: { zone: Zone }) {
  const router = useRouter();
  const { idToken } = useStaffAuth();
  const { lines, error } = useZoneLines(zone);
  // アンドゥ待ちの状態はカード単位ではなくここ(ゾーンページ)で持つ。カード側に持たせると、
  // 3秒のカウントダウン中にポーリング応答が返ってpending中の表示ステータスを巻き戻してしまう。
  const [pendingActions, setPendingActions] = useState<Record<string, PendingAction>>({});
  const [confirmError, setConfirmError] = useState(false);

  const handleSwipe = useCallback((line: ZoneLine) => {
    const toStatus = nextLineStatus(line.status);
    if (!toStatus) return;
    setPendingActions((prev) => ({ ...prev, [lineKey(line)]: { line, toStatus } }));
  }, []);

  const handleUndo = useCallback((key: string) => {
    setPendingActions((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const handleConfirm = useCallback(
    async (key: string, pending: PendingAction) => {
      if (idToken) {
        try {
          await updateLineStatus(
            pending.line.orderId,
            pending.line.lineId,
            pending.line.status,
            pending.toStatus,
            idToken,
          );
          setConfirmError(false);
        } catch {
          // 失敗時は取り消しと同じ扱いで元の一覧に戻す。次回ポーリングで実際の状態を確認できる。
          setConfirmError(true);
        }
      }
      setPendingActions((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    },
    [idToken],
  );

  if (error) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <p className="text-red-600">キューの取得に失敗しました。ページを再読み込みしてください。</p>
      </div>
    );
  }

  const visibleLines = (lines ?? []).filter((line) => !(lineKey(line) in pendingActions));

  return (
    <div className="flex flex-1 flex-col gap-4 p-6 pb-32">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{zone}ゾーン</h1>
        <button
          type="button"
          onClick={() => router.push("/staff")}
          className="text-sm text-zinc-600 underline dark:text-zinc-400"
        >
          ゾーンを選び直す
        </button>
      </div>

      {confirmError && (
        <p className="text-sm text-red-600">更新に失敗しました。時間をおいて再度スワイプしてください。</p>
      )}

      {lines === null ? (
        <p className="text-zinc-600 dark:text-zinc-400">読み込み中...</p>
      ) : visibleLines.length === 0 ? (
        <p className="text-zinc-600 dark:text-zinc-400">担当中の注文はありません。</p>
      ) : (
        <div className="flex flex-col gap-3">
          <AnimatePresence>
            {visibleLines.map((line) => (
              <ZoneLineCard key={lineKey(line)} line={line} onSwipe={() => handleSwipe(line)} />
            ))}
          </AnimatePresence>
        </div>
      )}

      <div className="fixed inset-x-0 bottom-0 flex flex-col gap-2 p-4">
        {Object.entries(pendingActions).map(([key, pending]) => (
          <UndoBanner
            key={key}
            label={`${pending.line.name} を${LINE_ACTION_LABELS[pending.line.status] ?? "次の状態"}にします`}
            onConfirm={() => handleConfirm(key, pending)}
            onUndo={() => handleUndo(key)}
          />
        ))}
      </div>
    </div>
  );
}
