"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useStaffAuth } from "@/components/staff/StaffAuthProvider";
import { ApiError } from "@/lib/api";
import { fetchZoneLines, type Zone, type ZoneLine } from "@/lib/staff";

const BACKOFF_INITIAL_SECONDS = 15;
const BACKOFF_MAX_SECONDS = 120;
const MAX_CONSECUTIVE_FAILURES = 5;

interface UseZoneLinesResult {
  lines: ZoneLine[] | null;
  error: boolean;
}

// web/src/hooks/useOrderStatus.tsのポーリング設計(サーバー主導pollAfterSeconds・指数バックオフ・
// visibilitychangeでの一時停止/再開・アンマウント時クリーンアップ)を踏襲するが、2点はあえて変える。
// (1) ゾーンキューに終端状態が無い(pollAfterSeconds: nullが来ない)ため、
//     useOrderStatusのMAX_POLLING_DURATION_MSは持ち込まない(シフト中にポーリングが止まる事故になる)。
// (2) 401は通常の失敗としてバックオフに数えず、StaffAuthProviderのrefresh()経由でリフレッシュしてから
//     即座に再試行する。
export function useZoneLines(zone: Zone): UseZoneLinesResult {
  const { idToken, refresh } = useStaffAuth();
  const [lines, setLines] = useState<ZoneLine[] | null>(null);
  const [error, setError] = useState(false);

  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backoffSecondsRef = useRef<number | null>(null);
  const consecutiveFailuresRef = useRef(0);
  const mountedRef = useRef(true);
  const idTokenRef = useRef(idToken);
  const pollRef = useRef<() => Promise<void>>(async () => {});

  useEffect(() => {
    idTokenRef.current = idToken;
  }, [idToken]);

  const clearScheduled = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const poll = useCallback(async () => {
    if (!mountedRef.current) return;
    if (document.visibilityState !== "visible") return;
    // RequireStaffAuthがidToken確立後にしかこのフックをマウントさせない想定だが、
    // 型上nullableなためガードする。
    const token = idTokenRef.current;
    if (!token) return;

    try {
      const result = await fetchZoneLines(zone, token);
      if (!mountedRef.current) return;
      consecutiveFailuresRef.current = 0;
      backoffSecondsRef.current = null;
      setError(false);
      setLines(result.lines);
      timeoutRef.current = setTimeout(() => pollRef.current(), result.pollAfterSeconds * 1000);
    } catch (err) {
      if (!mountedRef.current) return;

      if (err instanceof ApiError && err.status === 401) {
        try {
          await refresh();
          timeoutRef.current = setTimeout(() => pollRef.current(), 0);
        } catch {
          // refresh()自体がStaffAuthProviderをunauthenticatedへ遷移させ、
          // ログイン画面へのリダイレクトはRequireStaffAuth側の責務になる。ここでは何もしない。
        }
        return;
      }

      const isRateLimited = err instanceof ApiError && err.status === 429;
      if (!isRateLimited) {
        consecutiveFailuresRef.current += 1;
        if (consecutiveFailuresRef.current >= MAX_CONSECUTIVE_FAILURES) {
          setError(true);
          return;
        }
      }
      backoffSecondsRef.current = backoffSecondsRef.current
        ? Math.min(backoffSecondsRef.current * 2, BACKOFF_MAX_SECONDS)
        : BACKOFF_INITIAL_SECONDS;
      timeoutRef.current = setTimeout(() => pollRef.current(), backoffSecondsRef.current * 1000);
    }
  }, [zone, refresh]);

  useEffect(() => {
    pollRef.current = poll;
  }, [poll]);

  useEffect(() => {
    mountedRef.current = true;
    timeoutRef.current = setTimeout(() => pollRef.current(), 0);
    return () => {
      mountedRef.current = false;
      clearScheduled();
    };
  }, [zone, clearScheduled]);

  useEffect(() => {
    function handleVisibilityChange() {
      clearScheduled();
      if (document.visibilityState === "visible") {
        pollRef.current();
      }
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, [clearScheduled]);

  return { lines, error };
}
