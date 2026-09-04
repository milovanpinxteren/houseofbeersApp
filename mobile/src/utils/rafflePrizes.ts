import { t } from '../i18n';
import { Raffle, RafflePrize } from '../api/raffles';

/**
 * Helpers for multi-prize ("prize tier") raffles.
 *
 * The backend deploys separately from the PWA, so `prizes` / `my_prize_name` /
 * `winner_prizes` are missing on every raffle created before the feature and on
 * any older backend. Everything here degrades to "single prize, as before" when
 * the fields are absent, null or empty — never assume presence.
 */

type PrizeSource = Pick<Raffle, 'prizes'>;

/** Valid tiers in display order. Empty for a single-prize (or legacy) raffle. */
export function sortedPrizes(raffle: PrizeSource): RafflePrize[] {
  const prizes = raffle.prizes;
  if (!Array.isArray(prizes)) return [];
  return prizes
    .filter((p) => p && typeof p.name === 'string' && p.name.trim().length > 0)
    .slice()
    .sort((a, b) => (a.ordering ?? 0) - (b.ordering ?? 0));
}

/** True only when the raffle really awards several different prizes. */
export function hasPrizeTiers(raffle: PrizeSource): boolean {
  return sortedPrizes(raffle).length > 1;
}

/** "Hoodie" or "2× Hoodie" when a tier has multiple copies. */
export function prizeLabel(prize: RafflePrize): string {
  const qty = typeof prize.quantity === 'number' ? prize.quantity : 1;
  return qty > 1 ? t('raffle.prizeQuantity', { count: qty, name: prize.name }) : prize.name;
}

export function prizeLabels(raffle: PrizeSource): string[] {
  return sortedPrizes(raffle).map(prizeLabel);
}

/** Total number of prizes handed out (sum of the tier quantities). */
export function prizeTotal(raffle: PrizeSource): number {
  return sortedPrizes(raffle).reduce((sum, p) => {
    const qty = typeof p.quantity === 'number' && p.quantity > 0 ? p.quantity : 1;
    return sum + qty;
  }, 0);
}

/** Compact one-liner for a card: at most `max` tiers, then "+N meer". */
export function prizeSummary(labels: string[], max = 3): string {
  const shown = labels.slice(0, max);
  const rest = labels.length - shown.length;
  const line = shown.join(' · ');
  return rest > 0 ? `${line} · ${t('raffle.morePrizes', { count: rest })}` : line;
}

/**
 * Pairs winner names with the prize each of them won, positionally against
 * `winner_prizes`. Falls back to the bare name whenever the prize is unknown,
 * so a partial or absent list still renders today's wording.
 */
export function winnersWithPrizes(
  names: string[],
  winnerPrizes?: string[] | null
): string[] {
  if (!Array.isArray(winnerPrizes) || winnerPrizes.length === 0) return names;
  return names.map((name, index) => {
    const prize = winnerPrizes[index];
    return prize ? t('raffle.winnerWithPrize', { name, prize }) : name;
  });
}
