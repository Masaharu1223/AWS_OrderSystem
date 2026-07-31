export interface Product {
  productId: string;
  category: string;
  name: string;
  basePrice: number;
  sizeDelta: Record<string, number>;
  allowHot: boolean;
  allowIced: boolean;
  available: boolean;
  displayOrder: number | null;
}

export interface MenuCategory {
  category: string;
  products: Product[];
}

export interface MenuResponse {
  categories: MenuCategory[];
}

const API_BASE_URL =
  process.env.API_BASE_URL ?? "https://pbmejzmuo4.execute-api.ap-northeast-1.amazonaws.com";

export async function fetchMenu(): Promise<MenuResponse> {
  const res = await fetch(`${API_BASE_URL}/menu`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`failed to fetch menu: ${res.status}`);
  }
  return res.json();
}
