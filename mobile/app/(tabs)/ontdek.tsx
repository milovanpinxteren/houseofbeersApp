import { useCallback, useEffect, useState } from 'react';
import { Image, Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import { useLanguage } from '../../src/context/LanguageContext';
import { t } from '../../src/i18n';
import { colors, spacing, borderRadius, fonts, type } from '../../src/theme/colors';
import { Card, Screen, SectionHeader, Badge, useToast } from '../../src/components/ui';
import {
  addFavorite,
  AppShopProduct,
  Favorite,
  getAppShop,
  getFavorites,
  getNewArrivals,
  NewArrival,
  removeFavorite,
} from '../../src/api/recommendations';
import { AppShopSection } from '../../src/components/AppShopSection';

export default function OntdekScreen() {
  const router = useRouter();
  const { language } = useLanguage();
  const { showToast } = useToast();
  const [favorites, setFavorites] = useState<Favorite[]>([]);
  const [newArrivals, setNewArrivals] = useState<NewArrival[]>([]);
  const [appShop, setAppShop] = useState<AppShopProduct[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [togglingIds, setTogglingIds] = useState<Set<string>>(new Set());

  const favoritesCount = favorites.length;
  const favoriteByBeerId = new Map(favorites.map((fav) => [fav.beer_id, fav]));

  const loadData = useCallback(async () => {
    const [favoritesResult, arrivalsResult, appShopResult] = await Promise.allSettled([
      getFavorites(),
      getNewArrivals(10),
      getAppShop(),
    ]);
    if (favoritesResult.status === 'fulfilled') {
      setFavorites(favoritesResult.value.favorites);
    } else {
      console.log('[Ontdek] Favorites load error:', favoritesResult.reason);
    }
    if (arrivalsResult.status === 'fulfilled') {
      setNewArrivals(arrivalsResult.value.products);
    } else {
      console.log('[Ontdek] New arrivals load error:', arrivalsResult.reason);
    }
    // Empty or failed → no section at all; never retry in a loop
    if (appShopResult.status === 'fulfilled') {
      setAppShop(appShopResult.value.products);
    } else {
      console.log('[Ontdek] App shop load error:', appShopResult.reason);
      setAppShop([]);
    }
  }, []);

  async function toggleFavorite(product: NewArrival) {
    const beerId = String(product.id);
    if (togglingIds.has(beerId)) return;
    setTogglingIds((ids) => new Set(ids).add(beerId));
    try {
      const existing = favoriteByBeerId.get(beerId);
      if (existing) {
        await removeFavorite(existing.id);
        setFavorites((favs) => favs.filter((fav) => fav.id !== existing.id));
      } else {
        const result = await addFavorite({
          beer_id: beerId,
          variant_id: product.variant_id || undefined,
          title: product.title,
          price: product.price ? Number(product.price) : null,
          image_url: product.image_url,
          product_url: product.shop_url,
          style: product.product_type,
        });
        setFavorites((favs) => [...favs, result.favorite]);
      }
    } catch (err: any) {
      console.log('[Ontdek] Favorite toggle error:', err);
      showToast(err?.message || 'Error', 'error');
    } finally {
      setTogglingIds((ids) => {
        const next = new Set(ids);
        next.delete(beerId);
        return next;
      });
    }
  }

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

  return (
    <Screen refreshing={refreshing} onRefresh={handleRefresh}>
      <Text style={styles.intro}>{t('discover.intro')}</Text>

      {/* App exclusives: leftover sale stock, only rendered when available */}
      <AppShopSection
        products={appShop}
        onViewAll={() => router.push('/(profile)/app-shop' as any)}
      />

      <SectionHeader title={t('discover.forYou')} />

      {/* Hero: recommendations */}
      <Card
        variant="accent"
        onPress={() => router.push('/(profile)/recommendations' as any)}
        style={styles.heroCard}
      >
        <View style={styles.heroIconWrap}>
          <Ionicons name="beer" size={30} color={colors.primary} />
        </View>
        <View style={styles.heroText}>
          <Text style={styles.heroTitle}>{t('discover.recommendationsTitle')}</Text>
          <Text style={styles.heroSubtitle}>{t('discover.recommendationsSubtitle')}</Text>
        </View>
        <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
      </Card>

      {/* 2x2 feature grid: taste profile, favorites, random beer, sixpack */}
      <View style={styles.tileRow}>
        <Card
          onPress={() => router.push('/(profile)/taste-profile' as any)}
          style={styles.tile}
        >
          <Ionicons name="analytics" size={24} color={colors.primary} />
          <Text style={styles.tileTitle}>{t('discover.tasteProfileTitle')}</Text>
          <Text style={styles.tileSubtitle} numberOfLines={2}>
            {t('discover.tasteProfileSubtitle')}
          </Text>
        </Card>
        <Card
          onPress={() => router.push('/(profile)/favorites' as any)}
          style={styles.tile}
        >
          <View style={styles.tileHeader}>
            <Ionicons name="heart" size={24} color={colors.secondary} />
            {favoritesCount > 0 && <Badge value={favoritesCount} />}
          </View>
          <Text style={styles.tileTitle}>{t('discover.favoritesTitle')}</Text>
          <Text style={styles.tileSubtitle} numberOfLines={2}>
            {t('discover.favoritesSubtitle')}
          </Text>
        </Card>
      </View>
      <View style={styles.tileRow}>
        <Card
          onPress={() => router.push('/(profile)/random-beer' as any)}
          style={styles.tile}
        >
          <Ionicons name="dice" size={24} color={colors.primary} />
          <Text style={styles.tileTitle}>{t('randomBeer.cardTitle')}</Text>
          <Text style={styles.tileSubtitle} numberOfLines={2}>
            {t('randomBeer.cardSubtitle')}
          </Text>
        </Card>
        <Card
          onPress={() => router.push('/(profile)/sixpack' as any)}
          style={styles.tile}
        >
          <Ionicons name="gift" size={24} color={colors.primary} />
          <Text style={styles.tileTitle}>{t('sixpack.cardTitle')}</Text>
          <Text style={styles.tileSubtitle} numberOfLines={2}>
            {t('sixpack.cardSubtitle')}
          </Text>
        </Card>
      </View>

      {/* New arrivals rail */}
      {newArrivals.length > 0 && (
        <>
          <SectionHeader title={t('discover.newArrivalsTitle')} />
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.railContent}
            style={styles.rail}
          >
            {newArrivals.map((product) => {
              const favorited = favoriteByBeerId.has(String(product.id));
              return (
                <Pressable
                  key={product.id}
                  onPress={() =>
                    Linking.openURL(product.shop_url).catch((err) =>
                      console.log('[Ontdek] Open product error:', err)
                    )
                  }
                  style={({ pressed }) => [styles.railCard, pressed && { opacity: 0.85 }]}
                >
                  {product.image_url ? (
                    <Image
                      source={{ uri: product.image_url }}
                      style={styles.railImage}
                      resizeMode="cover"
                    />
                  ) : (
                    <View style={styles.railImagePlaceholder}>
                      <Ionicons name="beer-outline" size={32} color={colors.textMuted} />
                    </View>
                  )}
                  <Pressable
                    onPress={() => toggleFavorite(product)}
                    hitSlop={8}
                    style={({ pressed }) => [
                      styles.railHeart,
                      pressed && { opacity: 0.7 },
                    ]}
                  >
                    <Ionicons
                      name={favorited ? 'heart' : 'heart-outline'}
                      size={17}
                      color={favorited ? colors.secondary : colors.text}
                    />
                  </Pressable>
                  <View style={styles.railBody}>
                    <Text style={styles.railTitle} numberOfLines={2}>
                      {product.title}
                    </Text>
                    {!!product.price && (
                      <Text style={styles.railPrice}>
                        €{Number(product.price).toFixed(2)}
                      </Text>
                    )}
                  </View>
                </Pressable>
              );
            })}
          </ScrollView>
        </>
      )}

    </Screen>
  );
}

const styles = StyleSheet.create({
  intro: {
    ...type.serifLarge,
    fontFamily: fonts.serifItalic,
    color: colors.textMuted,
    marginTop: spacing.md,
  },
  heroCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.sm,
  },
  heroIconWrap: {
    width: 56,
    height: 56,
    borderRadius: 18,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  heroText: {
    flex: 1,
  },
  heroTitle: {
    fontFamily: fonts.heading,
    fontSize: 18,
    letterSpacing: 0.5,
    color: colors.text,
  },
  heroSubtitle: {
    fontFamily: fonts.serif,
    fontSize: 14,
    color: colors.textMuted,
    marginTop: 2,
  },
  tileRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  tile: {
    flex: 1,
    gap: spacing.xs,
  },
  tileHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  tileTitle: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.4,
    color: colors.text,
    marginTop: spacing.xs,
  },
  tileSubtitle: {
    fontSize: 12,
    lineHeight: 16,
    color: colors.textMuted,
  },
  rail: {
    marginHorizontal: -spacing.md,
    marginBottom: spacing.sm,
  },
  railContent: {
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  railCard: {
    width: 140,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    overflow: 'hidden',
  },
  railImage: {
    width: '100%',
    aspectRatio: 1,
    backgroundColor: colors.surfaceLow,
  },
  railImagePlaceholder: {
    width: '100%',
    aspectRatio: 1,
    backgroundColor: colors.surfaceLow,
    alignItems: 'center',
    justifyContent: 'center',
  },
  railHeart: {
    position: 'absolute',
    top: 8,
    right: 8,
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: colors.background + 'B3',
    alignItems: 'center',
    justifyContent: 'center',
  },
  railBody: {
    padding: spacing.sm,
  },
  railTitle: {
    fontFamily: fonts.heading,
    fontSize: 13,
    lineHeight: 17,
    letterSpacing: 0.3,
    color: colors.text,
    minHeight: 34,
  },
  railPrice: {
    fontFamily: fonts.heading,
    fontSize: 14,
    color: colors.primary,
    marginTop: 4,
  },
});
