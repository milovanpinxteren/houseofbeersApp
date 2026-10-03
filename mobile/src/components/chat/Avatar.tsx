import { StyleSheet, Text, View, ViewStyle, StyleProp } from 'react-native';
import { colors, fonts } from '../../theme/colors';

const SIZES = { xs: 22, sm: 30, md: 40, lg: 48 } as const;

interface AvatarProps {
  /** Display name — used for the monogram (and the hue when no userId). */
  name?: string;
  /** Stable id driving the deterministic hue; falls back to a name hash. */
  userId?: number;
  size?: keyof typeof SIZES | number;
  style?: StyleProp<ViewStyle>;
}

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  const first = [...parts[0]][0] ?? '?';
  const second = parts.length > 1 ? [...parts[parts.length - 1]][0] ?? '' : '';
  return (first + second).toUpperCase();
}

/**
 * Monogram avatar: two-letter initials on a deterministic muted hue, so every
 * member is visually distinct without any backend image support. Saturation
 * and lightness are kept low to sit inside the warm dark palette.
 */
export function Avatar({ name = '', userId, size = 'md', style }: AvatarProps) {
  const px = typeof size === 'number' ? size : SIZES[size];
  const seed = userId ?? hashString(name || '?');
  // Golden-angle spacing spreads consecutive ids across the wheel.
  const hue = Math.round((seed * 137.508) % 360);
  const bg = `hsl(${hue}, 26%, 24%)`;
  const fg = `hsl(${hue}, 42%, 78%)`;

  return (
    <View
      style={[
        styles.base,
        { width: px, height: px, borderRadius: px / 2, backgroundColor: bg },
        style,
      ]}
    >
      <Text
        style={[styles.label, { color: fg, fontSize: Math.round(px * 0.4) }]}
        numberOfLines={1}
      >
        {initialsOf(name)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  base: {
    justifyContent: 'center',
    alignItems: 'center',
    overflow: 'hidden',
  },
  label: {
    fontFamily: fonts.heading,
    letterSpacing: 0.5,
    color: colors.text,
  },
});
