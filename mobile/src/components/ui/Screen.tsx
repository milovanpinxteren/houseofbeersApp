import { ReactNode } from 'react';
import { RefreshControl, ScrollView, StyleSheet, View } from 'react-native';
import { colors, spacing } from '../../theme/colors';
import { ContentColumn } from './ContentColumn';

interface ScreenProps {
  children: ReactNode;
  scroll?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  padded?: boolean;
  /**
   * Opt-in: cap content to a centered column on wide screens (PWA on
   * desktop/tablet). Inert on phones. Screens that don't pass it keep
   * their exact current layout.
   */
  maxContentWidth?: number;
}

/** Themed screen container with optional scroll + pull-to-refresh. */
export function Screen({
  children,
  scroll = true,
  refreshing,
  onRefresh,
  padded = true,
  maxContentWidth,
}: ScreenProps) {
  const content = maxContentWidth ? (
    <ContentColumn maxWidth={maxContentWidth}>{children}</ContentColumn>
  ) : (
    children
  );
  if (!scroll) {
    return <View style={[styles.container, padded && styles.padded]}>{content}</View>;
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
      {content}
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
