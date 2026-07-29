import { useState, useEffect, useCallback, useRef } from 'react';
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
  getRecommendationStatus,
  getUntappdProfile,
  getFavorites,
  addFavorite,
  removeFavorite,
  isPendingRecommendations,
  RecommendationsResponse,
  ScoredBeer,
  UntappdProfile,
  Favorite,
} from '../../../src/api/recommendations';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
import PriceSlider from '../../../src/components/PriceSlider';

const MIN_PRICE = 0;
const MAX_PRICE = 100;

// Client-side long polling for profile builds (backend hands us a task_id
// instead of blocking a gunicorn worker)
const POLL_INTERVAL_MS = 3000;
const MAX_POLL_ATTEMPTS = 40; // ~2 minutes

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

  const [isBuildingProfile, setIsBuildingProfile] = useState(false);

  // Price filter state (MAX_PRICE means no limit)
  const [maxPrice, setMaxPrice] = useState(MAX_PRICE);
  const [isFiltering, setIsFiltering] = useState(false);

  // Read via ref inside loadData so its identity is stable (no refetch on
  // every slider tick) — data loading is only triggered explicitly.
  const maxPriceRef = useRef(MAX_PRICE);
  // Monotonically increasing sequence; responses from stale requests are ignored.
  const requestSeqRef = useRef(0);
  // Guard against an endless pending -> poll -> refetch loop
  const didRefetchAfterPendingRef = useRef(false);

  const pollTaskStatus = useCallback(async (taskId: string, seq: number) => {
    for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      if (seq !== requestSeqRef.current) return; // superseded by a newer load
      try {
        const statusData = await getRecommendationStatus(taskId);
        if (seq !== requestSeqRef.current) return;
        if (statusData.status !== 'pending') {
          // completed or failed — either way refetch; on failure the backend
          // falls back to Shopify order history
          break;
        }
      } catch (err) {
        console.log('[Recommendations] Status poll error:', err);
        break;
      }
    }
    if (seq !== requestSeqRef.current) return;
    setIsBuildingProfile(false);
    if (didRefetchAfterPendingRef.current) {
      // Already refetched once for this load — don't loop
      setError(t('recommendations.loadError'));
      setIsLoading(false);
      return;
    }
    didRefetchAfterPendingRef.current = true;
    setIsLoading(true);
    loadDataRef.current();
  }, []);

  const loadData = useCallback(async (priceMax?: number) => {
    const seq = ++requestSeqRef.current;
    try {
      setError('');
      const priceFilter = priceMax !== undefined ? priceMax : maxPriceRef.current;
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
      if (seq !== requestSeqRef.current) return; // stale response
      setUntappdProfile(untappdData.untappd);
      setFavorites(favoritesData.favorites);
      setFavoriteIds(new Set(favoritesData.favorites.map(f => f.beer_id)));

      if (isPendingRecommendations(recsData)) {
        // Profile is still being built — show a friendly state and long-poll
        setIsBuildingProfile(true);
        setIsLoading(false);
        setIsRefreshing(false);
        setIsFiltering(false);
        pollTaskStatus(recsData.task_id, seq);
        return;
      }

      setIsBuildingProfile(false);
      setRecommendations(recsData);
    } catch (err) {
      if (seq !== requestSeqRef.current) return;
      console.log('[Recommendations] Error:', err);
      setError(err instanceof Error ? err.message : t('recommendations.loadError'));
    } finally {
      if (seq === requestSeqRef.current) {
        setIsLoading(false);
        setIsRefreshing(false);
        setIsFiltering(false);
      }
    }
  }, [pollTaskStatus]);

  // Stable handle so pollTaskStatus can refetch without a circular dependency
  const loadDataRef = useRef(loadData);
  loadDataRef.current = loadData;

  useEffect(() => {
    loadData();
    // Load once on mount — subsequent loads are triggered explicitly
    // (pull-to-refresh, slider release, retry)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleRefresh() {
    didRefetchAfterPendingRef.current = false;
    setIsRefreshing(true);
    loadData();
  }

  function handlePriceChange(value: number) {
    setMaxPrice(value);
    maxPriceRef.current = value;
  }

  function handlePriceChangeEnd(value: number) {
    didRefetchAfterPendingRef.current = false;
    setMaxPrice(value);
    maxPriceRef.current = value;
    setIsFiltering(true);
    loadData(value);
  }

  function handleRetry() {
    didRefetchAfterPendingRef.current = false;
    setIsLoading(true);
    loadData();
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
            {beer.untappd_rating != null && (
              <View style={styles.ratingBadge}>
                <Ionicons name="star" size={12} color="#FFD700" />
                <Text style={styles.ratingText}>{parseFloat(String(beer.untappd_rating)).toFixed(1)}</Text>
              </View>
            )}
            {beer.abv != null && (
              <Text style={styles.abvText}>{beer.abv}%</Text>
            )}
          </View>

          <View style={styles.beerFooter}>
            {beer.price != null && (
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
    if (!beers || beers.length === 0) {
      if (!emptyText) return null;
      return (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{title}</Text>
          <Text style={styles.emptySectionText}>{emptyText}</Text>
        </View>
      );
    }

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

  if (isBuildingProfile) {
    return (
      <View style={styles.centerContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
        <Text style={styles.loadingText}>{t('recommendations.buildingProfile')}</Text>
        <Text style={styles.loadingSubtext}>{t('recommendations.buildingProfileSubtext')}</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.centerContainer}>
        <Ionicons name="alert-circle-outline" size={48} color={colors.error} />
        <Text style={styles.errorText}>{error}</Text>
        <TouchableOpacity style={styles.retryButton} onPress={() => handleRetry()}>
          <Text style={styles.retryButtonText}>{t('common.retry')}</Text>
        </TouchableOpacity>
      </View>
    );
  }

  // Trust the backend's profile_source (it may have fallen back to Shopify
  // even when an Untappd account is linked)
  const profileSource = recommendations?.profile_source
    ?? (untappdProfile ? 'untappd' : 'shopify');
  const hasAnyBeers = !!recommendations && (
    (recommendations.recommendations?.length ?? 0) > 0 ||
    (recommendations.discovery_picks?.length ?? 0) > 0 ||
    (recommendations.tried_beers?.length ?? 0) > 0
  );

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
            name={profileSource === 'untappd' ? 'beer' : 'cart'}
            size={24}
            color={colors.primary}
          />
          <View style={styles.profileInfo}>
            <Text style={styles.profileTitle}>
              {profileSource === 'untappd'
                ? t('recommendations.untappdProfile')
                : t('recommendations.orderHistory')}
            </Text>
            <Text style={styles.profileSubtitle}>
              {profileSource === 'untappd'
                ? (untappdProfile?.username ?? recommendations?.profile_identifier ?? '')
                : t('recommendations.basedOnOrders')}
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

        {!hasAnyBeers ? (
          /* Nothing at all — show the backend's message or a fallback */
          <View style={styles.emptyStateContainer}>
            <Ionicons name="beer-outline" size={48} color={colors.textMuted} />
            <Text style={styles.emptyStateText}>
              {recommendations?.message || t('recommendations.noRecommendations')}
            </Text>
          </View>
        ) : (
          <>
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
          </>
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
  emptySectionText: {
    fontSize: 14,
    color: colors.textMuted,
    marginHorizontal: spacing.md,
  },
  emptyStateContainer: {
    alignItems: 'center',
    padding: spacing.xl,
  },
  emptyStateText: {
    marginTop: spacing.md,
    fontSize: 14,
    color: colors.textMuted,
    textAlign: 'center',
    lineHeight: 20,
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
