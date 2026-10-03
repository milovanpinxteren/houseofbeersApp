// Single client-side source of truth for message reactions and the
// composer's quick-emoji set. ALLOWED_REACTIONS must stay in sync with the
// backend's allowed set — the server rejects anything else.

export const ALLOWED_REACTIONS = ['🍺', '🔥', '😂', '❤️', '👍', '🤯'];

// Curated composer palette (~60), grouped for the inline picker strip.
// i18n label keys live under community.emoji*.
export const COMPOSER_EMOJI: { labelKey: string; emoji: string[] }[] = [
  {
    labelKey: 'community.emojiBeer',
    emoji: ['🍺', '🍻', '🥂', '🍷', '🥃', '🍾', '🫗', '🍹', '🧉', '☕', '🥤', '🍕'],
  },
  {
    labelKey: 'community.emojiSmileys',
    emoji: [
      '😀', '😂', '🤣', '😅', '😊', '😍', '🤩', '😎', '🤤', '🥳',
      '😮', '🤯', '🙃', '😏', '🫠', '😭', '😤', '🥴', '🤔', '🫡',
    ],
  },
  {
    labelKey: 'community.emojiGestures',
    emoji: [
      '👍', '👎', '👌', '✌️', '🤘', '🤙', '👏', '🙌', '🙏', '💪',
      '🫶', '🤝', '👀', '🧠', '🦵', '🖐️',
    ],
  },
  {
    labelKey: 'community.emojiMisc',
    emoji: [
      '🔥', '❤️', '🧡', '💛', '💯', '🎉', '🎊', '🏆', '⭐', '⚡',
      '🚀', '🎯',
    ],
  },
];

// Jumbomoji: a short message that is nothing but emoji renders large and
// bubble-less. Hermes and modern browsers both support Unicode property
// escapes, but guard construction anyway so an exotic engine degrades to
// "never jumbo" instead of crashing at import time.
let emojiOnlyRe: RegExp | null = null;
try {
  emojiOnlyRe = new RegExp(
    '^(?:\\p{Extended_Pictographic}(?:\\uFE0F|\\p{Emoji_Modifier})*' +
    '(?:\\u200D\\p{Extended_Pictographic}(?:\\uFE0F|\\p{Emoji_Modifier})*)*' +
    '|\\s)+$',
    'u'
  );
} catch {
  emojiOnlyRe = null;
}

function graphemeCount(text: string): number {
  try {
    const Segmenter = (Intl as unknown as {
      Segmenter?: new (locale?: string, opts?: { granularity: string }) => {
        segment: (s: string) => Iterable<unknown>;
      };
    }).Segmenter;
    if (Segmenter) {
      return [...new Segmenter(undefined, { granularity: 'grapheme' }).segment(text)].length;
    }
  } catch {}
  // Rough fallback: code points (ZWJ sequences over-count, which only makes
  // us more conservative about going jumbo).
  return [...text].length;
}

export function isJumbomoji(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed || !emojiOnlyRe) return false;
  if (!emojiOnlyRe.test(trimmed)) return false;
  return graphemeCount(trimmed.replace(/\s/g, '')) <= 3;
}
