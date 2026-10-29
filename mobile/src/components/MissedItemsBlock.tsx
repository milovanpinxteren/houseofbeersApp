import { useState } from 'react';
import { Pressable, StyleProp, StyleSheet, Text, View, ViewStyle } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { t } from '../i18n';
import { colors, spacing, borderRadius } from '../theme/colors';
import { MissedLine, MissedSale } from '../api/orders';

/**
 * "You missed these in the sale" — a calm explanation, never an error.
 * Rendered inside the draft/order card the miss belongs to, or standalone.
 *
 * Collapsible: the header line (with a count) is always visible and toggles
 * the details, so the pay card stays compact while the answer to "why is this
 * beer not in my order?" remains one tap away. Collapsed by default.
 *
 * Staleness guard: the missed snapshot can lag the live lines by a sync, so a
 * FULL miss whose product is present among the live items of the card it's
 * attached to is shown as "delivered after all ✓" instead of as a miss.
 * Partial misses are never suppressed — they describe quantities, which a
 * product-id match can't verify.
 */
/** A full miss whose product is among the live lines was delivered after all. */
export function isDeliveredAfterAll(
  line: MissedLine,
  fulfilledProductIds: Set<number>
): boolean {
  return (
    line.received === 0 &&
    line.product_id !== null &&
    fulfilledProductIds.has(line.product_id)
  );
}

/** Lines that still represent an actual miss (not delivered after all). */
export function countRealMisses(
  missed: MissedSale,
  fulfilledProductIds: Set<number>
): number {
  return missed.lines.filter(
    (line) => !isDeliveredAfterAll(line, fulfilledProductIds)
  ).length;
}

function reasonText(reason: MissedLine['reason']): string {
  switch (reason) {
    case 'out_of_stock':
      return t('orders.missedReasonOutOfStock');
    case 'max_per_customer':
      return t('orders.missedReasonMaxPerCustomer');
    default:
      return t('orders.missedReasonUnavailable');
  }
}

/**
 * The bare missed lines, without any header or background — shared between
 * the per-card MissedItemsBlock and the consolidated MissedSalesSection, so
 * the staleness treatment and copy can never drift between the two.
 */
export function MissedLines({
  missed,
  fulfilledProductIds,
}: {
  missed: MissedSale;
  fulfilledProductIds: Set<number>;
}) {
  return (
    <>
      {missed.lines.map((line, index) => {
        if (isDeliveredAfterAll(line, fulfilledProductIds)) {
          return (
            <View key={index} style={styles.lineRow}>
              <Ionicons name="checkmark-circle" size={13} color={colors.success} />
              <Text style={styles.lineText} numberOfLines={2}>
                {`${line.requested}× ${line.title}`}
                <Text style={styles.deliveredText}>
                  {'  '}
                  {t('orders.missedDeliveredAfterAll')}
                </Text>
              </Text>
            </View>
          );
        }
        const text =
          line.received === 0
            ? `${line.requested}× ${line.title}`
            : t('orders.missedPartial', {
                title: line.title,
                requested: line.requested,
                received: line.received,
              });
        return (
          <View key={index} style={styles.line}>
            <Text style={styles.lineText} numberOfLines={2}>
              {text}
            </Text>
            <Text style={styles.reasonText}>{reasonText(line.reason)}</Text>
          </View>
        );
      })}
    </>
  );
}

export function MissedItemsBlock({
  missed,
  fulfilledProductIds,
  language,
  style,
}: {
  missed: MissedSale;
  /** Product ids of the live line items this block is checked against. */
  fulfilledProductIds: Set<number>;
  language: string;
  style?: StyleProp<ViewStyle>;
}) {
  // `language` keeps the block re-rendering on a language switch; all copy
  // goes through t(), which reads the active locale globally.
  void language;

  const [expanded, setExpanded] = useState(false);

  if (missed.lines.length === 0) return null;

  const realMissCount = countRealMisses(missed, fulfilledProductIds);
  // All lines delivered after all → the header itself is the reassurance.
  const allDelivered = realMissCount === 0;

  return (
    <View style={[styles.block, style]}>
      <Pressable
        onPress={() => setExpanded((open) => !open)}
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
        style={({ pressed }) => [styles.headingRow, pressed && { opacity: 0.7 }]}
      >
        <Ionicons
          name={allDelivered ? 'checkmark-circle' : 'information-circle-outline'}
          size={14}
          color={allDelivered ? colors.success : colors.warning}
        />
        <Text style={[styles.heading, allDelivered && styles.headingDelivered]}>
          {allDelivered
            ? t('orders.missedAllDelivered')
            : `${t('orders.missedTitle')} (${realMissCount})`}
        </Text>
        <Ionicons
          name={expanded ? 'chevron-up' : 'chevron-down'}
          size={13}
          color={colors.textMuted}
        />
      </Pressable>

      {expanded && (
        <MissedLines missed={missed} fulfilledProductIds={fulfilledProductIds} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  block: {
    backgroundColor: colors.warning + '0f',
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm + spacing.xs,
    paddingVertical: spacing.sm + spacing.xs,
    gap: spacing.sm,
  },
  headingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
  },
  heading: {
    flex: 1,
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 0.3,
    color: colors.warning,
  },
  headingDelivered: {
    color: colors.success,
  },
  line: {
    gap: 1,
  },
  lineRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 5,
  },
  lineText: {
    flexShrink: 1,
    fontSize: 13,
    lineHeight: 18,
    color: colors.text,
  },
  deliveredText: {
    fontSize: 12,
    color: colors.success,
  },
  reasonText: {
    fontSize: 12,
    lineHeight: 16,
    color: colors.textMuted,
  },
});
