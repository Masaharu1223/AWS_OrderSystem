const SESSION_ID_KEY = "mobileOrder.sessionId";

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
