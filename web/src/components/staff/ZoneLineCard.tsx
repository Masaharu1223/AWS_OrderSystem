"use client";

import { motion, type PanInfo } from "framer-motion";
import type { LineStatus, ZoneLine } from "@/lib/staff";

// GSI2(製造キュー)はWAITING/PREPARINGの明細しか持たないスパースインデックスのため
// (services/src/adapters/order_repository.py)、ここに届くlineのstatusは実質この2値しかない。
export const LINE_ACTION_LABELS: Partial<Record<LineStatus, string>> = {
  WAITING: "製造開始",
  PREPARING: "完成",
};

const SWIPE_THRESHOLD_PX = 96;

interface ZoneLineCardProps {
  line: ZoneLine;
  onSwipe: () => void;
}

export function ZoneLineCard({ line, onSwipe }: ZoneLineCardProps) {
  function handleDragEnd(_event: unknown, info: PanInfo) {
    if (info.offset.x > SWIPE_THRESHOLD_PX) {
      onSwipe();
    }
  }

  return (
    <motion.div
      layout
      exit={{ opacity: 0, x: 200 }}
      drag="x"
      dragConstraints={{ left: 0, right: 0 }}
      dragElastic={{ left: 0, right: 0.6 }}
      dragSnapToOrigin
      onDragEnd={handleDragEnd}
      whileDrag={{ scale: 1.02 }}
      className="flex cursor-grab items-center justify-between gap-4 rounded-lg border border-black/10 bg-white p-4 active:cursor-grabbing dark:border-white/10 dark:bg-zinc-900"
    >
      <div>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          #{line.orderNumber} ・ {line.queueSeq}番目
        </p>
        <p className="text-lg font-semibold">
          {line.name}（{line.variant.temperature === "hot" ? "ホット" : "アイス"}・{line.variant.size}） ×{" "}
          {line.quantity}
        </p>
      </div>
      <span className="shrink-0 whitespace-nowrap text-sm text-zinc-600 dark:text-zinc-400">
        → {LINE_ACTION_LABELS[line.status] ?? line.status}
      </span>
    </motion.div>
  );
}
