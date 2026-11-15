import { useCallback, useMemo, useState } from 'react';
import { Image, Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius, fonts } from '../../../src/theme/colors';
import { EmptyState, Screen, SkeletonCard } from '../../../src/components/ui';
import {
  AppShopProduct,
  appShopEta,
  getAppShop,
  isAppShopMissed,
  isPresaleProduct,
  presaleRunId,
} from '../../../src/api/recommendations';
import { trackEvent } from '../../../src/api/analytics';
import { AppShopDetailSheet, formatEtaDate } from '../../../src/components/AppShopSection';

const SHOP_BASE_URL = 'https://houseofbeers.nl';
const CHECKOUT_BAR_HEIGHT = 72;

interface SaleGroup {
  // Stable identity for the React key and the collapse-override map —
  // distinct from `label` (display text) so two presale runs that both fall
  // back to the generic "Presale" title (e.g. one has no run tag) still
  // don't collide into a single collapsible section.
  key: string;
  label: string;
  newest: string; // ISO created_at used for group ordering
  products: AppShopProduct[];
  // Presale campaign group (one per `presale-run-<id>` tag) rather than a
  // WhatsApp-sale group. Drives the pre-order styling on the group header.
  isPresale: boolean;
  // Soonest estimated_delivery_date across the group's products, or null.
  // Only meaningful when isPresale.
  eta: string | null;
  // Whether this group starts collapsed. Decided here (not from the group's
  // position in the final, mixed list) so a presale group is always open
  // regardless of how many sale groups sit after it, while the normal
  // app-only sale groups keep their exact existing behaviour: newest open,
  // the rest collapsed.
  defaultCollapsed: boolean;
}

/**
 * Group products for the App-exclusief page.
 *
 * Presale products (tag `presale`, one Shopify product per beer — see
 * ShopifyService.get_presale_products in the hob backend) carry no shared
 * "sale" the way normal app-only leftovers do, so grouping them with
 * `saleLabel()` below puts every single beer in its own group of one (the
 * bug this fixes). Instead, all presale products are bucketed by their
 * `presale-run-<id>` tag — the one per-campaign signal the app backend
 * actually has — producing ONE group per active presale run, expanded by
 * default so the user never has to tap to see the beers. A second,
 * concurrently running presale run gets its own group rather than being
 * merged into the first.
 *
 * Normal app-only leftovers are grouped exactly as before: the sale name is
 * the first ` - ` segment of the Shopify title ("SaleName - Letter -
 * BeerName"); products without that shape fall back to a per-day group
 * labelled with the created_at date.
 */
function groupBySale(products: AppShopProduct[], locale: string): SaleGroup[] {
  interface PresaleBucket {
    runId: string | null;
    newest: string;
    eta: string | null;
    products: AppShopProduct[];
  }

  const presaleBuckets = new Map<string, PresaleBucket>();
  const saleGroups = new Map<string, SaleGroup>();

  for (const product of products) {
    if (isPresaleProduct(product)) {
      const runId = presaleRunId(product);
      const key = runId ?? '__presale_unknown_run__';
      let bucket = presaleBuckets.get(key);
      if (!bucket) {
        bucket = { runId, newest: '', eta: null, products: [] };
        presaleBuckets.set(key, bucket);
      }
      bucket.products.push(product);
      if ((product.created_at || '') > bucket.newest) {
        bucket.newest = product.created_at || '';
      }
      const eta = appShopEta(product);
      if (eta && (!bucket.eta || eta < bucket.eta)) {
        bucket.eta = eta;
      }
      continue;
    }

    const label = saleLabel(product, locale);
    let group = saleGroups.get(label);
    if (!group) {
      group = {
        key: `sale:${label}`,
        label,
        newest: product.created_at || '',
        products: [],
        isPresale: false,
        eta: null,
        defaultCollapsed: false,
      };
      saleGroups.set(label, group);
    }
    group.products.push(product);
    if ((product.created_at || '') > group.newest) {
      group.newest = product.created_at || '';
    }
  }

  const presaleBucketList = [...presaleBuckets.values()].sort((a, b) =>
    b.newest.localeCompare(a.newest)
  );
  // Only disambiguate with the run id when two presale runs are genuinely
  // live at once — the number means nothing to a customer otherwise.
  const multiplePresaleGroups = presaleBucketList.length > 1;
  const presaleGroups: SaleGroup[] = presaleBucketList.map((bucket) => ({
    key: `presale:${bucket.runId ?? 'unknown'}`,
    label:
      multiplePresaleGroups && bucket.runId
        ? t('discover.appShopPresaleRunTitle', { runId: bucket.runId })
        : t('discover.appShopPresaleTitle'),
    newest: bucket.newest,
    products: bucket.products,
    isPresale: true,
    eta: bucket.eta,
    // The whole point of this fix: no tap required to see the beers.
    defaultCollapsed: false,
  }));

  const saleGroupList = [...saleGroups.values()]
    .sort((a, b) => b.newest.localeCompare(a.newest))
    // Unchanged from before this fix: newest sale group open, the rest
    // collapsed — now based on each group's own position among sale
    // groups, not its position in the final (presale-first) list.
    .map((group, index) => ({ ...group, defaultCollapsed: index > 0 }));

  return [...presaleGroups, ...saleGroupList];
}

