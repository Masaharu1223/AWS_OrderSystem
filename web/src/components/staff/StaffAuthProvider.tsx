"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import {
  AuthError,
  clearStoredTokens,
  getStoredTokens,
  refreshTokens as refreshTokensRequest,
  setStoredTokens,
  signIn as signInRequest,
  type AuthTokens,
} from "@/lib/auth";

type StaffAuthStatus = "loading" | "authenticated" | "unauthenticated";

interface StaffAuthContextValue {
  status: StaffAuthStatus;
  idToken: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  // 期限間近の先回りリフレッシュと、API呼び出し側での401時の1回リトライの両方から呼ばれる
  // 単一の窓口。失敗時はunauthenticatedへ遷移した上でthrowする。
  refresh: () => Promise<string>;
}

const StaffAuthContext = createContext<StaffAuthContextValue | null>(null);

// この時間を切ったら期限切れ前でも先回りでリフレッシュする。
const REFRESH_MARGIN_MS = 5 * 60 * 1000;

export function StaffAuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<StaffAuthStatus>("loading");
  const [tokens, setTokens] = useState<AuthTokens | null>(null);

  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // setTimeoutのコールバックは発火時点の最新のrefreshを呼びたいため、
  // web/src/hooks/useOrderStatus.tsのpollRefと同じ理由でrefに逃がす。
  const refreshRef = useRef<() => Promise<string>>(async () => {
    throw new AuthError("StaffAuthProvider not ready");
  });

  const clearScheduled = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const applyTokens = useCallback(
    (next: AuthTokens) => {
      setStoredTokens(next);
      setTokens(next);
      setStatus("authenticated");
      clearScheduled();
      const delay = Math.max(next.expiresAt * 1000 - Date.now() - REFRESH_MARGIN_MS, 0);
      timeoutRef.current = setTimeout(() => {
        refreshRef.current().catch(() => {});
      }, delay);
    },
    [clearScheduled],
  );

  const forgetTokens = useCallback(() => {
    clearScheduled();
    clearStoredTokens();
    setTokens(null);
    setStatus("unauthenticated");
  }, [clearScheduled]);

  const refresh = useCallback(async (): Promise<string> => {
    const current = tokens ?? getStoredTokens();
    if (!current) {
      forgetTokens();
      throw new AuthError("no session to refresh");
    }
    try {
      const next = await refreshTokensRequest(current.refreshToken);
      applyTokens(next);
      return next.idToken;
    } catch (err) {
      // リフレッシュトークン自体の失効(1日)・ネットワークエラーいずれも区別せず、
      // ログイン画面へ戻す(共有タブレットでの運用上、これ以上の状態管理は複雑さに見合わない)。
      forgetTokens();
      throw err;
    }
  }, [tokens, applyTokens, forgetTokens]);

  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  // 初回マウント時にsessionStorageから復元する。web/src/lib/session.tsと同じ規約で、
  // sessionStorage参照はuseEffect内に限定する(レンダー中に呼ぶとハイドレーション不整合を招く)。
  // setStateをeffect本体で同期的に呼ぶとreact-hooks/set-state-in-effectに引っかかるため、
  // web/src/hooks/useOrderStatus.tsのpoll呼び出しと同じくsetTimeout(...,0)で1マイクロタスク遅延させる。
  // applyTokens/clearScheduledは参照が安定している(依存先が変化しない)ため、
  // 深い依存配列に含めても実質「マウント時1回だけ」実行される。
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      const stored = getStoredTokens();
      if (!stored) {
        setStatus("unauthenticated");
        return;
      }
      if (stored.expiresAt * 1000 - Date.now() > REFRESH_MARGIN_MS) {
        applyTokens(stored);
      } else {
        refreshRef.current().catch(() => {});
      }
    }, 0);
    return () => {
      clearTimeout(timeoutId);
      clearScheduled();
    };
  }, [applyTokens, clearScheduled]);

  const login = useCallback(
    async (username: string, password: string) => {
      const next = await signInRequest(username, password);
      applyTokens(next);
    },
    [applyTokens],
  );

  const logout = useCallback(() => {
    forgetTokens();
  }, [forgetTokens]);

  const value: StaffAuthContextValue = {
    status,
    idToken: tokens?.idToken ?? null,
    login,
    logout,
    refresh,
  };

  return <StaffAuthContext.Provider value={value}>{children}</StaffAuthContext.Provider>;
}

export function useStaffAuth(): StaffAuthContextValue {
  const context = useContext(StaffAuthContext);
  if (!context) {
    throw new Error("useStaffAuth must be used within a StaffAuthProvider");
  }
  return context;
}
