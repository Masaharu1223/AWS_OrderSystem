// store-fn(店員向けAPI)クライアント。認証はCognito JWT(Authorization: Bearer <idToken>)で、
// api.tsのapiFetchに認証注入機構を足さず、ここで明示的にヘッダを渡す(顧客向けエンドポイントに
// 暗黙のグローバル依存を持ち込まないため)。契約はservices/src/domain/store/models.pyと
// services/src/handlers/store.pyに合わせている。
import { apiFetch } from "./api";
import { STORE_ID } from "./orders";

export type Zone = "A" | "B" | "C" | "D";
export type LineStatus = "WAITING" | "PREPARING" | "READY" | "HANDED_OVER" | "CANCELLED";

export interface Variant {
  temperature: "hot" | "iced";
  size: "S" | "M" | "L";
}

export interface ZoneLine {
  orderId: string;
  orderNumber: number;
  lineId: string;
  zone: Zone;
  productId: string;
  name: string;
  variant: Variant;
  quantity: number;
  status: LineStatus;
  queueSeq: number;
  createdAt: string;
}

export interface ZoneLinesResponse {
  lines: ZoneLine[];
  pollAfterSeconds: number;
}

export interface LineStatusUpdateResponse {
  orderId: string;
  lineId: string;
  zone: Zone;
  status: LineStatus;
  preparedAt?: string;
  readyAt?: string;
}

// 許可される遷移はこの2つのみ(services/src/domain/fulfillment/service.py)。
// READYへ遷移した明細はGSI2(製造キュー)から除外されるため、呼び出し側にREADYが渡ることは無い。
export function nextLineStatus(status: LineStatus): LineStatus | null {
  if (status === "WAITING") return "PREPARING";
  if (status === "PREPARING") return "READY";
  return null;
}

function authHeaders(idToken: string): HeadersInit {
  return { Authorization: `Bearer ${idToken}` };
}

export async function fetchZoneLines(zone: Zone, idToken: string): Promise<ZoneLinesResponse> {
  return apiFetch<ZoneLinesResponse>(`/stores/${STORE_ID}/zones/${zone}/lines`, {
    headers: authHeaders(idToken),
  });
}

// 許可される遷移はWAITING→PREPARINGとPREPARING→READYのみ(services/src/domain/fulfillment/service.py)。
// それ以外はサーバー側で409になる(docs/architecture.md §7.5、404は無い)。
export async function updateLineStatus(
  orderId: string,
  lineId: string,
  fromStatus: LineStatus,
  toStatus: LineStatus,
  idToken: string,
): Promise<LineStatusUpdateResponse> {
  return apiFetch<LineStatusUpdateResponse>(`/orders/${orderId}/lines/${lineId}/status`, {
    method: "PATCH",
    headers: { ...authHeaders(idToken), "Content-Type": "application/json" },
    body: JSON.stringify({ fromStatus, toStatus }),
  });
}
