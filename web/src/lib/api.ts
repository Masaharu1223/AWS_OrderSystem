const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://pbmejzmuo4.execute-api.ap-northeast-1.amazonaws.com";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// API Gatewayのスロットリング(429)はLambda側の共通エラーエンベロープ({code, message, requestId})を
// 経由しないプレーンテキスト応答を返すことがある(tasks/todo.md §6)。本文の形式に依存せず、まず
// HTTPステータスコードを正として扱う。
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, init);

  if (!res.ok) {
    let message = `request failed: ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.error?.message === "string") {
        message = body.error.message;
      }
    } catch {
      // 本文がJSONでない場合(429のプレーンテキスト等)はステータスのみで扱う
    }
    throw new ApiError(res.status, message);
  }

  return res.json();
}
