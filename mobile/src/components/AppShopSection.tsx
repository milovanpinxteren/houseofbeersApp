import { useState } from 'react';
import {
  Image,
  Linking,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { t } from '../i18n';
import { colors, spacing, borderRadius, fonts } from '../theme/colors';
import { SectionHeader } from './ui';
import { AppShopProduct, isAppShopMissed } from '../api/recommendations';
import { trackEvent } from '../api/analytics';

// The Ontdek rail is a teaser: the full page shows everything.
const RAIL_MAX_PRODUCTS = 6;

/**
 * "App exclusives" rail: leftover WhatsApp-sale beers sold only in the app.
 * Renders nothing when there are no products — the section simply does not
 * exist most of the time, by design.
 */
export function AppShopSection({
  products,
  onViewAll,
}: {
  products: AppShopProduct[];
  onViewAll?: () => void;
}) {
  const [selected, setSelected] = useState<AppShopProduct | null>(null);

  if (products.length === 0) {
    return null;
  }

  return (
    <>
      <SectionHeader
        title={t('discover.appShopTitle')}
        actionLabel={onViewAll ? t('discover.appShopViewAll') : undefined}
        onAction={onViewAll}
      />
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.railContent}
        style={styles.rail}
      >
        {products.slice(0, RAIL_MAX_PRODUCTS).map((product) => (
          <Pressable
            key={product.id}
            onPress={() => setSelected(product)}
            style={({ pressed }) => [
              styles.card,
              isAppShopMissed(product) && styles.cardMissed,
              pressed && { opacity: 0.85 },
            ]}
          >
            {product.image_url ? (
              <Image
                source={{ uri: product.image_url }}
                style={[styles.image, isAppShopMissed(product) && styles.imageMissed]}
                resizeMode="cover"
              />
            ) : (
              <View style={styles.imagePlaceholder}>
                <Ionicons name="beer-outline" size={32} color={colors.textMuted} />
              </View>
            )}
            {product.untappd_rating != null && (
              <View style={styles.ratingBadge}>
                <Ionicons name="star" size={10} color={colors.background} />
                <Text style={styles.ratingText}>
                  {product.untappd_rating.toFixed(2)}
                </Text>
              </View>
            )}
            <View style={styles.body}>
              <Text style={styles.title} numberOfLines={2}>
                {product.title}
              </Text>
              <View style={styles.priceRow}>
                <Text style={[styles.price, isAppShopMissed(product) && styles.priceMuted]}>
                  {isAppShopMissed(product) && product.sale_price != null && (
                    <Text style={styles.priceStruck}>
                      €{Number(product.sale_price).toFixed(2)}{'  '}
                    </Text>
                  )}
                  €{Number(product.price).toFixed(2)}
                </Text>
                <Text style={[styles.stock, isAppShopMissed(product) && styles.stockMissed]}>
                  {!isAppShopMissed(product)
                    ? t('discover.appShopStock', { count: product.inventory })
                    : t('discover.appShopMissed')}
                </Text>
              </View>
            </View>
          </Pressable>
        ))}
      </ScrollView>

      <AppShopDetailSheet product={selected} onClose={() => setSelected(null)} />
    </>
  );
}

/**
 * Product detail bottom sheet, shared between the Ontdek rail and the full
 * App-exclusief page. Pass `product = null` to hide it.
 */
