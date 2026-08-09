const SESSION_ID_KEY = "mobileOrder.sessionId";

// 既存のsessionIdを読むだけで、無ければ何もしない(新規発行しない)。カート件数バッジや
// カート画面の初期表示など、「あれば使う・無ければ空として扱う」場面で使う。
// メニューを眺めただけの訪問者にIDを発行してしまわないよう、発行そのものは
// getOrCreateSessionId()側の1箇所(カート追加ハンドラ)に閉じる。
export function getSessionId(): string | null {
  return window.localStorage.getItem(SESSION_ID_KEY);
}

// cart-fnのsessionIdはクライアント生成のUUIDで、サーバー側に「存在するセッション」という概念が
// 無い(docs/architecture.md §7.2)。localStorageに保存し、無ければ新規発行する。
// 呼び出しはuseEffect内などブラウザ実行時に限定すること(レンダー中に呼ぶと、静的エクスポートで
// 事前生成されたHTMLとブラウザでの実行結果が食い違うハイドレーション不整合の原因になる)。
export function getOrCreateSessionId(): string {
  const existing = window.localStorage.getItem(SESSION_ID_KEY);
  if (existing) {
    return existing;
  }

  const sessionId = crypto.randomUUID();
  window.localStorage.setItem(SESSION_ID_KEY, sessionId);
  return sessionId;
}
