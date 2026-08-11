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
import { AppShopProduct } from '../api/recommendations';

/**
 * "App exclusives" rail: leftover WhatsApp-sale beers sold only in the app.
 * Renders nothing when there are no products — the section simply does not
 * exist most of the time, by design.
 */
export function AppShopSection({ products }: { products: AppShopProduct[] }) {
  const [selected, setSelected] = useState<AppShopProduct | null>(null);

  if (products.length === 0) {
    return null;
  }

  function order(product: AppShopProduct) {
    Linking.openURL(product.cart_url).catch((err) =>
      console.log('[AppShop] Open cart error:', err)
    );
  }

  return (
    <>
      <SectionHeader title={t('discover.appShopTitle')} />
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.railContent}
        style={styles.rail}
      >
        {products.map((product) => (
          <Pressable
            key={product.id}
            onPress={() => setSelected(product)}
            style={({ pressed }) => [styles.card, pressed && { opacity: 0.85 }]}
          >
            {product.image_url ? (
              <Image
                source={{ uri: product.image_url }}
                style={styles.image}
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
                <Text style={styles.price}>€{Number(product.price).toFixed(2)}</Text>
                <Text style={styles.stock}>
                  {t('discover.appShopStock', { count: product.inventory })}
                </Text>
              </View>
            </View>
          </Pressable>
        ))}
      </ScrollView>

      {/* Detail sheet */}
      <Modal
        visible={selected !== null}
        transparent
        animationType="slide"
        onRequestClose={() => setSelected(null)}
      >
        <Pressable style={styles.modalOverlay} onPress={() => setSelected(null)}>
          <Pressable style={styles.sheet} onPress={() => {}}>
            {selected && (
              <ScrollView showsVerticalScrollIndicator={false}>
                <View style={styles.sheetHandle} />
                {selected.image_url ? (
                  <Image
                    source={{ uri: selected.image_url }}
                    style={styles.sheetImage}
                    resizeMode="cover"
                  />
                ) : null}
                <View style={styles.exclusiveBadge}>
                  <Ionicons name="sparkles" size={12} color={colors.primary} />
                  <Text style={styles.exclusiveText}>{t('discover.appShopBadge')}</Text>
                </View>
                <Text style={styles.sheetTitle}>{selected.title}</Text>

                <View style={styles.chipRow}>
                  {!!selected.style && <Chip label={selected.style} />}
                  {!!selected.abv && <Chip label={selected.abv.includes('%') ? selected.abv : `${selected.abv}%`} />}
                  {!!selected.volume && <Chip label={selected.volume} />}
                  {!!selected.country && <Chip label={selected.country} />}
                </View>

                {selected.untappd_rating != null && (
                  <View style={styles.untappdRow}>
                    <Ionicons name="star" size={14} color={colors.primary} />
                    <Text style={styles.untappdText}>
                      {selected.untappd_rating.toFixed(2)}
                      {selected.untappd_checkins
                        ? `  ·  ${selected.untappd_checkins.toLocaleString()} ${t('discover.appShopCheckins')}`
                        : ''}
                    </Text>
                  </View>
                )}

                {!!selected.description && (
                  <Text style={styles.description}>{selected.description}</Text>
                )}

                <Pressable
                  onPress={() => order(selected)}
                  style={({ pressed }) => [styles.orderBtn, pressed && { opacity: 0.85 }]}
                >
                  <Text style={styles.orderBtnText}>
                    {t('discover.appShopOrder')} · €{Number(selected.price).toFixed(2)}
                  </Text>
                </Pressable>
                <Text style={styles.stockNote}>
                  {t('discover.appShopStock', { count: selected.inventory })}
                </Text>
              </ScrollView>
            )}
          </Pressable>
        </Pressable>
      </Modal>
    </>
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
  image: {
    width: '100%',
    aspectRatio: 1,
    backgroundColor: colors.surfaceLow,
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
  stock: {
    fontSize: 11,
    color: colors.textMuted,
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
  sheetImage: {
    width: '100%',
    aspectRatio: 1.2,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.surfaceLow,
    marginBottom: spacing.sm,
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
    marginBottom: spacing.xs,
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
});
