/**
 * Fuzzy search over a customer's order history.
 *
 * Kept separate from the screen so the matching rules are testable and the
 * component stays presentational.
 */

import { Order, LineItem } from '../api/orders';
import { normalize, fuzzyScore } from './fuzzySearch';

export interface SearchableOrder {
  order: Order;
  /** Pre-normalized haystack per line item, index-aligned with line_items. */
  itemHaystacks: string[];
  /** Order number / name / date / status, so "#1234" or "maart" finds an order. */
  orderHaystack: string;
}

export interface OrderMatch {
  order: Order;
  /** Items to display: the matching ones, or all when the order itself matched. */
  matchedItems: LineItem[];
  /** True when the order matched on its number/date rather than on any item. */
  orderLevelMatch: boolean;
  score: number;
}

/**
 * Normalizing every title on each keystroke would be wasteful, so callers
 * should build this once per orders payload and reuse it.
 */
export function buildOrderSearchIndex(
  orders: Order[],
  formatDate: (iso: string) => string
): SearchableOrder[] {
  return orders.map((order) => ({
    order,
    itemHaystacks: order.line_items.map((item) =>
      normalize([item.title, item.variant_title, item.sku].filter(Boolean).join(' '))
    ),
    orderHaystack: normalize(
      [order.name, String(order.order_number), formatDate(order.created_at), order.financial_status]
        .filter(Boolean)
        .join(' ')
    ),
  }));
}

/**
 * Filter and rank orders. With no tokens every order passes through unchanged,
 * so the screen can render the same list shape whether or not a search is active.
 */
export function searchOrders(index: SearchableOrder[], tokens: string[]): OrderMatch[] {
  if (tokens.length === 0) {
    return index.map((entry) => ({
      order: entry.order,
      matchedItems: entry.order.line_items,
      orderLevelMatch: false,
      score: 0,
    }));
  }

  const results: OrderMatch[] = [];

  for (const entry of index) {
    const orderScore = fuzzyScore(tokens, entry.orderHaystack);

    const matchedItems: LineItem[] = [];
    let itemScore = 0;
    entry.itemHaystacks.forEach((haystack, i) => {
      const score = fuzzyScore(tokens, haystack);
      if (score !== null) {
        matchedItems.push(entry.order.line_items[i]);
        if (score > itemScore) itemScore = score;
      }
    });

    if (orderScore === null && matchedItems.length === 0) continue;

    results.push({
      order: entry.order,
      // An order matched by its number shows everything; otherwise just the hits.
      matchedItems: matchedItems.length ? matchedItems : entry.order.line_items,
      orderLevelMatch: orderScore !== null && matchedItems.length === 0,
      score: Math.max(orderScore ?? 0, itemScore),
    });
  }

  // Best match first, then newest — ties are common with one-word queries.
  results.sort(
    (a, b) =>
      b.score - a.score ||
      new Date(b.order.created_at).getTime() - new Date(a.order.created_at).getTime()
  );
  return results;
}

/** Total line items shown as matches, for the result summary. */
export function countMatchedItems(matches: OrderMatch[]): number {
  return matches.reduce(
    (sum, m) => sum + (m.orderLevelMatch ? 0 : m.matchedItems.length),
    0
  );
}

/** The three buckets the shipping filter offers. */
export type ItemStatus = 'unfulfilled' | 'partial' | 'fulfilled';
export type ItemStatusFilter = ItemStatus | 'all';

export const ITEM_STATUSES: ItemStatus[] = ['unfulfilled', 'partial', 'fulfilled'];

/**
 * Shopify leaves `fulfillment_status` null until something ships; any status we
 * don't know reads as "not shipped yet" too, matching what the card renders.
 */
export function itemStatus(item: LineItem): ItemStatus {
  if (item.fulfillment_status === 'fulfilled') return 'fulfilled';
  if (item.fulfillment_status === 'partial') return 'partial';
  return 'unfulfilled';
}

/**
 * Narrow matches down to items with the given status. Orders left without a
 * single matching item drop out, so every card on screen has something to show.
 * Runs after searchOrders, so search and filter compose.
 */
