import { apiFetch } from "./api";
import type { Order } from "./orders";

export interface OrderStatusLine {
  lineId: string;
  name: string;
  zone: "A" | "B" | "C" | "D";
  status: "WAITING" | "PREPARING" | "READY" | "HANDED_OVER" | "CANCELLED";
  quantity: number;
  position: number | null;
  estimatedWaitMinutes: number;
}

export interface OrderStatusResponse {
  orderId: string;
  orderNumber: number;
  status: "STORE_ACCEPTED" | "PREPARING" | "READY_PICKUP" | "HANDED_OVER" | "CANCELLED";
  updatedAt: string;
  lines: OrderStatusLine[];
  estimatedReadyMinutes: number;
  pollAfterSeconds: number | null;
}

export async function fetchOrderStatus(orderId: string): Promise<OrderStatusResponse> {
  return apiFetch<OrderStatusResponse>(`/orders/${orderId}`);
}

export async function cancelOrder(orderId: string): Promise<Order> {
  return apiFetch<Order>(`/orders/${orderId}/cancel`, { method: "PATCH" });
}
