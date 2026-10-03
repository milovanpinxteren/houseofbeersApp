import { Pressable, StyleSheet, Text, View } from 'react-native';
import { colors, borderRadius, fonts } from '../../theme/colors';
import { ALLOWED_REACTIONS } from './emoji';

interface ReactionBarProps {
  reactions: Record<string, number>;
  mine?: string[];
  onToggle?: (emoji: string) => void;
  align: 'left' | 'right';
}

/**
 * Count pills under a message bubble. Tapping a pill toggles that emoji
 * directly (no sheet). Renders nothing when there are no reactions, so the
 * common case costs no layout.
 */
export function ReactionBar({ reactions, mine = [], onToggle, align }: ReactionBarProps) {
  const entries = Object.entries(reactions).filter(([, count]) => count > 0);
  if (entries.length === 0) return null;

  // Stable order: the allowed set first, anything unexpected after.
  entries.sort(
    ([a], [b]) =>
      (ALLOWED_REACTIONS.indexOf(a) + 100 * +(ALLOWED_REACTIONS.indexOf(a) < 0)) -
      (ALLOWED_REACTIONS.indexOf(b) + 100 * +(ALLOWED_REACTIONS.indexOf(b) < 0))
  );

  return (
    <View style={[styles.row, align === 'right' ? styles.right : styles.left]}>
      {entries.map(([emoji, count]) => {
        const isMine = mine.includes(emoji);
        return (
          <Pressable
            key={emoji}
            onPress={onToggle ? () => onToggle(emoji) : undefined}
            disabled={!onToggle}
            hitSlop={4}
            style={({ pressed }) => [
              styles.pill,
              isMine && styles.pillMine,
              pressed && { opacity: 0.7 },
            ]}
          >
            <Text style={styles.emoji}>{emoji}</Text>
            <Text style={[styles.count, isMine && styles.countMine]}>{count}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
    // Tuck into the bubble's bottom corner.
    marginTop: -6,
    marginBottom: 2,
    zIndex: 1,
  },
  left: { alignSelf: 'flex-start', marginLeft: 6 },
  right: { alignSelf: 'flex-end', marginRight: 6 },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: colors.surfaceHigh,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.pill,
    paddingHorizontal: 7,
    paddingVertical: 2,
  },
  pillMine: {
    backgroundColor: colors.primary + '18',
    borderColor: colors.primary,
  },
  emoji: { fontSize: 12 },
  count: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 0.3,
    color: colors.textMuted,
  },
  countMine: { color: colors.primary },
});
