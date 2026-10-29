import { useState } from 'react';
import { Pressable, StyleProp, StyleSheet, Text, View, ViewStyle } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { t } from '../i18n';
import { colors, spacing, borderRadius, fonts } from '../theme/colors';
import { MissedSale } from '../api/orders';
import { countRealMisses, MissedLines } from './MissedItemsBlock';

/**
 * ONE collapsible section for all missed-sale entries that attach to no
 * draft or order card (rejected-only customers, or sales whose draft is
 * gone). A card per sale did not scale — ten sales with misses would have
 * buried the order history under ten separate blocks — so this renders a
 * single header with the total count and, expanded, compact per-sale groups
 * inside one card. Collapsed by default: it is an explanation, not an
 * obligation (unlike the drafts section, which defaults open).
 */
export function MissedSalesSection({
  entries,
  fulfilledProductIds,
  language,
  formatDate,
  autoExpand,
  style,
}: {
  entries: MissedSale[];
  /** Live product ids from ALL orders/drafts, for the staleness guard. */
  fulfilledProductIds: Set<number>;
  language: string;
  formatDate: (iso: string) => string;
  /** Start expanded (a future "je hebt bieren gemist" push deep-links to
      /orders?missed=1 and should land on the open answer). */
  autoExpand?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  // `language` keeps the section re-rendering on a language switch.
  void language;

  const [expanded, setExpanded] = useState(autoExpand ?? false);

  const withLines = entries.filter((entry) => entry.lines.length > 0);
  if (withLines.length === 0) return null;

  const realTotal = withLines.reduce(
    (sum, entry) => sum + countRealMisses(entry, fulfilledProductIds),
    0
  );
  const allDelivered = realTotal === 0;

  return (
    <View style={style}>
      <Pressable
        onPress={() => setExpanded((open) => !open)}
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        hitSlop={{ top: 6, bottom: 6 }}
        style={({ pressed }) => [styles.sectionHeader, pressed && { opacity: 0.7 }]}
      >
        <Ionicons
          name={allDelivered ? 'checkmark-circle' : 'information-circle-outline'}
          size={14}
          color={allDelivered ? colors.success : colors.warning}
        />
        <Text style={styles.sectionLabel}>
          {allDelivered
            ? t('orders.missedAllDelivered')
            : `${t('orders.missedTitle')} (${realTotal})`}
        </Text>
        <Ionicons
          name={expanded ? 'chevron-up' : 'chevron-down'}
          size={14}
          color={colors.textMuted}
        />
      </Pressable>

      {expanded && (
        <View style={styles.card}>
          {withLines.map((entry, index) => (
            <View
              key={entry.sale_id}
              style={[styles.saleGroup, index === 0 && styles.saleGroupFirst]}
            >
              <View style={styles.saleHeader}>
                <Text style={styles.saleTitle}>
                  {t('orders.missedSaleHeader', { name: entry.sale_name })}
                </Text>
                <Text style={styles.saleDate}>
                  {/* Noon-anchored so the calendar day never shifts a timezone. */}
                  {formatDate(`${entry.sale_date}T12:00:00`)}
                </Text>
              </View>
              <MissedLines
                missed={entry}
                fulfilledProductIds={fulfilledProductIds}
              />
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  sectionLabel: {
    flex: 1,
    fontFamily: fonts.heading,
    fontSize: 13,
    letterSpacing: 1.6,
    textTransform: 'uppercase',
    color: colors.textMuted,
  },
  card: {
    backgroundColor: colors.warning + '0f',
    borderRadius: borderRadius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  saleGroup: {
    paddingVertical: spacing.sm + spacing.xs,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    gap: spacing.sm,
  },
  saleGroupFirst: {
    borderTopWidth: 0,
  },
  saleHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    gap: spacing.md,
  },
  saleTitle: {
    fontFamily: fonts.heading,
    fontSize: 13,
    letterSpacing: 0.5,
    color: colors.text,
  },
  saleDate: {
    fontSize: 11,
    color: colors.textMuted,
  },
});
