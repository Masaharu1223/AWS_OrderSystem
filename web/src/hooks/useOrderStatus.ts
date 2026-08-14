import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { cancelOrder, fetchOrderStatus, type OrderStatusResponse } from "@/lib/status";

const BACKOFF_INITIAL_SECONDS = 15;
const BACKOFF_MAX_SECONDS = 120;
const MAX_CONSECUTIVE_FAILURES = 5;
const MAX_POLLING_DURATION_MS = 60 * 60 * 1000;

interface UseOrderStatusResult {
  status: OrderStatusResponse | null;
  error: boolean;
  cancel: () => Promise<void>;
}

export function useOrderStatus(orderId: string): UseOrderStatusResult {
  const [status, setStatus] = useState<OrderStatusResponse | null>(null);
  const [error, setError] = useState(false);

  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backoffSecondsRef = useRef<number | null>(null);
  const consecutiveFailuresRef = useRef(0);
  const startTimeRef = useRef(0);
  const terminalRef = useRef(false);
  const mountedRef = useRef(true);
  // pollは自身をsetTimeoutで再帰的に呼び出すため、useCallback本体から直接自己参照すると
  // react-hooks/immutabilityに反する。安定した参照先としてrefに逃がして呼び出す。
  const pollRef = useRef<() => Promise<void>>(async () => {});

  const clearScheduled = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const poll = useCallback(async () => {
    if (!mountedRef.current || terminalRef.current) return;
    if (Date.now() - startTimeRef.current > MAX_POLLING_DURATION_MS) {
      setError(true);
      return;
    }
    // タブが裏に回っている間はfetchしない。visibilitychangeハンドラが復帰時に再開する。
    if (document.visibilityState !== "visible") return;

    try {
      const result = await fetchOrderStatus(orderId);
      if (!mountedRef.current) return;
      consecutiveFailuresRef.current = 0;
      backoffSecondsRef.current = null;
      setError(false);
      setStatus(result);
      if (result.pollAfterSeconds === null) {
        terminalRef.current = true;
        return;
      }
      timeoutRef.current = setTimeout(() => pollRef.current(), result.pollAfterSeconds * 1000);
    } catch (err) {
      if (!mountedRef.current) return;
      // 429（一時的な混雑によるスロットリング）は連続失敗カウントに含めない。詳細な判断根拠は
      // docs/order-status-polling-design.md を参照。
      const isRateLimited = err instanceof ApiError && err.status === 429;
      if (!isRateLimited) {
        consecutiveFailuresRef.current += 1;
        if (consecutiveFailuresRef.current >= MAX_CONSECUTIVE_FAILURES) {
          setError(true);
          return;
        }
      }
      // 429だけでなく他の失敗（ネットワークエラー・5xx）でも同じ指数バックオフを使い、
      // 障害発生時にサーバーを叩き続けないようにする。
      backoffSecondsRef.current = backoffSecondsRef.current
        ? Math.min(backoffSecondsRef.current * 2, BACKOFF_MAX_SECONDS)
        : BACKOFF_INITIAL_SECONDS;
      timeoutRef.current = setTimeout(() => pollRef.current(), backoffSecondsRef.current * 1000);
    }
  }, [orderId]);

  useEffect(() => {
    pollRef.current = poll;
  }, [poll]);

  useEffect(() => {
    mountedRef.current = true;
    terminalRef.current = false;
    startTimeRef.current = Date.now();
    // poll()を直接呼ぶとeffect内で同期的にsetStateしうる呼び出しとして検出されるため、
    // pollRef経由のコールバックに包んでマイクロタスク以降に遅延させる。
    timeoutRef.current = setTimeout(() => pollRef.current(), 0);
    return () => {
      mountedRef.current = false;
      clearScheduled();
    };
  }, [orderId, clearScheduled]);

  useEffect(() => {
    function handleVisibilityChange() {
      clearScheduled();
      if (document.visibilityState === "visible") {
        poll();
      }
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, [poll, clearScheduled]);

  const cancel = useCallback(async () => {
    clearScheduled();
    try {
      await cancelOrder(orderId);
    } catch (err) {
      // キャンセル自体が失敗しても状況ポーリングは止めない。
      poll();
      throw err;
    }
    // cancelOrderの戻り値（Order型）は使わず、OrderStatusResponse型のまま状態を更新するため
    // 通常のpollを再利用してGET /orders/{orderId}を取り直す。
    await poll();
  }, [orderId, clearScheduled, poll]);

  return { status, error, cancel };
}
