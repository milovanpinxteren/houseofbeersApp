import { useCallback, useMemo, useState } from 'react';
import { Image, Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Stack } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius, fonts } from '../../../src/theme/colors';
import { EmptyState, Screen, SectionHeader, SkeletonCard } from '../../../src/components/ui';
import { AppShopProduct, getAppShop } from '../../../src/api/recommendations';
import { AppShopDetailSheet } from '../../../src/components/AppShopSection';

const SHOP_BASE_URL = 'https://houseofbeers.nl';
const CHECKOUT_BAR_HEIGHT = 72;

interface SaleGroup {
  label: string;
  newest: string; // ISO created_at used for group ordering
  products: AppShopProduct[];
}

/**
 * Group products per sale. The sale name is the first ` - ` segment of the
 * Shopify title ("SaleName - Letter - BeerName"); products without that shape
 * fall back to a per-day group labelled with the created_at date.
 */
function groupBySale(products: AppShopProduct[], locale: string): SaleGroup[] {
  const groups = new Map<string, SaleGroup>();
  for (const product of products) {
    const label = saleLabel(product, locale);
    let group = groups.get(label);
    if (!group) {
      group = { label, newest: product.created_at || '', products: [] };
      groups.set(label, group);
    }
    group.products.push(product);
    if ((product.created_at || '') > group.newest) {
      group.newest = product.created_at || '';
    }
  }
  return [...groups.values()].sort((a, b) => b.newest.localeCompare(a.newest));
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
    Linking.openURL(`${SHOP_BASE_URL}/cart/${items}`).catch((err) =>
      console.log('[AppShop] Open cart error:', err)
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

        {groups.map((group) => (
          <View key={group.label}>
            <SectionHeader title={group.label} />
            {group.products.map((product) => {
              const qty = cart[product.id] || 0;
              return (
                <Pressable
                  key={product.id}
                  onPress={() => setSelected(product)}
                  style={({ pressed }) => [styles.card, pressed && { opacity: 0.9 }]}
                >
                  {product.image_url ? (
                    <Image
                      source={{ uri: product.image_url }}
                      style={styles.cardImage}
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
                    </View>
                    <View style={styles.cardFooter}>
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
                    </View>
                  </View>
                </Pressable>
              );
            })}
          </View>
        ))}

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
