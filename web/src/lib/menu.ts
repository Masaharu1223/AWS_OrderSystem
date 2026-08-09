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

import { apiFetch } from "./api";

export async function fetchMenu(): Promise<MenuResponse> {
  return apiFetch<MenuResponse>("/menu");
}
