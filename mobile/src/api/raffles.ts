import { apiFetch } from './client';

// Types — shapes are FROZEN per the campaign contract; do not rename fields.

export type RaffleStatus = 'open' | 'drawn';

/**
 * One prize tier of a multi-prize raffle (e.g. a shirt, a hoodie and a cap
 * drawn from the same entrant pool). A user still wins at most one tier.
 */
export interface RafflePrize {
  id: number;
  name: string;
  description: string;
  image_url: string;
  /** How many of this prize are available. */
  quantity: number;
  /** Display order, ascending. */
  ordering: number;
}

export interface Raffle {
  id: number;
  campaign_id: number;
  title: string;
  rule_sentence: string;
  prize_name: string;
  prize_description: string;
  prize_image_url: string;
  // null = manual draw, no scheduled time yet
  draw_at: string | null;
  status: RaffleStatus;
  entered: boolean;
  ticket_count: number;
  matched_products: string[];
  seen: boolean;
  result_seen: boolean;
  entrant_count: number;
  // Post-draw only (null while status is 'open'):
  entrant_first_names: string[] | null;
  winner_first_names: string[] | null;
  did_win: boolean | null;
  my_code: string | null;
  my_code_expires_at: string | null;
  // Storefront link that applies the prize code and puts the prize product in
  // the cart (prize products are normally unlisted in the webshop).
  my_code_cart_url: string | null;
  public_winner_names: string[] | null;
  // Multi-prize support. The backend and the PWA deploy separately, so these
  // are OPTIONAL: for every raffle created before the feature — and for any
  // backend that predates it — they are missing entirely. `prize_name` /
  // `prize_description` / `prize_image_url` above stay the headline; the tiers
  // sit underneath, they do not replace it.
  /** Prize tiers; absent or [] for a single-prize raffle. */
  prizes?: RafflePrize[] | null;
  /** The tier THIS user won; null pre-draw or when they didn't win. */
  my_prize_name?: string | null;
  /** Parallel to `winner_first_names`, same draw order; null pre-draw. */
  winner_prizes?: string[] | null;
}

export async function getRaffles(): Promise<{ raffles: Raffle[] }> {
  return apiFetch<{ raffles: Raffle[] }>('/loyalty/raffles/');
}

// The seen endpoints return 204 No Content; apiFetch always calls
// response.json(), which throws a SyntaxError on the empty body even though
// the request succeeded — treat that as success.
async function postNoContent(endpoint: string): Promise<void> {
  try {
    await apiFetch(endpoint, { method: 'POST' });
  } catch (err) {
    if (err instanceof SyntaxError) return;
    throw err;
  }
}

/** Marks the raffle card/detail as opened (pre-draw). No-op server-side without an entry. */
export async function markRaffleSeen(raffleId: number): Promise<void> {
  return postNoContent(`/loyalty/raffles/${raffleId}/seen/`);
}

/** Marks the draw reveal as watched (post-draw). */
export async function markRaffleResultSeen(raffleId: number): Promise<void> {
  return postNoContent(`/loyalty/raffles/${raffleId}/result-seen/`);
}
