/**
 * Small fuzzy text matcher, tuned for beer names.
 *
 * Product titles here are long, multi-word and full of diacritics
 * ("Brouwerij de Molen Balcones Edition 2024 Imperial Doppelbock - 33 CL"),
 * so the useful behaviours are:
 *   - accent-insensitive  ("kwak" matches "Pauwel Kwäk")
 *   - order-independent   ("molen bock" matches the title above)
 *   - typo-tolerant       ("doppelbok" still matches "Doppelbock")
 *
 * Every query token must match somewhere (AND, not OR), which keeps results
 * tight as the user keeps typing.
 */

/** Lowercase and strip diacritics so "Kwäk" and "kwak" compare equal. */
export function normalize(value: string): string {
  return value
    .toLowerCase()
    .normalize('NFD')
    // Combining marks left behind by NFD.
    .replace(/[̀-ͯ]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function tokenize(query: string): string[] {
  return normalize(query).split(' ').filter(Boolean);
}

/**
 * Levenshtein distance, abandoned as soon as it exceeds `max`.
 * Bounded so a long title never costs a full DP pass.
 */
function boundedEditDistance(a: string, b: string, max: number): number {
  if (a === b) return 0;
  if (Math.abs(a.length - b.length) > max) return max + 1;

  let prev = new Array(b.length + 1);
  let curr = new Array(b.length + 1);
  for (let j = 0; j <= b.length; j++) prev[j] = j;

  for (let i = 1; i <= a.length; i++) {
    curr[0] = i;
    let rowBest = curr[0];
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      curr[j] = Math.min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost);
      if (curr[j] < rowBest) rowBest = curr[j];
    }
    if (rowBest > max) return max + 1;
    const tmp = prev;
    prev = curr;
    curr = tmp;
  }
  return prev[b.length];
}

/** Typos allowed for a token — none for very short ones, where they'd cause noise. */
function allowedTypos(token: string): number {
  if (token.length >= 7) return 2;
  if (token.length >= 4) return 1;
  return 0;
}

/**
 * Score one token against pre-normalized text.
 * Returns 0 when the token does not match at all.
 */
function scoreToken(token: string, textNorm: string, words: string[]): number {
  const index = textNorm.indexOf(token);
  if (index === 0) return 100;
  if (index > 0) {
    // Matching the start of a word beats matching mid-word.
    return textNorm[index - 1] === ' ' ? 90 : 60;
  }

  // No substring hit — allow a near-miss against any single word.
  const budget = allowedTypos(token);
  if (budget === 0) return 0;

  let best = 0;
  for (const word of words) {
    if (Math.abs(word.length - token.length) > budget) continue;
    const distance = boundedEditDistance(token, word, budget);
    if (distance <= budget) {
      const score = 45 - distance * 10;
      if (score > best) best = score;
    }
  }
  return best;
}

/**
 * Match all tokens against text. Returns null when any token fails,
 * otherwise a score where higher is a better match.
 */
export function fuzzyScore(tokens: string[], textNorm: string): number | null {
  if (tokens.length === 0) return 0;
  if (!textNorm) return null;

  const words = textNorm.split(' ');
  let total = 0;
  for (const token of tokens) {
    const score = scoreToken(token, textNorm, words);
    if (score === 0) return null;
    total += score;
  }
  return total;
}

export interface HighlightRange {
  start: number;
  end: number;
}

/**
 * Ranges to highlight in the ORIGINAL text.
 *
 * Only literal substring hits are highlighted — a typo-tolerant match has no
 * exact span to underline, and guessing one looks like a rendering bug.
 * Indices line up with the original string because normalize() is
 * length-preserving for the characters involved (NFD marks are removed, and
 * whitespace is only collapsed, which we account for by matching on a
 * per-character basis).
 */
export function highlightRanges(tokens: string[], text: string): HighlightRange[] {
  if (!tokens.length || !text) return [];

  // Length-preserving normalization so indices map back to `text` exactly.
  const norm = text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '');

  // NFD can expand a character into base + mark; if the length changed, the
  // index mapping is no longer 1:1, so skip highlighting rather than misplace it.
  if (norm.length !== text.length) return [];

  const ranges: HighlightRange[] = [];
  for (const token of tokens) {
    let from = 0;
    for (;;) {
      const at = norm.indexOf(token, from);
      if (at === -1) break;
      ranges.push({ start: at, end: at + token.length });
      from = at + token.length;
    }
  }

  if (ranges.length <= 1) return ranges;

  // Merge overlaps so nested tokens don't double-wrap.
  ranges.sort((a, b) => a.start - b.start);
  const merged: HighlightRange[] = [ranges[0]];
  for (let i = 1; i < ranges.length; i++) {
    const last = merged[merged.length - 1];
    if (ranges[i].start <= last.end) {
      last.end = Math.max(last.end, ranges[i].end);
    } else {
      merged.push(ranges[i]);
    }
  }
  return merged;
}