export function filterMatchesByItemStatus(
  matches: OrderMatch[],
  filter: ItemStatusFilter
): OrderMatch[] {
  if (filter === 'all') return matches;

  const results: OrderMatch[] = [];
  for (const match of matches) {
    const matchedItems = match.matchedItems.filter((item) => itemStatus(item) === filter);
    if (matchedItems.length === 0) continue;
    // These items are now an explicit selection rather than the "show
    // everything" fallback an order-number match produces, so they count
    // towards the result summary.
    results.push({ ...match, matchedItems, orderLevelMatch: false });
  }
  return results;
}

/** Item counts per status, for the filter chip labels. */
export function countItemsByStatus(matches: OrderMatch[]): Record<ItemStatus, number> {
  const counts: Record<ItemStatus, number> = { unfulfilled: 0, partial: 0, fulfilled: 0 };
  for (const match of matches) {
    for (const item of match.matchedItems) counts[itemStatus(item)] += 1;
  }
  return counts;
}

/** Local calendar day as YYYY-MM-DD — comparable as a plain string. */
export function toDateKey(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

/** Expected-delivery buckets. Only two of them are offered as filters. */
export type EtaBucket = 'upcoming' | 'past' | 'none';
export type EtaFilter = 'all' | 'upcoming' | 'none';

/**
 * The date comes from a product metafield, so it is whatever the shop typed.
 * ISO dates compare lexicographically, which sidesteps timezone drift entirely;
 * anything else still goes through Date. A value we cannot read at all counts as
 * upcoming — the card shows it as an expected delivery, so the filter agrees.
 */
export function etaBucket(raw: string | null, today: string): EtaBucket {
  const value = raw?.trim();
  if (!value) return 'none';
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) {
    return value.slice(0, 10) < today ? 'past' : 'upcoming';
  }
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return 'upcoming';
  return toDateKey(new Date(parsed)) < today ? 'past' : 'upcoming';
}

/** Same item-level narrowing as the status filter, on the delivery date. */
export function filterMatchesByEta(
  matches: OrderMatch[],
  filter: EtaFilter,
  today: string
): OrderMatch[] {
  if (filter === 'all') return matches;

  const results: OrderMatch[] = [];
  for (const match of matches) {
    const matchedItems = match.matchedItems.filter(
      (item) => etaBucket(item.estimated_delivery_date, today) === filter
    );
    if (matchedItems.length === 0) continue;
    results.push({ ...match, matchedItems, orderLevelMatch: false });
  }
  return results;
}

/** Item counts per delivery bucket, for the filter chip labels. */
export function countItemsByEta(
  matches: OrderMatch[],
  today: string
): Record<EtaBucket, number> {
  const counts: Record<EtaBucket, number> = { upcoming: 0, past: 0, none: 0 };
  for (const match of matches) {
    for (const item of match.matchedItems) {
      counts[etaBucket(item.estimated_delivery_date, today)] += 1;
    }
  }
  return counts;
}

/**
 * Period filter, encoded as a string so it can live in one state value:
 * 'all', '3m', or 'y:2026'. Unlike the other two this is order-level — it never
 * touches which line items are shown.
 */
export const PERIOD_ALL = 'all';
export const PERIOD_3M = '3m';
export const periodForYear = (year: number) => `y:${year}`;

export function threeMonthsBefore(now: Date): Date {
  const cutoff = new Date(now);
  cutoff.setMonth(cutoff.getMonth() - 3);
  return cutoff;
}

export function filterMatchesByPeriod(
  matches: OrderMatch[],
  period: string,
  now: Date
): OrderMatch[] {
  if (period === PERIOD_ALL) return matches;

  if (period === PERIOD_3M) {
    const cutoff = threeMonthsBefore(now).getTime();
    return matches.filter((m) => new Date(m.order.created_at).getTime() >= cutoff);
  }

  const year = Number(period.slice(2));
  if (!year) return matches;
  return matches.filter((m) => new Date(m.order.created_at).getFullYear() === year);
}

/** Years present in the history, newest first — one chip each. */
export function orderYears(orders: Order[]): number[] {
  const years = new Set<number>();
  for (const order of orders) years.add(new Date(order.created_at).getFullYear());
  return [...years].sort((a, b) => b - a);
}
