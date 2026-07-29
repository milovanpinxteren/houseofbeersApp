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
