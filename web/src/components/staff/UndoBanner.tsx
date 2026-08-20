"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";

// 要件定義書§5.4: スワイプ後3秒間「取り消し」バナーを表示。3秒以内に取り消せばAPIを叩かず、
// 3秒経過後に初めてDynamoDBへの書き込み(PATCH)を確定する。
const UNDO_WINDOW_SECONDS = 3;

interface UndoBannerProps {
  label: string;
  onConfirm: () => void;
  onUndo: () => void;
}

export function UndoBanner({ label, onConfirm, onUndo }: UndoBannerProps) {
  // onConfirmの参照は親の再レンダーで変わりうるが、3秒のタイマー自体はマウント時に1回だけ
  // 仕掛けたい(再レンダーのたびに延長されると3秒という約束が崩れる)ため、refで最新を追う。
  const onConfirmRef = useRef(onConfirm);
  useEffect(() => {
    onConfirmRef.current = onConfirm;
  }, [onConfirm]);

  useEffect(() => {
    const timeoutId = setTimeout(() => onConfirmRef.current(), UNDO_WINDOW_SECONDS * 1000);
    return () => clearTimeout(timeoutId);
  }, []);

  return (
    <div className="overflow-hidden rounded-lg border border-black/10 bg-white shadow-lg dark:border-white/10 dark:bg-zinc-900">
      <div className="flex items-center justify-between gap-4 p-4">
        <span>{label}</span>
        <button
          type="button"
          onClick={onUndo}
          className="shrink-0 rounded border border-black/20 px-4 py-2 dark:border-white/20"
        >
          取り消し
        </button>
      </div>
      <motion.div
        className="h-1 bg-black/60 dark:bg-white/60"
        initial={{ width: "100%" }}
        animate={{ width: "0%" }}
        transition={{ duration: UNDO_WINDOW_SECONDS, ease: "linear" }}
      />
    </div>
  );
}
