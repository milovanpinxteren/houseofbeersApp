import { apiFetch } from './client';

export interface LineItem {
  id: number;
  title: string;
  variant_title: string | null;
  quantity: number;
  price: string;
  sku: string | null;
  product_id: number | null;
  estimated_delivery_date: string | null;
}

export interface Order {
  id: number;
  order_number: number;
  name: string;
  created_at: string;
  financial_status: string;
  fulfillment_status: string | null;
  total_price: string;
  currency: string;
  line_items: LineItem[];
}

interface OrdersResponse {
  orders: Order[];
}

export async function getOrders(): Promise<Order[]> {
  const response = await apiFetch<OrdersResponse>('/users/me/orders/');
  return response.orders;
}
