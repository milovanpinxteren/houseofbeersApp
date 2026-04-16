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
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '../../src/context/LanguageContext';
import { t } from '../../src/i18n';
import {
  getFavorites,
  removeFavorite,
  getSelectedCartLink,
  Favorite,
} from '../../src/api/recommendations';
import { colors, spacing, borderRadius } from '../../src/theme/colors';

export default function FavoritesScreen() {
  const { language } = useLanguage();
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
      Alert.alert(t('common.error'), t('recommendations.removeFavoriteError'));
    } finally {
      setRemovingId(null);
    }
  }

  async function handleAddToCart() {
    const idsToAdd = isSelectionMode && selectedIds.size > 0
      ? Array.from(selectedIds)
      : favorites.map((f) => f.id);

    if (idsToAdd.length === 0) {
      Alert.alert(t('common.error'), t('recommendations.noFavoritesSelected'));
      return;
    }

    setIsGeneratingCart(true);
    try {
      const result = await getSelectedCartLink(idsToAdd);
      Linking.openURL(result.cart_url);
    } catch (err) {
      console.log('[Favorites] Cart error:', err);
      Alert.alert(t('common.error'), t('recommendations.cartLinkError'));
    } finally {
      setIsGeneratingCart(false);
    }
  }

  function openProduct(url: string) {
    Linking.openURL(url);
  }

  if (isLoading) {
    return (
      <View style={styles.centerContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
        <Text style={styles.loadingText}>{t('loading')}</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.centerContainer}>
        <Ionicons name="alert-circle-outline" size={48} color={colors.error} />
        <Text style={styles.errorText}>{error}</Text>
      </View>
    );
  }

  if (favorites.length === 0) {
    return (
      <View style={styles.centerContainer}>
        <Ionicons name="heart-outline" size={64} color={colors.textMuted} />
        <Text style={styles.emptyTitle}>{t('recommendations.noFavorites')}</Text>
        <Text style={styles.emptyText}>{t('recommendations.noFavoritesHint')}</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Selection Header */}
      <View style={styles.actionHeader}>
        <TouchableOpacity
          onPress={toggleSelectionMode}
          style={styles.selectButton}
        >
          <Text style={styles.selectButtonText}>
            {isSelectionMode ? t('common.done') : t('common.select')}
          </Text>
        </TouchableOpacity>
        {isSelectionMode && (
          <View style={styles.selectionActions}>
            <TouchableOpacity onPress={selectAll} style={styles.selectionButton}>
              <Text style={styles.selectionButtonText}>{t('common.selectAll')}</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={clearSelection} style={styles.selectionButton}>
              <Text style={styles.selectionButtonText}>{t('common.clearSelection')}</Text>
            </TouchableOpacity>
          </View>
        )}
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
        {isSelectionMode && selectedIds.size > 0 && (
          <Text style={styles.selectionCount}>
            {selectedIds.size} {t('recommendations.selected')}
          </Text>
        )}

        {/* Favorites List */}
        <View style={styles.listContainer}>
          {favorites.map((favorite) => {
            const isSelected = selectedIds.has(favorite.id);
            const isRemoving = removingId === favorite.id;

            return (
              <TouchableOpacity
                key={favorite.id}
                style={[
                  styles.favoriteCard,
                  isSelectionMode && isSelected && styles.favoriteCardSelected,
                ]}
                onPress={() => {
                  if (isSelectionMode) {
                    toggleSelection(favorite.id);
                  } else {
                    openProduct(favorite.product_url);
                  }
                }}
                activeOpacity={0.7}
              >
                {/* Selection Checkbox */}
                {isSelectionMode && (
                  <View style={styles.checkbox}>
                    <Ionicons
                      name={isSelected ? 'checkbox' : 'square-outline'}
                      size={24}
                      color={isSelected ? colors.primary : colors.textMuted}
                    />
                  </View>
                )}

                {/* Beer Image */}
                <View style={styles.imageContainer}>
                  {favorite.image_url ? (
                    <Image
                      source={{ uri: favorite.image_url }}
                      style={styles.beerImage}
                    />
                  ) : (
                    <View style={styles.imagePlaceholder}>
                      <Ionicons name="beer-outline" size={30} color={colors.textMuted} />
                    </View>
                  )}
                </View>

                {/* Beer Info */}
                <View style={styles.infoContainer}>
                  <Text style={styles.beerTitle} numberOfLines={2}>
                    {favorite.title}
                  </Text>
                  <View style={styles.beerMeta}>
                    {favorite.untappd_rating && (
                      <View style={styles.ratingBadge}>
                        <Ionicons name="star" size={12} color="#FFD700" />
                        <Text style={styles.ratingText}>
                          {parseFloat(String(favorite.untappd_rating)).toFixed(1)}
                        </Text>
                      </View>
                    )}
                    {favorite.abv && (
                      <Text style={styles.abvText}>{favorite.abv}%</Text>
                    )}
                    {favorite.style && (
                      <Text style={styles.styleText} numberOfLines={1}>
                        {favorite.style}
                      </Text>
                    )}
                  </View>
                  {favorite.price && (
                    <Text style={styles.priceText}>
                      €{parseFloat(favorite.price).toFixed(2)}
                    </Text>
                  )}
                </View>

                {/* Actions */}
                {!isSelectionMode && (
                  <TouchableOpacity
                    style={styles.removeButton}
                    onPress={() => handleRemoveFavorite(favorite)}
                    disabled={isRemoving}
                  >
                    {isRemoving ? (
                      <ActivityIndicator size="small" color={colors.error} />
                    ) : (
                      <Ionicons name="trash-outline" size={20} color={colors.error} />
                    )}
                  </TouchableOpacity>
                )}
              </TouchableOpacity>
            );
          })}
        </View>

        <View style={styles.bottomPadding} />
      </ScrollView>

      {/* Add to Cart Footer */}
      <View style={styles.footer}>
        <View style={styles.footerInfo}>
          <Text style={styles.footerTitle}>
            {isSelectionMode && selectedIds.size > 0
              ? `${selectedIds.size} ${t('recommendations.beers')}`
              : `${favorites.length} ${t('recommendations.beers')}`}
          </Text>
          <Text style={styles.footerSubtitle}>
            {t('recommendations.addToCartHint')}
          </Text>
        </View>
        <TouchableOpacity
          style={[
            styles.cartButton,
            isGeneratingCart && styles.cartButtonDisabled,
          ]}
          onPress={handleAddToCart}
          disabled={isGeneratingCart}
        >
          {isGeneratingCart ? (
            <ActivityIndicator size="small" color={colors.background} />
          ) : (
            <>
              <Ionicons name="cart" size={20} color={colors.background} />
              <Text style={styles.cartButtonText}>{t('recommendations.addToCart')}</Text>
            </>
          )}
        </TouchableOpacity>
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
    alignItems: 'center',
    backgroundColor: colors.background,
    padding: spacing.lg,
  },
  loadingText: {
    marginTop: spacing.md,
    color: colors.textMuted,
    fontSize: 14,
  },
  errorText: {
    marginTop: spacing.md,
    color: colors.error,
    fontSize: 14,
    textAlign: 'center',
  },
  emptyTitle: {
    marginTop: spacing.md,
    fontSize: 18,
    fontWeight: '600',
    color: colors.text,
  },
  emptyText: {
    marginTop: spacing.xs,
    fontSize: 14,
    color: colors.textMuted,
    textAlign: 'center',
    paddingHorizontal: spacing.xl,
  },

  // Action Header
  actionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.tertiary + '30',
  },
  selectButton: {
    paddingVertical: spacing.xs,
  },
  selectButtonText: {
    color: colors.primary,
    fontSize: 16,
    fontWeight: '600',
  },
  selectionActions: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  selectionButton: {
    paddingVertical: spacing.xs,
  },
  selectionButtonText: {
    fontSize: 14,
    color: colors.primary,
    fontWeight: '500',
  },
  selectionCount: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
  },

  // List
  listContainer: {
    padding: spacing.md,
  },
  favoriteCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  favoriteCardSelected: {
    borderColor: colors.primary,
    backgroundColor: colors.primary + '10',
  },

  // Checkbox
  checkbox: {
    marginRight: spacing.sm,
  },

  // Image
  imageContainer: {
    width: 70,
    height: 70,
    borderRadius: borderRadius.sm,
    overflow: 'hidden',
    backgroundColor: colors.background,
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
    fontSize: 15,
    fontWeight: '600',
    color: colors.text,
    lineHeight: 20,
  },
  beerMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.xs,
    flexWrap: 'wrap',
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
  styleText: {
    fontSize: 12,
    color: colors.textMuted,
    flex: 1,
  },
  priceText: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
    marginTop: spacing.xs,
  },

  // Remove Button
  removeButton: {
    padding: spacing.sm,
    marginLeft: spacing.sm,
  },

  // Footer
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.surface,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.tertiary + '30',
  },
  footerInfo: {
    flex: 1,
  },
  footerTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text,
  },
  footerSubtitle: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
  cartButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: borderRadius.md,
    gap: spacing.xs,
  },
  cartButtonDisabled: {
    opacity: 0.7,
  },
  cartButtonText: {
    color: colors.background,
    fontSize: 16,
    fontWeight: '600',
  },

  bottomPadding: {
    height: spacing.md,
  },
});
