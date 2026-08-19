"use client";

import { useState, type FormEvent } from "react";
import { useStaffAuth } from "@/components/staff/StaffAuthProvider";

export function StaffLoginForm() {
  const { login } = useStaffAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(false);
    try {
      await login(username, password);
    } catch {
      setError(true);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <form onSubmit={handleSubmit} className="flex w-full max-w-sm flex-col gap-4">
        <h1 className="text-xl font-semibold">スタッフログイン</h1>

        <label className="flex flex-col gap-1">
          <span className="text-sm text-zinc-600 dark:text-zinc-400">ユーザー名</span>
          <input
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="rounded border border-black/10 p-3 dark:border-white/10"
            required
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm text-zinc-600 dark:text-zinc-400">パスワード</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded border border-black/10 p-3 dark:border-white/10"
            required
          />
        </label>

        {error && (
          <p className="text-sm text-red-600">ユーザー名またはパスワードが違います。</p>
        )}

        <button
          type="submit"
          disabled={pending}
          className="rounded bg-black py-3 text-white disabled:opacity-40 dark:bg-white dark:text-black"
        >
          {pending ? "ログイン中..." : "ログイン"}
        </button>
      </form>
    </div>
  );
}
