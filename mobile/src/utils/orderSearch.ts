/**
 * Fuzzy search over a customer's order history.
 *
 * Kept separate from the screen so the matching rules are testable and the
 * component stays presentational.
 */

import { Order, LineItem, ItemState } from '../api/orders';
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
    // display_title is what the card renders, so search matches what you see.
    itemHaystacks: order.line_items.map((item) =>
      normalize(
        [item.display_title, item.variant_title, item.sku].filter(Boolean).join(' ')
      )
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

/**
 * The single item-level filter dimension. The server decides each item's state;
 * 'unknown' is deliberately not offered as a chip (too rare) and matches only
 * 'all'.
 */
export type StateFilter = 'all' | ItemState;

export const ITEM_STATE_FILTERS: Exclude<StateFilter, 'all' | 'unknown'>[] = [
  'in_warehouse',
  'incoming',
  'shipped',
  'partial',
];

/**
 * Narrow matches down to items with the given state. Orders left without a
 * single matching item drop out, so every card on screen has something to show.
 * Runs after searchOrders, so search and filter compose.
 */
export function filterMatchesByState(
  matches: OrderMatch[],
  filter: StateFilter
): OrderMatch[] {
  if (filter === 'all') return matches;

  const results: OrderMatch[] = [];
  for (const match of matches) {
    const matchedItems = match.matchedItems.filter((item) => item.state === filter);
    if (matchedItems.length === 0) continue;
    // These items are now an explicit selection rather than the "show
    // everything" fallback an order-number match produces, so they count
    // towards the result summary.
    results.push({ ...match, matchedItems, orderLevelMatch: false });
  }
  return results;
}

/** Item counts per state, for the filter chip labels. */
export function countItemsByState(matches: OrderMatch[]): Record<ItemState, number> {
  const counts: Record<ItemState, number> = {
    shipped: 0,
    partial: 0,
    in_warehouse: 0,
    incoming: 0,
    unknown: 0,
  };
  for (const match of matches) {
    for (const item of match.matchedItems) counts[item.state] += 1;
  }
  return counts;
}

export interface OrderStateSummary {
  inWarehouse: number;
  incoming: number;
  shipped: number;
  partial: number;
  unknown: number;
  /** MAX estimated_delivery_date among incoming items — the box is complete
   *  at the last arrival. Null when no incoming item carries a date. */
  latestEta: string | null;
}

/** Per-order roll-up for the collapsed card's status line. */
export function orderStateSummary(
  items: Pick<LineItem, 'state' | 'estimated_delivery_date'>[]
): OrderStateSummary {
  const summary: OrderStateSummary = {
    inWarehouse: 0,
    incoming: 0,
    shipped: 0,
    partial: 0,
    unknown: 0,
    latestEta: null,
  };
  for (const item of items) {
    switch (item.state) {
      case 'in_warehouse':
        summary.inWarehouse += 1;
        break;
      case 'incoming':
        summary.incoming += 1;
        if (
          item.estimated_delivery_date &&
          (summary.latestEta === null || item.estimated_delivery_date > summary.latestEta)
        ) {
          summary.latestEta = item.estimated_delivery_date;
        }
        break;
      case 'shipped':
        summary.shipped += 1;
        break;
      case 'partial':
        summary.partial += 1;
        break;
      default:
        summary.unknown += 1;
    }
  }
  return summary;
}

/**
 * Period filter, encoded as a string so it can live in one state value:
 * 'all', '3m', or 'y:2026'. Unlike the state filter this is order-level — it
 * never touches which line items are shown.
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