function saleLabel(product: AppShopProduct, locale: string): string {
  const shopifyTitle = product.shopify_title || '';
  if (shopifyTitle.includes(' - ')) {
    const name = shopifyTitle.split(' - ')[0].trim();
    if (name) return name;
  }
  return t('discover.appShopSaleFallback', {
    date: formatDate(product.created_at, locale),
  });
}

function formatDate(isoDate: string, locale: string): string {
  const date = new Date(isoDate);
  if (isNaN(date.getTime())) return '';
  try {
    return date.toLocaleDateString(locale === 'nl' ? 'nl-NL' : 'en-GB', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
  } catch {
    return date.toISOString().slice(0, 10);
  }
}

export default function AppShopScreen() {
  const { language } = useLanguage();
  const [products, setProducts] = useState<AppShopProduct[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState<AppShopProduct | null>(null);
  // Client-side cart: product id → quantity. Deliberately screen-local (v1):
  // leaving the page may reset it.
  const [cart, setCart] = useState<Record<string, number>>({});
  // Collapse overrides per group (keyed by SaleGroup.key, not the display
  // label). Absent = each group's own `defaultCollapsed` (see groupBySale):
  // every presale group starts open, the newest sale group starts open,
  // older sales start collapsed.
  const [groupOverrides, setGroupOverrides] = useState<Record<string, boolean>>({});

  const loadData = useCallback(async () => {
    try {
      const result = await getAppShop();
      setProducts(result.products);
      // Clamp any cart lines to the fresh inventory; drop vanished products.
      setCart((prev) => {
        const byId = new Map(result.products.map((p) => [p.id, p]));
        const next: Record<string, number> = {};
        for (const [id, qty] of Object.entries(prev)) {
          const product = byId.get(id);
          if (product && qty > 0) {
            next[id] = Math.min(qty, product.inventory);
          }
        }
        return next;
      });
    } catch (err) {
      console.log('[AppShop] Load error:', err);
      setProducts((prev) => prev ?? []);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      loadData();
    }, [loadData])
  );

  async function handleRefresh() {
    setRefreshing(true);
    await loadData();
    setRefreshing(false);
  }

  const groups = useMemo(
    () => groupBySale(products ?? [], language),
    [products, language]
  );

  const { totalQty, totalPrice } = useMemo(() => {
    let qty = 0;
    let price = 0;
    for (const product of products ?? []) {
      const count = cart[product.id] || 0;
      if (count > 0) {
        qty += count;
        price += count * Number(product.price);
      }
    }
    return { totalQty: qty, totalPrice: price };
  }, [products, cart]);

  // Delta-based with a functional update: two fast taps must both count,
  // so never compute the target from the render-time quantity.
  function adjustQuantity(product: AppShopProduct, delta: number) {
    setCart((prev) => {
      const current = prev[product.id] || 0;
      const clamped = Math.max(0, Math.min(current + delta, product.inventory));
      const next = { ...prev };
      if (clamped === 0) {
        delete next[product.id];
      } else {
        next[product.id] = clamped;
      }
      return next;
    });
  }

  function checkout() {
    // One Shopify cart permalink for all selected items:
    // /cart/{variant_id}:{qty},{variant_id}:{qty}
    const perVariant = new Map<string, number>();
    for (const product of products ?? []) {
      const qty = cart[product.id] || 0;
      if (qty > 0 && product.variant_id) {
        perVariant.set(
          product.variant_id,
          (perVariant.get(product.variant_id) || 0) + qty
        );
      }
    }
    if (perVariant.size === 0) return;
    const items = [...perVariant.entries()]
      .map(([variantId, qty]) => `${variantId}:${qty}`)
      .join(',');
    trackEvent('app_shop_checkout', { items: totalQty, total: totalPrice.toFixed(2) });
    // attributes[source] tags the Shopify order as app-originated
    Linking.openURL(`${SHOP_BASE_URL}/cart/${items}?attributes[source]=app-shop`).catch(
      (err) => console.log('[AppShop] Open cart error:', err)
    );
  }

  const loading = products === null;
  const empty = !loading && (products?.length ?? 0) === 0;

  return (
    <View style={styles.root}>
      <Stack.Screen options={{ title: t('discover.appShopTitle') }} />
      <Screen refreshing={refreshing} onRefresh={handleRefresh}>
        {loading && (
          <View style={styles.skeletons}>
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </View>
        )}

        {empty && (
          <EmptyState
            icon="beer-outline"
            title={t('discover.appShopEmptyTitle')}
            message={t('discover.appShopEmptyMessage')}
          />
        )}

        {groups.map((group) => {
          const isCollapsed = groupOverrides[group.key] ?? group.defaultCollapsed;
          return (
          <View key={group.key} style={styles.saleGroup}>
            <Pressable
              onPress={() =>
                setGroupOverrides((prev) => ({ ...prev, [group.key]: !isCollapsed }))
              }
              style={({ pressed }) => [styles.saleHeader, pressed && { opacity: 0.85 }]}
            >
              <Text style={styles.saleTitle}>{group.label}</Text>
              <View style={styles.saleHeaderRight}>
                {group.isPresale && (
                  // Pre-order badge/ETA, reusing the same chip style and
                  // copy as the per-card ETA chip below — a presale group
                  // is a pre-order even before any single card is expanded.
                  <View style={styles.etaChip}>
                    <Ionicons name="time-outline" size={9} color={colors.primary} />
                    <Text style={styles.etaChipText}>
                      {group.eta
                        ? t('discover.appShopEtaShort', {
                            date: formatEtaDate(group.eta, language),
                          })
                        : t('discover.appShopPreorderBadge')}
                    </Text>
                  </View>
                )}
                {group.products.every(isAppShopMissed) && (
                  <Text style={styles.saleMissed}>{t('discover.appShopMissed')}</Text>
                )}
                <Text style={styles.saleCount}>
                  {t('discover.appShopGroupCount', { count: group.products.length })}
                </Text>
                <Ionicons
                  name={isCollapsed ? 'chevron-down' : 'chevron-up'}
                  size={18}
                  color={colors.textMuted}
                />
              </View>
            </Pressable>
            {!isCollapsed && group.products.map((product) => {
              const qty = cart[product.id] || 0;
              return (
                <Pressable
                  key={product.id}
                  onPress={() => setSelected(product)}
                  style={({ pressed }) => [
                    styles.card,
                    isAppShopMissed(product) && styles.cardMissed,
                    pressed && { opacity: 0.9 },
                  ]}
                >
                  {product.image_url ? (
                    <Image
                      source={{ uri: product.image_url }}
                      style={[styles.cardImage, isAppShopMissed(product) && styles.cardImageMissed]}
                      resizeMode="cover"
                    />
                  ) : (
                    <View style={[styles.cardImage, styles.cardImagePlaceholder]}>
                      <Ionicons name="beer-outline" size={26} color={colors.textMuted} />
                    </View>
                  )}
                  <View style={styles.cardBody}>
                    <Text style={styles.cardTitle} numberOfLines={2}>
                      {product.title}
                    </Text>
                    <View style={styles.chipRow}>
                      {!!product.style && <Chip label={product.style} />}
                      {!!product.volume && <Chip label={product.volume} />}
                      {product.untappd_rating != null && (
                        <View style={styles.ratingChip}>
                          <Ionicons name="star" size={9} color={colors.background} />
                          <Text style={styles.ratingChipText}>
                            {product.untappd_rating.toFixed(2)}
                          </Text>
                        </View>
                      )}
                      {appShopEta(product) && (
                        <View style={styles.etaChip}>
                          <Ionicons name="time-outline" size={9} color={colors.primary} />
                          <Text style={styles.etaChipText}>
                            {t('discover.appShopEtaShort', {
                              date: formatEtaDate(appShopEta(product)!, language),
                            })}
                          </Text>
                        </View>
                      )}
                    </View>
                    <View style={styles.cardFooter}>
                      {!isAppShopMissed(product) ? (
                        <>
                          <Text style={styles.price}>
                            €{Number(product.price).toFixed(2)}
                            <Text style={styles.stock}>
                              {'   '}
                              {t('discover.appShopStock', { count: product.inventory })}
                            </Text>
                          </Text>
                          <QuantityStepper
                            quantity={qty}
                            max={product.inventory}
                            onChange={(delta) => adjustQuantity(product, delta)}
                          />
                        </>
                      ) : (
                        <>
                          <Text style={styles.priceMissed}>
                            {product.sale_price != null && (
                              <Text style={styles.priceStruck}>
                                €{Number(product.sale_price).toFixed(2)}{'  '}
                              </Text>
                            )}
                            €{Number(product.price).toFixed(2)}
                          </Text>
                          <Text style={styles.missedLabel}>
                            {t('discover.appShopMissed')}
                          </Text>
                        </>
                      )}
                    </View>
                  </View>
                </Pressable>
              );
            })}
          </View>
          );
        })}

        {/* Keep the last cards reachable above the sticky checkout bar */}
        {totalQty > 0 && <View style={{ height: CHECKOUT_BAR_HEIGHT }} />}
      </Screen>

      {totalQty > 0 && (
        <View style={styles.checkoutBar}>
          <Pressable
            onPress={checkout}
            style={({ pressed }) => [styles.checkoutBtn, pressed && { opacity: 0.85 }]}
          >
            <Ionicons name="cart" size={18} color={colors.background} />
            <Text style={styles.checkoutText}>
              {t('discover.appShopCheckout', {
                count: totalQty,
                total: totalPrice.toFixed(2),
              })}
            </Text>
          </Pressable>
        </View>
      )}

      <AppShopDetailSheet product={selected} onClose={() => setSelected(null)} />
    </View>
  );
}

function QuantityStepper({
  quantity,
  max,
  onChange,
}: {
  quantity: number;
  max: number;
  onChange: (delta: number) => void;
}) {
  const minusDisabled = quantity <= 0;
  const plusDisabled = quantity >= max;
  return (
    <View style={styles.stepper}>
      <Pressable
        onPress={() => onChange(-1)}
        disabled={minusDisabled}
        hitSlop={6}
        accessibilityLabel={t('discover.appShopQtyMinus')}
        style={({ pressed }) => [
          styles.stepperBtn,
          minusDisabled && styles.stepperBtnDisabled,
          pressed && { opacity: 0.7 },
        ]}
      >
        <Ionicons
          name="remove"
          size={16}
          color={minusDisabled ? colors.textMuted : colors.text}
        />
      </Pressable>
      <Text style={styles.stepperQty}>{quantity}</Text>
      <Pressable
        onPress={() => onChange(+1)}
        disabled={plusDisabled}
        hitSlop={6}
        accessibilityLabel={t('discover.appShopQtyPlus')}
        style={({ pressed }) => [
          styles.stepperBtn,
          plusDisabled && styles.stepperBtnDisabled,
          pressed && { opacity: 0.7 },
        ]}
      >
        <Ionicons
          name="add"
          size={16}
          color={plusDisabled ? colors.textMuted : colors.text}
        />
      </Pressable>
    </View>
  );
}

function Chip({ label }: { label: string }) {
  return (
    <View style={styles.chip}>
      <Text style={styles.chipText} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.background,
  },
  skeletons: {
    marginTop: spacing.lg,
  },
  saleGroup: {
    marginBottom: spacing.md,
  },
  saleHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    marginBottom: spacing.sm,
  },
  saleTitle: {
    fontFamily: fonts.heading,
    fontSize: 16,
    letterSpacing: 0.4,
    color: colors.text,
  },
  saleHeaderRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  saleCount: {
    fontSize: 12,
    color: colors.textMuted,
  },
  saleMissed: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 0.5,
    color: colors.textMuted,
    textTransform: 'uppercase',
    backgroundColor: colors.surfaceLow,
    borderRadius: 8,
    paddingHorizontal: 7,
    paddingVertical: 2,
    overflow: 'hidden',
  },
  card: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.primary + '33',
    overflow: 'hidden',
    marginBottom: spacing.sm,
  },
  cardImage: {
    width: 92,
    alignSelf: 'stretch',
    backgroundColor: colors.surfaceLow,
  },
  cardImagePlaceholder: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  cardMissed: {
    borderColor: colors.border,
    opacity: 0.85,
  },
  cardImageMissed: {
    opacity: 0.55,
  },
  cardBody: {
    flex: 1,
    padding: spacing.sm,
    gap: 6,
  },
  cardTitle: {
    fontFamily: fonts.heading,
    fontSize: 14,
    lineHeight: 18,
    letterSpacing: 0.3,
    color: colors.text,
  },
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 5,
    alignItems: 'center',
  },
  chip: {
    backgroundColor: colors.surfaceLow,
    borderRadius: 10,
    paddingHorizontal: 8,
    paddingVertical: 3,
    maxWidth: 140,
  },
  chipText: {
    fontSize: 11,
    color: colors.textMuted,
  },
  ratingChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingHorizontal: 7,
    paddingVertical: 3,
  },
  ratingChipText: {
    fontFamily: fonts.heading,
    fontSize: 10,
    color: colors.background,
  },
  etaChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: colors.primary + '1A',
    borderRadius: 10,
    paddingHorizontal: 7,
    paddingVertical: 3,
  },
  etaChipText: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 0.3,
    color: colors.primary,
  },
  cardFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 'auto' as const,
  },
  price: {
    fontFamily: fonts.heading,
    fontSize: 15,
    color: colors.primary,
  },
  priceMissed: {
    fontFamily: fonts.heading,
    fontSize: 15,
    color: colors.textMuted,
  },
  priceStruck: {
    fontSize: 13,
    color: colors.textMuted,
    textDecorationLine: 'line-through',
  },
  missedLabel: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 0.5,
    color: colors.textMuted,
    textTransform: 'uppercase',
  },
  stock: {
    fontFamily: fonts.serif,
    fontSize: 12,
    color: colors.textMuted,
  },
  stepper: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.pill,
    padding: 3,
    gap: 2,
  },
  stepperBtn: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: colors.surfaceHigh,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepperBtnDisabled: {
    backgroundColor: 'transparent',
  },
  stepperQty: {
    fontFamily: fonts.heading,
    fontSize: 14,
    color: colors.text,
    minWidth: 22,
    textAlign: 'center',
  },
  checkoutBar: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    padding: spacing.md,
    paddingTop: spacing.sm,
    backgroundColor: colors.background + 'F2',
  },
  checkoutBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    backgroundColor: colors.primary,
    borderRadius: borderRadius.lg,
    paddingVertical: 14,
  },
  checkoutText: {
    fontFamily: fonts.heading,
    fontSize: 16,
    letterSpacing: 0.5,
    color: colors.background,
  },
});
