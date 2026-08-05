import { ReactNode } from 'react';
import { RefreshControl, ScrollView, StyleSheet, View } from 'react-native';
import { colors, spacing } from '../../theme/colors';

interface ScreenProps {
  children: ReactNode;
  scroll?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  padded?: boolean;
}

/** Themed screen container with optional scroll + pull-to-refresh. */
export function Screen({ children, scroll = true, refreshing, onRefresh, padded = true }: ScreenProps) {
  if (!scroll) {
    return <View style={[styles.container, padded && styles.padded]}>{children}</View>;
  }
  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={[padded && styles.padded, styles.grow]}
      refreshControl={
        onRefresh ? (
          <RefreshControl
            refreshing={!!refreshing}
            onRefresh={onRefresh}
            tintColor={colors.primary}
          />
        ) : undefined
      }
    >
      {children}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  grow: {
    flexGrow: 1,
    paddingBottom: spacing.xl,
  },
  padded: {
    paddingHorizontal: spacing.md,
  },
});
