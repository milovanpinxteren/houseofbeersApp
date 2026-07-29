import { useState, useEffect, useMemo } from 'react';
import {
  View,
  Text,
  FlatList,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../../../src/context/AuthContext';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { getOrders, Order } from '../../../src/api/orders';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
import { tokenize, highlightRanges } from '../../../src/utils/fuzzySearch';
import {
  buildOrderSearchIndex,
  searchOrders,
  countMatchedItems,
} from '../../../src/utils/orderSearch';

/** Renders text with the matched portions emphasised. */
function Highlighted({
  text,
  tokens,
  style,
}: {
  text: string;
  tokens: string[];
  style?: any;
}) {
  const ranges = tokens.length ? highlightRanges(tokens, text) : [];
  if (!ranges.length) return <Text style={style}>{text}</Text>;

  const parts = [];
  let cursor = 0;
  ranges.forEach((range, i) => {
    if (range.start > cursor) {
      parts.push(<Text key={`p${i}`}>{text.slice(cursor, range.start)}</Text>);
    }
    parts.push(
      <Text key={`h${i}`} style={styles.highlight}>
        {text.slice(range.start, range.end)}
      </Text>
    );
    cursor = range.end;
  });
  if (cursor < text.length) parts.push(<Text key="tail">{text.slice(cursor)}</Text>);

  return <Text style={style}>{parts}</Text>;
}


export default function OrdersScreen() {
  const { user } = useAuth();
  const { language } = useLanguage();
  const [orders, setOrders] = useState<Order[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [expandedOrderId, setExpandedOrderId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  // While searching, matching items are shown automatically; this tracks orders
  // where the user asked to see the full item list instead.
  const [showAllItemsFor, setShowAllItemsFor] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (user?.shopify_customer_id) {
      loadOrders();
    } else {
      setIsLoading(false);
    }
  }, [user?.shopify_customer_id]);

  async function loadOrders() {
    try {
      setError('');
      const data = await getOrders();
      setOrders(data);
    } catch (err) {
      console.log('[Orders] Error:', err);
      setError(err instanceof Error ? err.message : 'Failed to load orders');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }

  function handleRefresh() {
    setIsRefreshing(true);
    loadOrders();
  }

  function toggleOrderExpanded(orderId: number) {
    setExpandedOrderId(expandedOrderId === orderId ? null : orderId);
  }

  function toggleShowAllItems(orderId: number) {
    setShowAllItemsFor((prev) => {
      const next = new Set(prev);
      if (next.has(orderId)) next.delete(orderId);
      else next.add(orderId);
      return next;
    });
  }

  const searchIndex = useMemo(
    () => buildOrderSearchIndex(orders, formatDate),
    // formatDate is locale-dependent, so the date haystack is rebuilt on
    // language change.
    [orders, language]
  );

  const queryTokens = useMemo(() => tokenize(searchQuery), [searchQuery]);
  const isSearching = queryTokens.length > 0;

  const matches = useMemo(
    () => searchOrders(searchIndex, queryTokens),
    [searchIndex, queryTokens]
  );

  const matchedItemCount = useMemo(
    () => (isSearching ? countMatchedItems(matches) : 0),
    [matches, isSearching]
  );

  function formatDate(dateString: string): string {
    const date = new Date(dateString);
    const locale = language === 'nl' ? 'nl-NL' : 'en-US';
    return date.toLocaleDateString(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  }

  function formatPrice(price: string, currency: string): string {
    const locale = language === 'nl' ? 'nl-NL' : 'en-US';
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: currency,
    }).format(parseFloat(price));
  }

  function getStatusColor(status: string | null): string {
    switch (status) {
      case 'paid':
        return colors.success;
      case 'pending':
        return colors.warning;
      case 'refunded':
      case 'voided':
        return colors.error;
      default:
        return colors.textMuted;
    }
  }

  function getFulfillmentLabel(status: string | null): string {
    switch (status) {
      case 'fulfilled':
        return t('orders.delivered');
      case 'partial':
        return t('orders.partiallyShipped');
      case null:
        return t('orders.processing');
      default:
        return status;
    }
  }

  function getItemsLabel(count: number): string {
    if (count === 1) {
      return `1 ${t('orders.item')}`;
    }
    return `${count} ${t('orders.items')}`;
  }

  function getOrdersLabel(count: number): string {
    return count === 1
      ? `1 ${t('orders.order')}`
      : `${count} ${t('orders.ordersPlural')}`;
  }

  /**
   * Matching an order number matches no individual items, so reporting
   * "0 items" there would be wrong — show just the order count instead.
   */
  function getResultSummary(): string {
    const ordersLabel = getOrdersLabel(matches.length);
    if (matchedItemCount === 0) return ordersLabel;
    return t('orders.resultSummary', {
      items: getItemsLabel(matchedItemCount),
      orders: ordersLabel,
    });
  }

  function getItemFulfillmentLabel(status: string | null): string {
    switch (status) {
      case 'fulfilled':
        return t('orders.itemFulfilled');
      case 'partial':
        return t('orders.itemPartial');
      default:
        return t('orders.itemUnfulfilled');
    }
  }

  function getItemFulfillmentColor(status: string | null): string {
    switch (status) {
      case 'fulfilled':
        return colors.success;
      case 'partial':
        return colors.warning;
      default:
        return colors.textMuted;
    }
  }

  if (!user?.shopify_customer_id) {
    return (
      <View style={styles.centerContainer}>
        <Text style={styles.emptyTitle}>{t('orders.noShopifyTitle')}</Text>
        <Text style={styles.emptyText}>{t('orders.noShopifyText')}</Text>
      </View>
    );
  }

  if (isLoading) {
    return (
      <View style={styles.centerContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
        <Text style={styles.loadingText}>{t('orders.loading')}</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.centerContainer}>
        <Text style={styles.errorText}>{error}</Text>
        <TouchableOpacity style={styles.retryButton} onPress={loadOrders}>
          <Text style={styles.retryButtonText}>{t('retry')}</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (orders.length === 0) {
    return (
      <View style={styles.centerContainer}>
        <Text style={styles.emptyTitle}>{t('orders.noOrdersTitle')}</Text>
        <Text style={styles.emptyText}>{t('orders.noOrdersText')}</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
        <View style={styles.searchBar}>
          <Ionicons name="search" size={18} color={colors.textMuted} />
          <TextInput
            style={styles.searchInput}
            placeholder={t('orders.searchPlaceholder')}
            placeholderTextColor={colors.textMuted}
            value={searchQuery}
            onChangeText={setSearchQuery}
            autoCorrect={false}
            autoCapitalize="none"
            returnKeyType="search"
            clearButtonMode="never"
          />
          {searchQuery ? (
            <TouchableOpacity
              onPress={() => setSearchQuery('')}
              hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
            >
              <Ionicons name="close-circle" size={18} color={colors.textMuted} />
            </TouchableOpacity>
          ) : null}
        </View>

        {/* Zero matches are covered by the list's empty state below. */}
        {isSearching && matches.length > 0 && (
          <Text style={styles.resultSummary}>{getResultSummary()}</Text>
        )}

        <FlatList
          data={matches}
          keyExtractor={(m) => m.order.id.toString()}
          keyboardShouldPersistTaps="handled"
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={handleRefresh}
              tintColor={colors.primary}
            />
          }
          ListEmptyComponent={
            isSearching ? (
              <View style={styles.noResults}>
                <Ionicons name="search" size={40} color={colors.textMuted} />
                <Text style={styles.emptyTitle}>{t('orders.noResultsTitle')}</Text>
                <Text style={styles.emptyText}>
                  {t('orders.noResultsText', { query: searchQuery })}
                </Text>
              </View>
            ) : null
          }
          renderItem={({ item: match }) => {
            const order = match.order;
            const showingAll = showAllItemsFor.has(order.id);
            // While searching the matches are always visible — hiding them
            // behind a tap would defeat the point of the search.
            const isExpanded = isSearching ? true : expandedOrderId === order.id;
            const hiddenItemCount = order.line_items.length - match.matchedItems.length;
            const visibleItems =
              isSearching && !showingAll ? match.matchedItems : order.line_items;

            return (
              <TouchableOpacity
                style={styles.orderCard}
                onPress={() =>
                  isSearching ? toggleShowAllItems(order.id) : toggleOrderExpanded(order.id)
                }
                activeOpacity={0.7}
              >
                <View style={styles.orderHeader}>
                  <View style={styles.orderInfo}>
                    <Highlighted
                      text={order.name}
                      tokens={queryTokens}
                      style={styles.orderNumber}
                    />
                    <Text style={styles.orderDate}>{formatDate(order.created_at)}</Text>
                  </View>
                  <View style={styles.orderTotal}>
                    <Text style={styles.totalPrice}>
                      {formatPrice(order.total_price, order.currency)}
                    </Text>
                    <View
                      style={[
                        styles.statusBadge,
                        { backgroundColor: getStatusColor(order.financial_status) + '20' },
                      ]}
                    >
                      <Text
                        style={[
                          styles.statusText,
                          { color: getStatusColor(order.financial_status) },
                        ]}
                      >
                        {order.financial_status}
                      </Text>
                    </View>
                  </View>
                </View>

                <View style={styles.fulfillmentRow}>
                  <Text style={styles.fulfillmentLabel}>
                    {getFulfillmentLabel(order.fulfillment_status)}
                  </Text>
                  <Text style={styles.itemCount}>
                    {getItemsLabel(order.line_items.length)}
                  </Text>
                </View>

                {isExpanded && (
                  <View style={styles.lineItemsContainer}>
                    <View style={styles.divider} />
                    {visibleItems.map((item) => (
                      <View key={item.id} style={styles.lineItem}>
                        <View style={styles.lineItemInfo}>
                          <Highlighted
                            text={item.title}
                            tokens={queryTokens}
                            style={styles.lineItemTitle}
                          />
                          {item.variant_title && (
                            <Highlighted
                              text={item.variant_title}
                              tokens={queryTokens}
                              style={styles.lineItemVariant}
                            />
                          )}
                          <View
                            style={[
                              styles.itemFulfillmentBadge,
                              { backgroundColor: getItemFulfillmentColor(item.fulfillment_status) + '20' },
                            ]}
                          >
                            <View
                              style={[
                                styles.itemFulfillmentDot,
                                { backgroundColor: getItemFulfillmentColor(item.fulfillment_status) },
                              ]}
                            />
                            <Text
                              style={[
                                styles.itemFulfillmentText,
                                { color: getItemFulfillmentColor(item.fulfillment_status) },
                              ]}
                            >
                              {getItemFulfillmentLabel(item.fulfillment_status)}
                            </Text>
                          </View>
                          {item.estimated_delivery_date && (
                            <Text style={styles.estimatedDelivery}>
                              {t('orders.estimatedDelivery')}: {item.estimated_delivery_date}
                            </Text>
                          )}
                        </View>
                        <View style={styles.lineItemRight}>
                          <Text style={styles.lineItemQty}>x{item.quantity}</Text>
                          <Text style={styles.lineItemPrice}>
                            {formatPrice(item.price, order.currency)}
                          </Text>
                        </View>
                      </View>
                    ))}
                  </View>
                )}

                <Text style={styles.expandHint}>
                  {!isSearching
                    ? isExpanded
                      ? t('orders.tapToCollapse')
                      : t('orders.tapToExpand')
                    : showingAll
                    ? t('orders.tapToShowMatchesOnly')
                    : hiddenItemCount > 0
                    ? t('orders.tapToShowAllItems', { count: hiddenItemCount })
                    : ''}
                </Text>
              </TouchableOpacity>
            );
          }}
          contentContainerStyle={styles.listContent}
        />
      </View>
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
    padding: spacing.xl,
    backgroundColor: colors.background,
  },
  listContent: {
    padding: spacing.md,
  },
  searchBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surface,
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  searchInput: {
    flex: 1,
    color: colors.text,
    fontSize: 15,
    // Keeps the row height stable across platforms while typing.
    paddingVertical: 2,
  },
  resultSummary: {
    color: colors.textMuted,
    fontSize: 13,
    marginTop: spacing.sm,
    marginHorizontal: spacing.md,
  },
  noResults: {
    alignItems: 'center',
    paddingTop: 60,
    paddingHorizontal: spacing.xl,
    gap: spacing.sm,
  },
  highlight: {
    color: colors.primary,
    fontWeight: '700',
  },
  loadingText: {
    marginTop: spacing.md,
    color: colors.textMuted,
    fontSize: 14,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.sm,
  },
  emptyText: {
    fontSize: 14,
    color: colors.textMuted,
    textAlign: 'center',
  },
  errorText: {
    fontSize: 14,
    color: colors.error,
    textAlign: 'center',
    marginBottom: spacing.md,
  },
  retryButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
  },
  retryButtonText: {
    color: colors.background,
    fontSize: 14,
    fontWeight: '600',
  },
  orderCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  orderHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  orderInfo: {
    flex: 1,
  },
  orderNumber: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.primary,
  },
  orderDate: {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: 2,
  },
  orderTotal: {
    alignItems: 'flex-end',
  },
  totalPrice: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text,
  },
  statusBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
    marginTop: 4,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'capitalize',
  },
  fulfillmentRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: spacing.sm,
  },
  fulfillmentLabel: {
    fontSize: 13,
    color: colors.textMuted,
  },
  itemCount: {
    fontSize: 13,
    color: colors.textMuted,
  },
  lineItemsContainer: {
    marginTop: spacing.sm,
  },
  divider: {
    height: 1,
    backgroundColor: colors.tertiary + '30',
    marginBottom: spacing.sm,
  },
  lineItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.tertiary + '15',
  },
  lineItemInfo: {
    flex: 1,
    marginRight: spacing.md,
  },
  lineItemTitle: {
    fontSize: 14,
    color: colors.text,
  },
  lineItemVariant: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
  itemFulfillmentBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
    marginTop: 4,
  },
  itemFulfillmentDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    marginRight: 4,
  },
  itemFulfillmentText: {
    fontSize: 11,
    fontWeight: '600',
  },
  estimatedDelivery: {
    fontSize: 12,
    color: colors.primary,
    marginTop: 4,
  },
  lineItemRight: {
    alignItems: 'flex-end',
  },
  lineItemQty: {
    fontSize: 13,
    color: colors.textMuted,
  },
  lineItemPrice: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
  },
  expandHint: {
    fontSize: 11,
    color: colors.textMuted,
    textAlign: 'center',
    marginTop: spacing.sm,
  },
});
