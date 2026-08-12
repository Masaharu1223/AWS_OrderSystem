import { apiFetch } from "./api";
import type { Variant } from "./cart";

// 単一店舗のMVPのため店舗選択UIは作らず、固定値を使う。
export const STORE_ID = "store-01";

export interface OrderLine {
  lineId: string;
  productId: string;
  name: string;
  category: string;
  variant: Variant;
  quantity: number;
  unitPrice: number;
  zone: string;
  status: string;
  queueSeq: number;
  createdAt: string;
  updatedAt: string;
  lineTotal: number;
}

export interface Order {
  orderId: string;
  orderNumber: number;
  storeId: string;
  lines: OrderLine[];
  createdAt: string;
  status: string;
  totalPrice: number;
}

export async function createOrder(
  sessionId: string,
  storeId: string,
  idempotencyKey: string,
): Promise<Order> {
  return apiFetch<Order>("/orders", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({ sessionId, storeId }),
  });
}
