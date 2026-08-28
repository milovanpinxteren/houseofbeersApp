import { apiFetch } from './client';

// Types — shapes are FROZEN per the campaign contract; do not rename fields.

export type RaffleStatus = 'open' | 'drawn';

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
