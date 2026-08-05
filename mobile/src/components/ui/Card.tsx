import { ReactNode } from 'react';
import { Pressable, StyleSheet, View, ViewStyle, StyleProp } from 'react-native';
import { colors, spacing, borderRadius } from '../../theme/colors';

interface CardProps {
  children: ReactNode;
  variant?: 'default' | 'elevated' | 'inset' | 'accent';
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
  padded?: boolean;
}

/**
 * Surface container. Elevation is expressed through background contrast
 * steps, not borders — reserve borders for the 'accent' variant.
 */
export function Card({ children, variant = 'default', onPress, style, padded = true }: CardProps) {
  const base = [
    styles.card,
    variant === 'elevated' && styles.elevated,
    variant === 'inset' && styles.inset,
    variant === 'accent' && styles.accent,
    padded && styles.padded,
    style,
  ];

  if (onPress) {
    return (
      <Pressable
        onPress={onPress}
        style={({ pressed }) => [
          ...base,
          pressed && { opacity: 0.85, transform: [{ scale: 0.99 }] },
        ]}
      >
        {children}
      </Pressable>
    );
  }
  return <View style={base}>{children}</View>;
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    overflow: 'hidden',
  },
  padded: {
    padding: spacing.md,
  },
  elevated: {
    backgroundColor: colors.surfaceHigh,
  },
  inset: {
    backgroundColor: colors.surfaceLow,
  },
  accent: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
});
