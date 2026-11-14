import { apiFetch } from './client';

/**
 * Where a purchased item physically is, decided by the backend:
 * - in_warehouse: on our shelf — says NOTHING about who moves it next, see
 *   DeliveryMethod
 * - incoming: ordered from the brewery, expected around estimated_delivery_date
 *   (on its way to US, not to the customer)
 * - shipped: handed to the courier
 * - partial: partially shipped
 * - cancelled: the order was cancelled or restocked — nothing is owed
 * - handled: the order is finished (archived) but this line was never
 *   fulfilled in Shopify — collected at the counter, or shipped under a
 *   merged order. Done, by a route we cannot name.
 * - unknown: could not determine — render as the neutral "not yet shipped" look
 *
 * cancelled/handled are ORDER outcomes pushed down onto the lines: Shopify
 * leaves per-line fulfillment_status null forever on an order we finished
 * without fulfilling it, which used to render as "Ligt bij ons klaar" for
 * all eternity.
 */
export type ItemState =
  | 'shipped'
  | 'partial'
  | 'in_warehouse'
  | 'incoming'
  | 'cancelled'
  | 'handled'
  | 'unknown';

/**
 * How the order leaves us, derived server-side from the Shopify shipping line:
 * - pickup: the customer collects it in the shop
 * - shipping: we send it with a courier
 * - unknown: no shipping line at all (POS/in-store sales) — the app must
 *   promise neither, so these render the neutral in-stock wording
 */
export type DeliveryMethod = 'pickup' | 'shipping' | 'unknown';

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
  /** Shopify shipping-line title, e.g. 'House of Beers' or '0-20 KG'; '' when none. */
  shipping_method?: string;
  /**
   * Optional on purpose: backend and PWA deploy separately, so a PWA build
   * that ships first talks to an API that does not send this field yet.
   * Undefined must behave exactly like 'unknown' — never promise pickup.
   */
  delivery_method?: DeliveryMethod;
  /**
   * Set when the order was cancelled. The line states already say
   * `cancelled`; this is what lets the card explain it. Optional for the
   * same deploy-order reason as delivery_method.
   */
  cancelled_at?: string | null;
  /**
   * Order name this one was merged into ('HoB8556'), '' when it wasn't.
   * The real answer to "where is my beer?" for a merged-away order: it
   * went out under that number.
   */
  merged_into?: string | null;
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
