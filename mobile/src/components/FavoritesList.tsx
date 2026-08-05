import { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  ScrollView,
  Pressable,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
  Image,
  Linking,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useLanguage } from '../context/LanguageContext';
import { t } from '../i18n';
import {
  getFavorites,
  removeFavorite,
  getSelectedCartLink,
  Favorite,
} from '../api/recommendations';
import { colors, spacing, borderRadius, fonts, type } from '../theme/colors';
import { Button, Card, EmptyState, Skeleton, useToast } from './ui';

export default function FavoritesList() {
  const router = useRouter();
  const { language } = useLanguage();
  const { showToast } = useToast();
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [favorites, setFavorites] = useState<Favorite[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [isSelectionMode, setIsSelectionMode] = useState(false);
  const [isGeneratingCart, setIsGeneratingCart] = useState(false);
  const [removingId, setRemovingId] = useState<number | null>(null);

  const loadData = useCallback(async () => {
    try {
      setError('');
      const data = await getFavorites();
      setFavorites(data.favorites);
    } catch (err) {
      console.log('[Favorites] Error:', err);
      setError(err instanceof Error ? err.message : t('recommendations.loadError'));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  function handleRefresh() {
    setIsRefreshing(true);
    loadData();
  }

  function handleRetry() {
    setIsLoading(true);
    loadData();
  }

  function toggleSelection(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function selectAll() {
    setSelectedIds(new Set(favorites.map((f) => f.id)));
  }

  function clearSelection() {
    setSelectedIds(new Set());
  }

  function toggleSelectionMode() {
    if (isSelectionMode) {
      setSelectedIds(new Set());
    }
    setIsSelectionMode(!isSelectionMode);
  }

  async function handleRemoveFavorite(favorite: Favorite) {
    setRemovingId(favorite.id);
    try {
      await removeFavorite(favorite.id);
      setFavorites((prev) => prev.filter((f) => f.id !== favorite.id));
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(favorite.id);
        return next;
      });
    } catch (err) {
      console.log('[Favorites] Remove error:', err);
      showToast(t('recommendations.removeFavoriteError'), 'error');
    } finally {
      setRemovingId(null);
    }
  }

  async function handleAddToCart() {
    const idsToAdd = isSelectionMode && selectedIds.size > 0
      ? Array.from(selectedIds)
      : favorites.map((f) => f.id);

    if (idsToAdd.length === 0) {
      showToast(t('recommendations.noFavoritesSelected'), 'info');
      return;
    }

    setIsGeneratingCart(true);
    try {
      const result = await getSelectedCartLink(idsToAdd);
      Linking.openURL(result.cart_url);
    } catch (err) {
      console.log('[Favorites] Cart error:', err);
      showToast(t('recommendations.cartLinkError'), 'error');
    } finally {
      setIsGeneratingCart(false);
    }
  }

  function openProduct(url: string) {
    Linking.openURL(url);
  }

  if (isLoading) {
    return (
      <View style={styles.container}>
        <View style={styles.skeletonList}>
          {[0, 1, 2, 3, 4].map((i) => (
            <View key={i} style={styles.skeletonRow}>
              <Skeleton width={72} height={72} radius={borderRadius.md} />
              <View style={styles.skeletonLines}>
                <Skeleton width="72%" height={14} />
                <Skeleton width="48%" height={12} style={{ marginTop: spacing.sm }} />
                <Skeleton width="28%" height={12} style={{ marginTop: spacing.xs }} />
              </View>
            </View>
          ))}
        </View>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.centerContainer}>
        <EmptyState
          icon="alert-circle-outline"
          title={t('common.error')}
          message={error}
          actionLabel={t('common.retry')}
          onAction={handleRetry}
        />
      </View>
    );
  }

  if (favorites.length === 0) {
    return (
      <View style={styles.centerContainer}>
        <EmptyState
          icon="heart-outline"
          title={t('recommendations.noFavorites')}
          message={t('recommendations.noFavoritesHint')}
          actionLabel={t('recommendations.goToRecommendations')}
          onAction={() => router.push('/(profile)/recommendations' as any)}
        />
      </View>
    );
  }

  const selectionActive = isSelectionMode && selectedIds.size > 0;

  return (
    <View style={styles.container}>
      {/* Count + selection controls */}
      <View style={styles.actionHeader}>
        <Text style={styles.countLabel}>
          {selectionActive
            ? `${selectedIds.size} ${t('recommendations.selected')}`
            : `${favorites.length} ${t('recommendations.beers')}`}
        </Text>
        <View style={styles.selectionActions}>
          {isSelectionMode && (
            <>
              <Pressable
                onPress={selectAll}
                hitSlop={8}
                style={({ pressed }) => [styles.selectionButton, pressed && styles.pressed]}
              >
                <Text style={styles.selectionButtonText}>{t('common.selectAll')}</Text>
              </Pressable>
              <Pressable
                onPress={clearSelection}
                hitSlop={8}
                style={({ pressed }) => [styles.selectionButton, pressed && styles.pressed]}
              >
                <Text style={styles.selectionButtonText}>{t('common.clearSelection')}</Text>
              </Pressable>
            </>
          )}
          <Pressable
            onPress={toggleSelectionMode}
            hitSlop={8}
            style={({ pressed }) => [styles.selectionButton, pressed && styles.pressed]}
          >
            <Text style={styles.selectToggleText}>
              {isSelectionMode ? t('common.done') : t('common.select')}
            </Text>
          </Pressable>
        </View>
      </View>

      <ScrollView
        style={styles.scrollView}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={handleRefresh}
            tintColor={colors.primary}
          />
        }
      >
        {/* Favorites List */}
        <View style={styles.listContainer}>
          {favorites.map((favorite) => {
            const isSelected = selectedIds.has(favorite.id);
            const isRemoving = removingId === favorite.id;
            const breweryLine = [favorite.vendor, favorite.style]
              .filter(Boolean)
              .join(' · ');

            return (
              <Card
                key={favorite.id}
                padded={false}
                onPress={() => {
                  if (isSelectionMode) {
                    toggleSelection(favorite.id);
                  } else {
                    openProduct(favorite.product_url);
                  }
                }}
                style={[
                  styles.favoriteCard,
                  isSelectionMode && isSelected && styles.favoriteCardSelected,
                ]}
              >
                <View style={styles.cardRow}>
                  {/* Selection checkbox */}
                  {isSelectionMode && (
                    <Ionicons
                      name={isSelected ? 'checkbox' : 'square-outline'}
                      size={24}
                      color={isSelected ? colors.primary : colors.textMuted}
                      style={styles.checkbox}
                    />
                  )}

                  {/* Beer image */}
                  <View style={styles.imageContainer}>
                    {favorite.image_url ? (
                      <Image
                        source={{ uri: favorite.image_url }}
                        style={styles.beerImage}
                      />
                    ) : (
                      <View style={styles.imagePlaceholder}>
                        <Ionicons name="beer-outline" size={28} color={colors.textMuted} />
                      </View>
                    )}
                  </View>

                  {/* Beer info */}
                  <View style={styles.infoContainer}>
                    <Text style={styles.beerTitle} numberOfLines={2}>
                      {favorite.title}
                    </Text>
                    {breweryLine ? (
                      <Text style={styles.breweryLine} numberOfLines={1}>
                        {breweryLine}
                      </Text>
                    ) : null}
                    <View style={styles.beerMeta}>
                      {favorite.untappd_rating != null && (
                        <View style={styles.metaChip}>
                          <Ionicons name="star" size={11} color={colors.primary} />
                          <Text style={styles.metaChipText}>
                            {parseFloat(String(favorite.untappd_rating)).toFixed(1)}
                          </Text>
                        </View>
                      )}
                      {favorite.abv != null && (
                        <View style={styles.metaChip}>
                          <Text style={styles.metaChipText}>{favorite.abv}%</Text>
                        </View>
                      )}
                      {favorite.price != null && (
                        <Text style={styles.priceText}>
                          €{parseFloat(favorite.price).toFixed(2)}
                        </Text>
                      )}
                    </View>
                  </View>

                  {/* Remove (heart) */}
                  {!isSelectionMode && (
                    <Pressable
                      onPress={() => handleRemoveFavorite(favorite)}
                      disabled={isRemoving}
                      hitSlop={4}
                      style={({ pressed }) => [
                        styles.heartButton,
                        pressed && styles.pressed,
                      ]}
                    >
                      {isRemoving ? (
                        <ActivityIndicator size="small" color={colors.secondary} />
                      ) : (
                        <Ionicons name="heart" size={22} color={colors.secondary} />
                      )}
                    </Pressable>
                  )}
                </View>
              </Card>
            );
          })}
        </View>

        <View style={styles.bottomPadding} />
      </ScrollView>

      {/* Add to Cart footer */}
      <View style={styles.footer}>
        <View style={styles.footerInfo}>
          <Text style={styles.footerTitle}>
            {selectionActive
              ? `${selectedIds.size} ${t('recommendations.beers')}`
              : `${favorites.length} ${t('recommendations.beers')}`}
          </Text>
          <Text style={styles.footerSubtitle}>
            {t('recommendations.addToCartHint')}
          </Text>
        </View>
        <Button
          label={t('recommendations.addToCart')}
          icon="cart"
          onPress={handleAddToCart}
          loading={isGeneratingCart}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  scrollView: {
    flex: 1,
  },
  centerContainer: {
    flex: 1,
    justifyContent: 'center',
    backgroundColor: colors.background,
    padding: spacing.lg,
  },
  pressed: {
    opacity: 0.7,
  },

  // Skeletons
  skeletonList: {
    padding: spacing.md,
    gap: spacing.sm,
  },
  skeletonRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
  },
  skeletonLines: {
    flex: 1,
  },

  // Action Header
  actionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
    paddingBottom: spacing.xs,
  },
  countLabel: {
    ...type.label,
  },
  selectionActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  selectionButton: {
    paddingVertical: spacing.xs,
    minHeight: 32,
    justifyContent: 'center',
  },
  selectionButtonText: {
    fontSize: 13,
    color: colors.textMuted,
    fontWeight: '500',
  },
  selectToggleText: {
    fontFamily: fonts.heading,
    fontSize: 13,
    letterSpacing: 1,
    textTransform: 'uppercase',
    color: colors.primary,
  },

  // List
  listContainer: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
  },
  favoriteCard: {
    marginBottom: spacing.sm,
  },
  favoriteCardSelected: {
    backgroundColor: colors.surfaceHigh,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  cardRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.sm + spacing.xs,
  },
  checkbox: {
    marginRight: spacing.sm,
  },

  // Image
  imageContainer: {
    width: 72,
    height: 72,
    borderRadius: borderRadius.md,
    overflow: 'hidden',
    backgroundColor: colors.surfaceLow,
  },
  beerImage: {
    width: '100%',
    height: '100%',
    resizeMode: 'cover',
  },
  imagePlaceholder: {
    width: '100%',
    height: '100%',
    justifyContent: 'center',
    alignItems: 'center',
  },

  // Info
  infoContainer: {
    flex: 1,
    marginLeft: spacing.md,
  },
  beerTitle: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.3,
    lineHeight: 20,
    color: colors.text,
  },
  breweryLine: {
    fontFamily: fonts.serif,
    fontSize: 15,
    lineHeight: 19,
    color: colors.textMuted,
    marginTop: 2,
  },
  beerMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.sm,
    flexWrap: 'wrap',
  },
  metaChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: colors.surfaceHigh,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.pill,
  },
  metaChipText: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 0.4,
    color: colors.textMuted,
  },
  priceText: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.4,
    color: colors.primary,
  },

  // Heart / remove
  heartButton: {
    width: 44,
    height: 44,
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: spacing.xs,
  },

  // Footer
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.md,
    backgroundColor: colors.surfaceHigh,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    borderTopLeftRadius: borderRadius.lg,
    borderTopRightRadius: borderRadius.lg,
  },
  footerInfo: {
    flex: 1,
  },
  footerTitle: {
    fontFamily: fonts.heading,
    fontSize: 16,
    letterSpacing: 0.4,
    color: colors.text,
  },
  footerSubtitle: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },

  bottomPadding: {
    height: spacing.md,
  },
});
