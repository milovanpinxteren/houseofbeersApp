import { StyleSheet, Text, View } from 'react-native';
import { t } from '../i18n';
import { colors } from '../theme/colors';
import { ItemState } from '../api/orders';

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

export function stateColor(state: ItemState): string {
  switch (state) {
    case 'shipped':
    case 'in_warehouse':
      return colors.success;
    case 'partial':
    case 'incoming':
      return colors.warning;
    default:
      // 'unknown' renders as the neutral "not yet shipped" look — it must
      // never promise warehouse presence.
      return colors.textMuted;
  }
}

function stateLabel(state: ItemState, eta: string | null, language: string): string {
  switch (state) {
    case 'shipped':
      return t('orders.stateShipped');
    case 'partial':
      return t('orders.statePartial');
    case 'in_warehouse':
      return t('orders.stateInWarehouse');
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
 */
export function ItemStateBadge({
  state,
  eta,
  language,
}: {
  state: ItemState;
  eta: string | null;
  language: string;
}) {
  const color = stateColor(state);
  return (
    <View style={styles.badge}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={[styles.text, { color }]}>{stateLabel(state, eta, language)}</Text>
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
