import { apiFetch } from "./api";

export interface Variant {
  temperature: "hot" | "iced";
  size: string;
}

export interface CartItem {
  itemId: string;
  productId: string;
  category: string;
  name: string;
  variant: Variant;
  quantity: number;
  unitPrice: number;
  lineTotal: number;
}

export interface Cart {
  sessionId: string;
  items: CartItem[];
  subtotal: number;
}

export interface AddItemInput {
  productId: string;
  category: string;
  variant: Variant;
  quantity: number;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export async function fetchCart(sessionId: string): Promise<Cart> {
  return apiFetch<Cart>(`/cart/${encodeURIComponent(sessionId)}`);
}

export async function addItem(sessionId: string, input: AddItemInput): Promise<Cart> {
  return apiFetch<Cart>(`/cart/${encodeURIComponent(sessionId)}/items`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
  });
}

// itemIdは"prod-001#iced#M"のような形式で"#"を含む。URLパスに生のまま埋め込むと
// ブラウザに"#"以降がフラグメントとして解釈され送信されないため、必ずここでencodeする。
export async function updateQuantity(
  sessionId: string,
  itemId: string,
  quantity: number,
): Promise<Cart> {
  return apiFetch<Cart>(
    `/cart/${encodeURIComponent(sessionId)}/items/${encodeURIComponent(itemId)}`,
    {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ quantity }),
    },
  );
}

export async function deleteItem(sessionId: string, itemId: string): Promise<Cart> {
  return apiFetch<Cart>(
    `/cart/${encodeURIComponent(sessionId)}/items/${encodeURIComponent(itemId)}`,
    { method: "DELETE" },
  );
}
