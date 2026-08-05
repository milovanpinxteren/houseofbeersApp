import { useState, useEffect, useCallback, useRef } from 'react';
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ActivityIndicator,
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
import { colors, spacing, borderRadius, fonts, type } from '../../../src/theme/colors';
import { Card, EmptyState, Screen, Skeleton } from '../../../src/components/ui';
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

  function renderBeerCard(item: ScoredBeer) {
    const beer = item.beer;
    const beerId = String(beer.id);
    const isFavorite = favoriteIds.has(beerId);
    const isLoadingThis = loadingFavorite === beerId;

    return (
      <View style={styles.beerCard} key={beerId}>
        <Pressable
          style={({ pressed }) => [styles.beerImageContainer, pressed && styles.pressed]}
          onPress={() => openProduct(beer.product_url)}
        >
          {beer.image_url ? (
            <Image source={{ uri: beer.image_url }} style={styles.beerImage} />
          ) : (
            <View style={styles.beerImagePlaceholder}>
              <Ionicons name="beer-outline" size={40} color={colors.textMuted} />
            </View>
          )}
        </Pressable>

        <View style={styles.beerInfo}>
          <Pressable
            onPress={() => openProduct(beer.product_url)}
            style={({ pressed }) => pressed && styles.pressed}
          >
            <Text style={styles.beerTitle} numberOfLines={2}>{beer.title}</Text>
          </Pressable>

          <View style={styles.beerMeta}>
            {beer.style_category ? (
              <View style={styles.metaChip}>
                <Text style={styles.metaChipText} numberOfLines={1}>
                  {beer.style_category}
                </Text>
              </View>
            ) : null}
            {beer.abv != null && (
              <View style={styles.metaChip}>
                <Text style={styles.metaChipText}>{beer.abv}%</Text>
              </View>
            )}
            {beer.untappd_rating != null && (
              <View style={styles.metaChip}>
                <Ionicons name="star" size={10} color={colors.primary} />
                <Text style={styles.metaChipText}>
                  {parseFloat(String(beer.untappd_rating)).toFixed(1)}
                </Text>
              </View>
            )}
          </View>

          <View style={styles.beerFooter}>
            {beer.price != null ? (
              <Text style={styles.priceText}>€{parseFloat(beer.price).toFixed(2)}</Text>
            ) : (
              <View />
            )}
            <Pressable
              style={({ pressed }) => [styles.favoriteButton, pressed && styles.pressed]}
              onPress={() => toggleFavorite(beer)}
              disabled={isLoadingThis}
              hitSlop={4}
            >
              {isLoadingThis ? (
                <ActivityIndicator size="small" color={colors.primary} />
              ) : (
                <Ionicons
                  name={isFavorite ? 'heart' : 'heart-outline'}
                  size={22}
                  color={isFavorite ? colors.secondary : colors.textMuted}
                />
              )}
            </Pressable>
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
          renderItem={({ item }) => renderBeerCard(item)}
          contentContainerStyle={styles.carouselContent}
        />
      </View>
    );
  }

  if (isLoading) {
    return (
      <Screen scroll={false} padded={false}>
        <View style={styles.loadingHint}>
          <ActivityIndicator size="small" color={colors.primary} />
          <View style={styles.loadingHintText}>
            <Text style={styles.loadingTitle}>{t('recommendations.analyzing')}</Text>
            <Text style={styles.loadingSubtext}>{t('recommendations.analyzingSubtext')}</Text>
          </View>
        </View>
        <View style={styles.skeletonHeader}>
          <Skeleton width="55%" height={16} />
          <Skeleton width="35%" height={12} style={{ marginTop: spacing.sm }} />
        </View>
        {[0, 1].map((row) => (
          <View key={row}>
            <Skeleton
              width={140}
              height={13}
              style={{ marginLeft: spacing.md, marginTop: spacing.lg }}
            />
            <View style={styles.skeletonCarousel}>
              {[0, 1, 2].map((i) => (
                <View key={i} style={styles.skeletonBeerCard}>
                  <Skeleton width={168} height={150} radius={0} />
                  <View style={{ padding: spacing.sm + spacing.xs }}>
                    <Skeleton width="85%" height={13} />
                    <Skeleton width="50%" height={11} style={{ marginTop: spacing.sm }} />
                  </View>
                </View>
              ))}
            </View>
          </View>
        ))}
      </Screen>
    );
  }

  if (isBuildingProfile) {
    return (
      <Screen scroll={false}>
        <View style={styles.centerContainer}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.buildingTitle}>{t('recommendations.buildingProfile')}</Text>
          <Text style={styles.buildingSubtext}>{t('recommendations.buildingProfileSubtext')}</Text>
        </View>
      </Screen>
    );
  }

  if (error) {
    return (
      <Screen scroll={false}>
        <View style={styles.centerContainer}>
          <EmptyState
            icon="alert-circle-outline"
            title={t('common.error')}
            message={error}
            actionLabel={t('common.retry')}
            onAction={handleRetry}
          />
        </View>
      </Screen>
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
    <Screen padded={false} refreshing={isRefreshing} onRefresh={handleRefresh}>
      {/* Profile source + quick stats */}
      <Card variant="elevated" style={styles.headerCard} padded={false}>
        <View style={styles.profileRow}>
          <View style={styles.profileIconWrap}>
            <Ionicons
              name={profileSource === 'untappd' ? 'beer' : 'cart'}
              size={20}
              color={colors.primary}
            />
          </View>
          <View style={styles.profileInfo}>
            <Text style={styles.profileLabel}>
              {profileSource === 'untappd'
                ? t('recommendations.untappdProfile')
                : t('recommendations.orderHistory')}
            </Text>
            <Text style={styles.profileValue} numberOfLines={1}>
              {profileSource === 'untappd'
                ? (untappdProfile?.username ?? recommendations?.profile_identifier ?? '')
                : t('recommendations.basedOnOrders')}
            </Text>
          </View>
        </View>

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
              <Text style={styles.quickStatValue} numberOfLines={1}>
                {recommendations.profile_summary.preferred_styles?.[0] || '-'}
              </Text>
              <Text style={styles.quickStatLabel}>{t('recommendations.topStyle')}</Text>
            </View>
          </View>
        )}
      </Card>

      {/* Price Filter */}
      <Card style={styles.filterCard}>
        <View style={styles.filterHeader}>
          <View style={styles.filterLabelRow}>
            <Ionicons name="pricetag-outline" size={15} color={colors.primary} />
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
      </Card>

      {!hasAnyBeers ? (
        /* Nothing at all — show the backend's message or a fallback */
        <EmptyState
          icon="beer-outline"
          title={t('recommendations.noRecommendations')}
          message={recommendations?.message || undefined}
        />
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
    </Screen>
  );
}

