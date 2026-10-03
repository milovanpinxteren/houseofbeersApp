import { ReactNode } from 'react';
import { StyleSheet, View, ViewStyle } from 'react-native';

interface ContentColumnProps {
  children: ReactNode;
  /** Cap for the content column on wide screens (default 720). */
  maxWidth?: number;
  style?: ViewStyle | ViewStyle[];
}

/**
 * Centered max-width column for wide screens (desktop/tablet PWA).
 * On phones the cap is wider than the window, so layout is untouched —
 * safe to wrap any screen without a breakpoint check.
 */
export function ContentColumn({ children, maxWidth = 720, style }: ContentColumnProps) {
  return <View style={[styles.column, { maxWidth }, style]}>{children}</View>;
}

const styles = StyleSheet.create({
  column: {
    flex: 1,
    width: '100%',
    alignSelf: 'center',
  },
});
