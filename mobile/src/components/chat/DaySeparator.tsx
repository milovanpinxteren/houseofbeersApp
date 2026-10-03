import { StyleSheet, Text, View } from 'react-native';
import { t, getCurrentLanguage } from '../../i18n';
import { colors, spacing, borderRadius, fonts } from '../../theme/colors';

interface DaySeparatorProps {
  /** ISO datetime of any message on that day. */
  date: string;
}

function labelFor(date: Date): string {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const thatDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.round((today.getTime() - thatDay.getTime()) / 86400000);
  if (diffDays === 0) return t('time.today');
  if (diffDays === 1) return t('time.yesterday');
  const locale = getCurrentLanguage() === 'nl' ? 'nl-NL' : 'en-US';
  const sameYear = date.getFullYear() === now.getFullYear();
  return date.toLocaleDateString(
    locale,
    sameYear
      ? { weekday: 'short', day: 'numeric', month: 'short' }
      : { day: 'numeric', month: 'short', year: 'numeric' }
  );
}

/** Centered date pill between chat messages of different days. */
export function DaySeparator({ date }: DaySeparatorProps) {
  return (
    <View style={styles.wrap}>
      <Text style={styles.label}>{labelFor(new Date(date))}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    marginVertical: spacing.sm,
  },
  label: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: colors.textMuted,
    backgroundColor: colors.surfaceHigh,
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
    borderRadius: borderRadius.pill,
    overflow: 'hidden',
  },
});