const styles = StyleSheet.create({
  pressed: {
    opacity: 0.85,
  },
  centerContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },

  // Loading skeletons
  loadingHint: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
  },
  loadingHintText: {
    flex: 1,
  },
  loadingTitle: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.4,
    color: colors.text,
  },
  loadingSubtext: {
    fontFamily: fonts.serif,
    fontSize: 15,
    color: colors.textMuted,
    marginTop: 1,
  },
  skeletonHeader: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
  },
  skeletonCarousel: {
    flexDirection: 'row',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    marginTop: spacing.sm,
  },
  skeletonBeerCard: {
    width: 168,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    overflow: 'hidden',
  },

  // Building profile
  buildingTitle: {
    fontFamily: fonts.heading,
    fontSize: 18,
    letterSpacing: 0.4,
    color: colors.text,
    marginTop: spacing.md,
    textAlign: 'center',
  },
  buildingSubtext: {
    fontFamily: fonts.serif,
    fontSize: 16,
    lineHeight: 22,
    color: colors.textMuted,
    marginTop: spacing.xs,
    textAlign: 'center',
    maxWidth: 280,
  },

  // Header card (source + stats)
  headerCard: {
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
  },
  profileRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
  },
  profileIconWrap: {
    width: 42,
    height: 42,
    borderRadius: 14,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  profileInfo: {
    flex: 1,
  },
  profileLabel: {
    ...type.label,
    fontSize: 11,
    letterSpacing: 1.4,
  },
  profileValue: {
    fontFamily: fonts.heading,
    fontSize: 16,
    letterSpacing: 0.4,
    color: colors.text,
    marginTop: 1,
  },
  quickStats: {
    flexDirection: 'row',
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
  },
  quickStat: {
    flex: 1,
    alignItems: 'center',
  },
  quickStatValue: {
    fontFamily: fonts.headingBold,
    fontSize: 18,
    letterSpacing: 0.4,
    color: colors.primary,
  },
  quickStatLabel: {
    fontSize: 11,
    color: colors.textMuted,
    marginTop: 2,
  },
  quickStatDivider: {
    width: StyleSheet.hairlineWidth,
    backgroundColor: colors.border,
    marginHorizontal: spacing.md,
  },

  // Price Filter
  filterCard: {
    marginHorizontal: spacing.md,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
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
    ...type.label,
    fontSize: 12,
    letterSpacing: 1.4,
  },
  priceValueRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  filterSpinner: {
    marginRight: spacing.sm,
  },
  priceValue: {
    fontFamily: fonts.heading,
    fontSize: 16,
    letterSpacing: 0.4,
    color: colors.primary,
  },

  // Sections
  section: {
    marginTop: spacing.lg,
  },
  sectionTitle: {
    ...type.label,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  carouselContent: {
    paddingHorizontal: spacing.md,
  },
  emptySectionText: {
    fontFamily: fonts.serif,
    fontSize: 15,
    color: colors.textMuted,
    marginHorizontal: spacing.md,
  },

  // Beer Cards
  beerCard: {
    width: 168,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    marginRight: spacing.sm,
    overflow: 'hidden',
  },
  beerImageContainer: {
    width: '100%',
    aspectRatio: 1,
    backgroundColor: colors.surfaceLow,
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
    padding: spacing.sm + spacing.xs,
  },
  beerTitle: {
    fontFamily: fonts.heading,
    fontSize: 14,
    letterSpacing: 0.3,
    lineHeight: 19,
    color: colors.text,
    minHeight: 38,
  },
  beerMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: spacing.xs,
    marginTop: spacing.sm,
  },
  metaChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: colors.surfaceHigh,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.pill,
    maxWidth: 148,
  },
  metaChipText: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    color: colors.textMuted,
  },
  beerFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: spacing.sm,
  },
  priceText: {
    fontFamily: fonts.heading,
    fontSize: 16,
    letterSpacing: 0.4,
    color: colors.primary,
  },
  favoriteButton: {
    width: 40,
    height: 40,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: -spacing.xs,
    marginBottom: -spacing.xs,
  },
});