export function AppShopDetailSheet({
  product,
  onClose,
}: {
  product: AppShopProduct | null;
  onClose: () => void;
}) {
  function order(selected: AppShopProduct) {
    if (!selected.cart_url) return;
    trackEvent('app_shop_checkout', { items: 1, total: selected.price, single: true });
    Linking.openURL(selected.cart_url).catch((err) =>
      console.log('[AppShop] Open cart error:', err)
    );
  }

  return (
    <Modal
      visible={product !== null}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <Pressable style={styles.modalOverlay} onPress={onClose}>
        <Pressable style={styles.sheet} onPress={() => {}}>
          <Pressable
            onPress={onClose}
            hitSlop={8}
            accessibilityLabel={t('common.cancel')}
            style={({ pressed }) => [styles.sheetClose, pressed && { opacity: 0.7 }]}
          >
            <Ionicons name="close" size={20} color={colors.text} />
          </Pressable>
          {product && (
            <ScrollView showsVerticalScrollIndicator={false}>
              <View style={styles.sheetHandle} />
              {product.image_url ? (
                <Image
                  source={{ uri: product.image_url }}
                  style={styles.sheetImage}
                  resizeMode="cover"
                />
              ) : null}
              <View style={styles.badgeRow}>
                <View style={styles.exclusiveBadge}>
                  <Ionicons name="sparkles" size={12} color={colors.primary} />
                  <Text style={styles.exclusiveText}>{t('discover.appShopBadge')}</Text>
                </View>
                {isAppShopMissed(product) && (
                  <View style={styles.missedBadge}>
                    <Ionicons name="time-outline" size={12} color={colors.textMuted} />
                    <Text style={styles.missedBadgeText}>{t('discover.appShopMissed')}</Text>
                  </View>
                )}
              </View>
              <Text style={styles.sheetTitle}>{product.title}</Text>

              <View style={styles.chipRow}>
                {!!product.style && <Chip label={product.style} />}
                {!!product.abv && (
                  <Chip label={product.abv.includes('%') ? product.abv : `${product.abv}%`} />
                )}
                {!!product.volume && <Chip label={product.volume} />}
                {!!product.country && <Chip label={product.country} />}
              </View>

              {product.untappd_rating != null && (
                <View style={styles.untappdRow}>
                  <Ionicons name="star" size={14} color={colors.primary} />
                  <Text style={styles.untappdText}>
                    {product.untappd_rating.toFixed(2)}
                    {product.untappd_checkins
                      ? `  ·  ${product.untappd_checkins.toLocaleString()} ${t('discover.appShopCheckins')}`
                      : ''}
                  </Text>
                </View>
              )}

              {!!product.description && (
                <Text style={styles.description}>{product.description}</Text>
              )}

              {!isAppShopMissed(product) ? (
                <>
                  <Pressable
                    onPress={() => order(product)}
                    style={({ pressed }) => [styles.orderBtn, pressed && { opacity: 0.85 }]}
                  >
                    <Text style={styles.orderBtnText}>
                      {t('discover.appShopOrder')} · €{Number(product.price).toFixed(2)}
                    </Text>
                  </Pressable>
                  <Text style={styles.stockNote}>
                    {t('discover.appShopStock', { count: product.inventory })}
                  </Text>
                </>
              ) : (
                <>
                  {/* Missed deal: show what the WhatsApp group and the app
                      window paid — the urgency for next time. */}
                  <View style={styles.missedPrices}>
                    {product.sale_price != null && (
                      <View style={styles.missedPriceRow}>
                        <Text style={styles.missedPriceLabel}>
                          {t('discover.appShopWaPrice')}
                        </Text>
                        <Text style={styles.missedPriceStruck}>
                          €{Number(product.sale_price).toFixed(2)}
                        </Text>
                      </View>
                    )}
                    <View style={styles.missedPriceRow}>
                      <Text style={styles.missedPriceLabel}>
                        {t('discover.appShopAppPrice')}
                      </Text>
                      <Text style={styles.missedPriceStruck}>
                        €{Number(product.price).toFixed(2)}
                      </Text>
                    </View>
                  </View>
                  <Text style={styles.missedInfo}>
                    {t('discover.appShopMissedInfo')}
                  </Text>
                </>
              )}
            </ScrollView>
          )}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function Chip({ label }: { label: string }) {
  return (
    <View style={styles.chip}>
      <Text style={styles.chipText}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  rail: {
    marginHorizontal: -spacing.md,
    marginBottom: spacing.sm,
  },
  railContent: {
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  card: {
    width: 150,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.primary + '33',
  },
  cardMissed: {
    borderColor: colors.border,
    opacity: 0.85,
  },
  image: {
    width: '100%',
    aspectRatio: 1,
    backgroundColor: colors.surfaceLow,
  },
  imageMissed: {
    opacity: 0.55,
  },
  imagePlaceholder: {
    width: '100%',
    aspectRatio: 1,
    backgroundColor: colors.surfaceLow,
    alignItems: 'center',
    justifyContent: 'center',
  },
  ratingBadge: {
    position: 'absolute',
    top: 8,
    left: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingHorizontal: 7,
    paddingVertical: 3,
  },
  ratingText: {
    fontFamily: fonts.heading,
    fontSize: 11,
    color: colors.background,
  },
  body: {
    padding: spacing.sm,
  },
  title: {
    fontFamily: fonts.heading,
    fontSize: 13,
    lineHeight: 17,
    letterSpacing: 0.3,
    color: colors.text,
    minHeight: 34,
  },
  priceRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    marginTop: 4,
  },
  price: {
    fontFamily: fonts.heading,
    fontSize: 14,
    color: colors.primary,
  },
  priceMuted: {
    color: colors.textMuted,
  },
  priceStruck: {
    textDecorationLine: 'line-through',
    color: colors.textMuted,
    fontSize: 12,
  },
  stock: {
    fontSize: 11,
    color: colors.textMuted,
  },
  stockMissed: {
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    fontSize: 10,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: '#000000AA',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: colors.background,
    borderTopLeftRadius: borderRadius.xl,
    borderTopRightRadius: borderRadius.xl,
    padding: spacing.md,
    maxHeight: '88%',
  },
  sheetHandle: {
    alignSelf: 'center',
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.surfaceLow,
    marginBottom: spacing.sm,
  },
  sheetClose: {
    position: 'absolute',
    top: spacing.sm,
    right: spacing.sm,
    zIndex: 1,
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: colors.surfaceHigh,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sheetImage: {
    width: '100%',
    aspectRatio: 1.2,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.surfaceLow,
    marginBottom: spacing.sm,
  },
  badgeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: spacing.xs,
  },
  exclusiveBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    alignSelf: 'flex-start',
    backgroundColor: colors.primary + '1A',
    borderRadius: 10,
    paddingHorizontal: 9,
    paddingVertical: 4,
  },
  missedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    alignSelf: 'flex-start',
    backgroundColor: colors.surfaceLow,
    borderRadius: 10,
    paddingHorizontal: 9,
    paddingVertical: 4,
  },
  missedBadgeText: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 0.5,
    color: colors.textMuted,
    textTransform: 'uppercase',
  },
  exclusiveText: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 0.5,
    color: colors.primary,
    textTransform: 'uppercase',
  },
  sheetTitle: {
    fontFamily: fonts.heading,
    fontSize: 20,
    letterSpacing: 0.4,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginBottom: spacing.sm,
  },
  chip: {
    backgroundColor: colors.surface,
    borderRadius: 10,
    paddingHorizontal: 9,
    paddingVertical: 4,
  },
  chipText: {
    fontSize: 12,
    color: colors.textMuted,
  },
  untappdRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: spacing.sm,
  },
  untappdText: {
    fontFamily: fonts.heading,
    fontSize: 13,
    color: colors.text,
  },
  description: {
    fontFamily: fonts.serif,
    fontSize: 14,
    lineHeight: 21,
    color: colors.textMuted,
    marginBottom: spacing.md,
  },
  orderBtn: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.lg,
    paddingVertical: 14,
    alignItems: 'center',
  },
  orderBtnText: {
    fontFamily: fonts.heading,
    fontSize: 16,
    letterSpacing: 0.5,
    color: colors.background,
  },
  stockNote: {
    textAlign: 'center',
    fontSize: 12,
    color: colors.textMuted,
    marginTop: spacing.xs,
    marginBottom: spacing.md,
  },
  missedPrices: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    gap: 8,
  },
  missedPriceRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
  },
  missedPriceLabel: {
    fontFamily: fonts.heading,
    fontSize: 13,
    letterSpacing: 0.4,
    color: colors.textMuted,
    textTransform: 'uppercase',
  },
  missedPriceStruck: {
    fontFamily: fonts.heading,
    fontSize: 16,
    color: colors.textMuted,
    textDecorationLine: 'line-through',
  },
  missedInfo: {
    fontFamily: fonts.serif,
    fontSize: 14,
    lineHeight: 21,
    color: colors.textMuted,
    marginTop: spacing.sm,
    marginBottom: spacing.md,
  },
});
