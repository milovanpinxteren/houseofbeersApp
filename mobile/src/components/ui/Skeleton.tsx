import { useEffect, useRef } from 'react';
import { Animated, StyleSheet, View, ViewStyle, StyleProp } from 'react-native';
import { colors, spacing, borderRadius } from '../../theme/colors';

interface SkeletonProps {
  width?: number | `${number}%`;
  height?: number;
  radius?: number;
  style?: StyleProp<ViewStyle>;
}

/** Pulsing placeholder block shown while content loads. */
export function Skeleton({ width = '100%', height = 16, radius = 6, style }: SkeletonProps) {
  const opacity = useRef(new Animated.Value(0.35)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.7, duration: 700, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.35, duration: 700, useNativeDriver: true }),
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [opacity]);

  return (
    <Animated.View
      style={[
        { width, height, borderRadius: radius, backgroundColor: colors.surfaceHigh, opacity },
        style,
      ]}
    />
  );
}

/** Standard card-shaped skeleton group for list screens. */
export function SkeletonCard() {
  return (
    <View style={styles.card}>
      <Skeleton width="45%" height={14} />
      <Skeleton width="80%" height={11} style={{ marginTop: spacing.sm }} />
      <Skeleton width="65%" height={11} style={{ marginTop: spacing.xs }} />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
});
