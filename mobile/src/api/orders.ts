import { apiFetch } from './client';

/**
 * Where a purchased item physically is, decided by the backend:
 * - in_warehouse: at the shop, ready to go
 * - incoming: ordered from the brewery, expected around estimated_delivery_date
 * - shipped: handed to the courier
 * - partial: partially shipped
 * - unknown: could not determine — render as the neutral "not yet shipped" look
 */
export type ItemState = 'shipped' | 'partial' | 'in_warehouse' | 'incoming' | 'unknown';

export interface LineItem {
  id: number;
  title: string;
  /** Clean beer name for display; `title` keeps the raw Shopify title. */
  display_title: string;
  variant_title: string | null;
  quantity: number;
  price: string;
  sku: string | null;
  product_id: number | null;
  fulfillment_status: string | null;
  state: ItemState;
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

export interface DraftLineItem {
  title: string;
  display_title: string;
  variant_title: string | null;
  quantity: number;
  price: string;
  product_id: number | null;
  state: ItemState;
  estimated_delivery_date: string | null;
}

/** An unpaid draft order — the customer pays via its live invoice URL. */
export interface DraftOrder {
  id: string;
  name: string;
  status: 'OPEN' | 'INVOICE_SENT';
  created_at: string;
  invoice_url: string;
  total_price: string;
  currency: string;
  line_items: DraftLineItem[];
}

export interface MissedLine {
  product_id: number | null;
  title: string;
  requested: number;
  received: number;
  reason: 'out_of_stock' | 'max_per_customer' | 'unavailable';
}

/** Items the customer asked for in a sale but (partly) didn't get. */
export interface MissedSale {
  sale_id: number;
  sale_name: string;
  sale_date: string;
  draft_order_id: string | null;
  shopify_order_id: string | null;
  lines: MissedLine[];
}

export interface OrdersResponse {
  orders: Order[];
  drafts: DraftOrder[];
  missed: MissedSale[];
}

export async function getOrders(): Promise<OrdersResponse> {
  // Demo mode: EXPO_PUBLIC_MOCK_ORDERS serves a local fixture instead of the
  // API, for reviewing the orders screen without a backend. The flag is never
  // set in .env.production, and since EXPO_PUBLIC_* vars are inlined at build
  // time the dynamic import below is dead code (and tree-shaken) in real
  // builds.
  if (process.env.EXPO_PUBLIC_MOCK_ORDERS) {
    const { MOCK_ORDERS_RESPONSE } = await import('./mockOrders');
    return MOCK_ORDERS_RESPONSE;
  }
  return apiFetch<OrdersResponse>('/users/me/orders/');
}
