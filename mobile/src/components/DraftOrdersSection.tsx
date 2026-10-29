import { useState } from 'react';
import {
  Linking,
  Pressable,
  StyleProp,
  StyleSheet,
  Text,
  View,
  ViewStyle,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { t } from '../i18n';
import { colors, spacing, borderRadius, fonts } from '../theme/colors';
import { DraftOrder, MissedSale } from '../api/orders';
import { ItemStateBadge } from './ItemStateBadge';
import { MissedItemsBlock } from './MissedItemsBlock';

/**
 * "Nog te betalen" — the customer's unpaid draft orders, pinned above the
 * order history. This is the money moment of the screen: each draft gets a
 * warm accent card with a prominent pay button opening the live invoice URL.
 * OPEN and INVOICE_SENT read as the same thing; the distinction is internal.
 *
 * The section header is a toggle (expanded by default — unpaid drafts should
 * confront, not hide); collapsed it keeps the count and the summed total
 * visible so the obligation never disappears entirely.
 */
export function DraftOrdersSection({
  drafts,
  missed,
  language,
  formatPrice,
  formatDate,
  style,
}: {
  drafts: DraftOrder[];
  /** All missed-sale entries; the ones pointing at a draft render inside it. */
  missed: MissedSale[];
  language: string;
  formatPrice: (price: string, currency: string) => string;
  formatDate: (iso: string) => string;
  style?: StyleProp<ViewStyle>;
}) {
  const [expanded, setExpanded] = useState(true);

  if (drafts.length === 0) return null;

  function openInvoice(url: string) {
    Linking.openURL(url).catch((err) =>
      console.log('[Drafts] Failed to open invoice:', err)
    );
  }

  const totalDue = drafts.reduce(
    (sum, draft) => sum + (parseFloat(draft.total_price) || 0),
    0
  );

  return (
    <View style={style}>
      <Pressable
        onPress={() => setExpanded((open) => !open)}
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        hitSlop={{ top: 6, bottom: 6 }}
        style={({ pressed }) => [styles.sectionHeader, pressed && { opacity: 0.7 }]}
      >
        <Text style={styles.sectionLabel}>
          {t('orders.draftsTitle')} ({drafts.length})
        </Text>
        {!expanded && (
          <Text style={styles.sectionTotal}>
            {formatPrice(String(totalDue), drafts[0].currency)}
          </Text>
        )}
        <Ionicons
          name={expanded ? 'chevron-up' : 'chevron-down'}
          size={14}
          color={colors.textMuted}
        />
      </Pressable>
      {expanded && drafts.map((draft) => {
        const missedEntry = missed.find((m) => m.draft_order_id === draft.id);
        // Staleness guard for the missed block: products already among this
        // draft's live lines were delivered after all.
        const liveProductIds = new Set(
          draft.line_items
            .map((item) => item.product_id)
            .filter((id): id is number => id !== null)
        );

        return (
          <View key={draft.id} style={styles.draftCard}>
            <View style={styles.header}>
              <View style={styles.headerInfo}>
                <Text style={styles.draftName}>{draft.name}</Text>
                <Text style={styles.draftDate}>{formatDate(draft.created_at)}</Text>
              </View>
              <View style={styles.headerRight}>
                <Text style={styles.total}>
                  {formatPrice(draft.total_price, draft.currency)}
                </Text>
              </View>
            </View>

            <View style={styles.divider} />

            {draft.line_items.map((item, index) => (
              <View
                key={index}
                style={[styles.lineItem, index === 0 && styles.lineItemFirst]}
              >
                <View style={styles.lineItemInfo}>
                  <Text style={styles.lineItemTitle}>
                    {item.quantity > 1 ? `${item.quantity}× ` : ''}
                    {item.display_title}
                  </Text>
                  <ItemStateBadge
                    state={item.state}
                    eta={item.estimated_delivery_date}
                    language={language}
                  />
                </View>
                <View style={styles.lineItemRight}>
                  <Text style={styles.lineItemPrice}>
                    {formatPrice(item.price, draft.currency)}
                  </Text>
                </View>
              </View>
            ))}

            {missedEntry && (
              <>
                <View style={styles.divider} />
                <MissedItemsBlock
                  missed={missedEntry}
                  fulfilledProductIds={liveProductIds}
                  language={language}
                  style={styles.missedBlock}
                />
              </>
            )}

            <Pressable
              onPress={() => openInvoice(draft.invoice_url)}
              accessibilityRole="button"
              style={({ pressed }) => [
                styles.payButton,
                pressed && { opacity: 0.85, transform: [{ scale: 0.99 }] },
              ]}
            >
              <Text style={styles.payButtonText}>{t('orders.payNow')}</Text>
            </Pressable>
          </View>
        );
      })}
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
  sectionTotal: {
    fontFamily: fonts.heading,
    fontSize: 14,
    letterSpacing: 0.4,
    color: colors.primary,
  },
  draftCard: {
    backgroundColor: colors.surfaceHigh,
    borderRadius: borderRadius.lg,
    borderLeftWidth: 3,
    borderLeftColor: colors.warning,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: spacing.md,
  },
  headerInfo: {
    flex: 1,
  },
  draftName: {
    fontFamily: fonts.heading,
    fontSize: 18,
    letterSpacing: 0.5,
    color: colors.text,
  },
  draftDate: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
  headerRight: {
    alignItems: 'flex-end',
  },
  total: {
    fontFamily: fonts.heading,
    fontSize: 18,
    letterSpacing: 0.4,
    color: colors.primary,
  },
  divider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: colors.borderStrong,
    marginTop: spacing.sm,
  },
  lineItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: spacing.sm + spacing.xs,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  lineItemFirst: {
    borderTopWidth: 0,
  },
  lineItemInfo: {
    flex: 1,
    marginRight: spacing.md,
  },
  lineItemTitle: {
    fontSize: 14,
    lineHeight: 19,
    color: colors.text,
  },
  lineItemRight: {
    alignItems: 'flex-end',
  },
  lineItemPrice: {
    fontFamily: fonts.heading,
    fontSize: 14,
    letterSpacing: 0.3,
    color: colors.text,
    marginTop: 2,
  },
  missedBlock: {
    marginTop: spacing.sm + spacing.xs,
  },
  payButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingVertical: 12,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: spacing.sm + spacing.xs,
  },
  payButtonText: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    color: colors.background,
  },
});
