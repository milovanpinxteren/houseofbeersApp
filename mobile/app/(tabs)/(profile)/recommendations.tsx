import { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
  Image,
  Linking,
  FlatList,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import {
  getRecommendations,
  getUntappdProfile,
  getFavorites,
  addFavorite,
  removeFavorite,
  RecommendationsResponse,
  ScoredBeer,
  UntappdProfile,
  Favorite,
} from '../../../src/api/recommendations';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
import PriceSlider from '../../../src/components/PriceSlider';

const MIN_PRICE = 0;
const MAX_PRICE = 100;

export default function RecommendationsScreen() {
  const { language } = useLanguage();
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [recommendations, setRecommendations] = useState<RecommendationsResponse | null>(null);
  const [untappdProfile, setUntappdProfile] = useState<UntappdProfile | null>(null);
  const [favorites, setFavorites] = useState<Favorite[]>([]);
  const [favoriteIds, setFavoriteIds] = useState<Set<string>>(new Set());
  const [loadingFavorite, setLoadingFavorite] = useState<string | null>(null);

  // Price filter state (MAX_PRICE means no limit)
  const [maxPrice, setMaxPrice] = useState(MAX_PRICE);
  const [isFiltering, setIsFiltering] = useState(false);

  const loadData = useCallback(async (priceMax?: number) => {
    try {
      setError('');
      const priceFilter = priceMax !== undefined ? priceMax : maxPrice;
      // Only apply filter if not at max (no limit)
      const filterValue = priceFilter >= MAX_PRICE ? undefined : priceFilter;
      const [recsData, untappdData, favoritesData] = await Promise.all([
        getRecommendations({
          limit: 10,
          price_max: filterValue,
        }),
        getUntappdProfile(),
        getFavorites(),
      ]);
      setRecommendations(recsData);
      setUntappdProfile(untappdData.untappd);
      setFavorites(favoritesData.favorites);
      setFavoriteIds(new Set(favoritesData.favorites.map(f => f.beer_id)));
    } catch (err) {
      console.log('[Recommendations] Error:', err);
      setError(err instanceof Error ? err.message : t('recommendations.loadError'));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
      setIsFiltering(false);
    }
  }, [maxPrice]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  function handleRefresh() {
    setIsRefreshing(true);
    loadData();
  }

  function handlePriceChange(value: number) {
    setMaxPrice(value);
  }

  function handlePriceChangeEnd(value: number) {
    setIsFiltering(true);
    loadData(value);
  }

  async function toggleFavorite(beer: ScoredBeer['beer']) {
    const beerId = String(beer.id);
    setLoadingFavorite(beerId);

    try {
      if (favoriteIds.has(beerId)) {
        const favorite = favorites.find(f => f.beer_id === beerId);
        if (favorite) {
          await removeFavorite(favorite.id);
          setFavorites(prev => prev.filter(f => f.id !== favorite.id));
          setFavoriteIds(prev => {
            const next = new Set(prev);
            next.delete(beerId);
            return next;
          });
        }
      } else {
        const result = await addFavorite({
          beer_id: beerId,
          variant_id: beer.variant_id,
          title: beer.title,
          vendor: beer.vendor,
          price: beer.price ? parseFloat(beer.price) : null,
          image_url: beer.image_url,
          product_url: beer.product_url,
          untappd_rating: beer.untappd_rating,
          abv: beer.abv,
          style: beer.style_category,
        });
        setFavorites(prev => [result.favorite, ...prev]);
        setFavoriteIds(prev => new Set(prev).add(beerId));
      }
    } catch (err) {
      console.log('[Recommendations] Favorite error:', err);
    } finally {
      setLoadingFavorite(null);
    }
  }

  function openProduct(url: string) {
    Linking.openURL(url);
  }

  function renderBeerCard(item: ScoredBeer, index: number) {
    const beer = item.beer;
    const beerId = String(beer.id);
    const isFavorite = favoriteIds.has(beerId);
    const isLoadingThis = loadingFavorite === beerId;

    return (
      <View style={styles.beerCard} key={beerId}>
        <TouchableOpacity
          style={styles.beerImageContainer}
          onPress={() => openProduct(beer.product_url)}
          activeOpacity={0.8}
        >
          {beer.image_url ? (
            <Image source={{ uri: beer.image_url }} style={styles.beerImage} />
          ) : (
            <View style={styles.beerImagePlaceholder}>
              <Ionicons name="beer-outline" size={40} color={colors.textMuted} />
            </View>
          )}
        </TouchableOpacity>

        <View style={styles.beerInfo}>
          <TouchableOpacity onPress={() => openProduct(beer.product_url)}>
            <Text style={styles.beerTitle} numberOfLines={2}>{beer.title}</Text>
          </TouchableOpacity>

          <View style={styles.beerMeta}>
            {beer.untappd_rating && (
              <View style={styles.ratingBadge}>
                <Ionicons name="star" size={12} color="#FFD700" />
                <Text style={styles.ratingText}>{parseFloat(String(beer.untappd_rating)).toFixed(1)}</Text>
              </View>
            )}
            {beer.abv && (
              <Text style={styles.abvText}>{beer.abv}%</Text>
            )}
          </View>

          <View style={styles.beerFooter}>
            {beer.price && (
              <Text style={styles.priceText}>€{parseFloat(beer.price).toFixed(2)}</Text>
            )}
            <TouchableOpacity
              style={styles.favoriteButton}
              onPress={() => toggleFavorite(beer)}
              disabled={isLoadingThis}
            >
              {isLoadingThis ? (
                <ActivityIndicator size="small" color={colors.primary} />
              ) : (
                <Ionicons
                  name={isFavorite ? 'heart' : 'heart-outline'}
                  size={22}
                  color={isFavorite ? colors.error : colors.textMuted}
                />
              )}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    );
  }

  function renderBeerCarousel(title: string, beers: ScoredBeer[], emptyText: string) {
    if (!beers || beers.length === 0) return null;

    return (
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>{title}</Text>
        <FlatList
          data={beers}
          horizontal
          showsHorizontalScrollIndicator={false}
          keyExtractor={(item) => String(item.beer.id)}
          renderItem={({ item, index }) => renderBeerCard(item, index)}
          contentContainerStyle={styles.carouselContent}
        />
      </View>
    );
  }

  if (isLoading) {
    return (
      <View style={styles.centerContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
        <Text style={styles.loadingText}>{t('recommendations.analyzing')}</Text>
        <Text style={styles.loadingSubtext}>{t('recommendations.analyzingSubtext')}</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.centerContainer}>
        <Ionicons name="alert-circle-outline" size={48} color={colors.error} />
        <Text style={styles.errorText}>{error}</Text>
        <TouchableOpacity style={styles.retryButton} onPress={loadData}>
          <Text style={styles.retryButtonText}>{t('common.retry')}</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={handleRefresh}
            tintColor={colors.primary}
          />
        }
      >
        {/* Profile Source Card */}
        <View style={styles.profileCard}>
          <Ionicons
            name={untappdProfile ? 'beer' : 'cart'}
            size={24}
            color={colors.primary}
          />
          <View style={styles.profileInfo}>
            <Text style={styles.profileTitle}>
              {untappdProfile ? t('recommendations.untappdProfile') : t('recommendations.orderHistory')}
            </Text>
            <Text style={styles.profileSubtitle}>
              {untappdProfile ? untappdProfile.username : t('recommendations.basedOnOrders')}
            </Text>
          </View>
        </View>

        {/* Quick Stats */}
        {recommendations?.profile_summary && (
          <View style={styles.quickStats}>
            <View style={styles.quickStat}>
              <Text style={styles.quickStatValue}>
                {recommendations.profile_summary.unique_beers}
              </Text>
              <Text style={styles.quickStatLabel}>{t('recommendations.uniqueBeers')}</Text>
            </View>
            <View style={styles.quickStatDivider} />
            <View style={styles.quickStat}>
              <Text style={styles.quickStatValue}>
                {recommendations.profile_summary.preferred_styles?.[0] || '-'}
              </Text>
              <Text style={styles.quickStatLabel}>{t('recommendations.topStyle')}</Text>
            </View>
          </View>
        )}

        {/* Price Filter */}
        <View style={styles.filterCard}>
          <View style={styles.filterHeader}>
            <View style={styles.filterLabelRow}>
              <Ionicons name="pricetag-outline" size={18} color={colors.primary} />
              <Text style={styles.filterLabel}>{t('recommendations.maxPrice')}</Text>
            </View>
            <View style={styles.priceValueRow}>
              {isFiltering && (
                <ActivityIndicator size="small" color={colors.primary} style={styles.filterSpinner} />
              )}
              <Text style={styles.priceValue}>
                {maxPrice >= MAX_PRICE ? t('recommendations.allPrices') : `€${maxPrice}`}
              </Text>
            </View>
          </View>
          <PriceSlider
            min={MIN_PRICE}
            max={MAX_PRICE}
            value={maxPrice}
            step={5}
            onChange={handlePriceChange}
            onChangeEnd={handlePriceChangeEnd}
          />
        </View>

        {/* Recommendations */}
        {renderBeerCarousel(
          t('recommendations.recommendedForYou'),
          recommendations?.recommendations || [],
          t('recommendations.noRecommendations')
        )}

        {/* Discovery Picks */}
        {renderBeerCarousel(
          t('recommendations.discoverSomethingNew'),
          recommendations?.discovery_picks || [],
          t('recommendations.noDiscovery')
        )}

        {/* Tried Beers */}
        {recommendations?.tried_beers && recommendations.tried_beers.length > 0 && (
          renderBeerCarousel(
            t('recommendations.triedBeers'),
            recommendations.tried_beers,
            ''
          )
        )}

        <View style={styles.bottomPadding} />
      </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  centerContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
    padding: spacing.lg,
  },
  loadingText: {
    marginTop: spacing.md,
    color: colors.text,
    fontSize: 16,
    fontWeight: '600',
  },
  loadingSubtext: {
    marginTop: spacing.xs,
    color: colors.textMuted,
    fontSize: 14,
    textAlign: 'center',
  },
  errorText: {
    marginTop: spacing.md,
    color: colors.error,
    fontSize: 14,
    textAlign: 'center',
  },
  retryButton: {
    marginTop: spacing.md,
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
  },
  retryButtonText: {
    color: colors.background,
    fontWeight: '600',
  },

  // Profile Card
  profileCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    margin: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.primary + '40',
  },
  profileInfo: {
    flex: 1,
    marginLeft: spacing.sm,
  },
  profileTitle: {
    fontSize: 14,
    color: colors.textMuted,
  },
  profileSubtitle: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text,
  },

  // Quick Stats
  quickStats: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  quickStat: {
    flex: 1,
    alignItems: 'center',
  },
  quickStatValue: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.primary,
  },
  quickStatLabel: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
  quickStatDivider: {
    width: 1,
    backgroundColor: colors.tertiary + '30',
    marginHorizontal: spacing.md,
  },

  // Price Filter
  filterCard: {
    backgroundColor: colors.surface,
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  filterHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  filterLabelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  filterLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
  },
  priceValueRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  filterSpinner: {
    marginRight: spacing.xs,
  },
  priceValue: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.primary,
  },

  // Sections
  section: {
    marginBottom: spacing.lg,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  carouselContent: {
    paddingHorizontal: spacing.md,
  },

  // Beer Cards
  beerCard: {
    width: 160,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    marginRight: spacing.sm,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  beerImageContainer: {
    width: '100%',
    aspectRatio: 1,
    backgroundColor: colors.background,
  },
  beerImage: {
    width: '100%',
    height: '100%',
    resizeMode: 'cover',
  },
  beerImagePlaceholder: {
    width: '100%',
    height: '100%',
    justifyContent: 'center',
    alignItems: 'center',
  },
  beerInfo: {
    padding: spacing.sm,
  },
  beerTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
    lineHeight: 18,
  },
  beerMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  ratingBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FFD700' + '20',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 8,
    gap: 2,
  },
  ratingText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#B8860B',
  },
  abvText: {
    fontSize: 12,
    color: colors.textMuted,
  },
  beerFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: spacing.sm,
  },
  priceText: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
  },
  favoriteButton: {
    padding: spacing.xs,
  },

  bottomPadding: {
    height: spacing.xl,
  },
});
