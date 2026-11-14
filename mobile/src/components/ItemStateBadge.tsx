import { StyleSheet, Text, View } from 'react-native';
import { t } from '../i18n';
import { colors } from '../theme/colors';
import { DeliveryMethod, ItemState } from '../api/orders';

/**
 * '2026-10-26' -> '26 okt' / 'Oct 26' — compact date for state badges and
 * roll-up lines. Noon avoids TZ edges; NEVER show the raw ISO string.
 */
export function formatShortDate(iso: string, language: string): string {
  const locale = language === 'nl' ? 'nl-NL' : 'en-US';
  return new Date(`${iso}T12:00:00`)
    .toLocaleDateString(locale, { day: 'numeric', month: 'short' })
    .replace('.', '');
}

export function stateColor(state: ItemState, unpaid = false): string {
  switch (state) {
    case 'shipped':
      return colors.success;
    case 'in_warehouse':
      // Unpaid draft lines are stock HELD for the customer, not an
      // obligation of ours that is done — neutral, never the success green.
      return unpaid ? colors.textMuted : colors.success;
    case 'partial':
    case 'incoming':
      return colors.warning;
    case 'cancelled':
    case 'handled':
      // Finished business. Muted, like the roll-up's shipped segment: it
      // must not read as something still owed to the customer, and a
      // cancelled merge is not an error worth painting red either.
      return colors.textMuted;
    default:
      // 'unknown' renders as the neutral "not yet shipped" look — it must
      // never promise warehouse presence.
      return colors.textMuted;
  }
}

/**
 * The in-warehouse wording depends on what happens NEXT, which the item state
 * cannot know: a shipping customer told "ready for pickup" reads it as "drive
 * to Uden". An absent/unknown delivery method keeps the neutral wording — it
 * promises neither leg.
 */
function inWarehouseLabel(
  deliveryMethod: DeliveryMethod | undefined,
  unpaid: boolean
): string {
  if (unpaid) return t('orders.stateReserved');
  switch (deliveryMethod) {
    case 'pickup':
      return t('orders.stateInWarehousePickup');
    case 'shipping':
      return t('orders.stateInWarehouseShipping');
    default:
      return t('orders.stateInWarehouse');
  }
}

function stateLabel(
  state: ItemState,
  eta: string | null,
  language: string,
  deliveryMethod: DeliveryMethod | undefined,
  unpaid: boolean
): string {
  switch (state) {
    case 'shipped':
      return t('orders.stateShipped');
    case 'partial':
      return t('orders.statePartial');
    case 'in_warehouse':
      return inWarehouseLabel(deliveryMethod, unpaid);
    case 'cancelled':
      return t('orders.stateCancelled');
    case 'handled':
      return t('orders.stateHandled');
    case 'incoming':
      return eta
        ? t('orders.stateIncoming', { date: formatShortDate(eta, language) })
        : t('orders.stateIncomingNoEta');
    default:
      return t('orders.stateUnknown');
  }
}

/**
 * The single per-line-item status badge: a small colored dot plus a short
 * label, shared between order cards and draft cards so the two never drift.
 *
 * `deliveryMethod` and `unpaid` are optional and default to the neutral
 * reading, so a call site that passes neither keeps the pre-existing
 * behaviour instead of guessing at a promise.
 */
export function ItemStateBadge({
  state,
  eta,
  language,
  deliveryMethod,
  unpaid = false,
}: {
  state: ItemState;
  eta: string | null;
  language: string;
  /** How the order leaves us; omit when it isn't known (never assume pickup). */
  deliveryMethod?: DeliveryMethod;
  /** True for unpaid draft-order lines: stock reserved, nothing promised. */
  unpaid?: boolean;
}) {
  const color = stateColor(state, unpaid);
  return (
    <View style={styles.badge}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={[styles.text, { color }]}>
        {stateLabel(state, eta, language, deliveryMethod, unpaid)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    marginTop: 4,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    marginRight: 5,
  },
  text: {
    fontSize: 11,
    fontWeight: '600',
  },
});
