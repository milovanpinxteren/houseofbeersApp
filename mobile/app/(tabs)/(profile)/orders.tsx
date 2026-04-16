import { useState, useEffect } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { useAuth } from '../../../src/context/AuthContext';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { getOrders, Order } from '../../../src/api/orders';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';

export default function OrdersScreen() {
  const { user } = useAuth();
  const { language } = useLanguage();
  const [orders, setOrders] = useState<Order[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [expandedOrderId, setExpandedOrderId] = useState<number | null>(null);

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
        <FlatList
          data={orders}
          keyExtractor={(item) => item.id.toString()}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={handleRefresh}
              tintColor={colors.primary}
            />
          }
          renderItem={({ item: order }) => {
            const isExpanded = expandedOrderId === order.id;

            return (
              <TouchableOpacity
                style={styles.orderCard}
                onPress={() => toggleOrderExpanded(order.id)}
                activeOpacity={0.7}
              >
                <View style={styles.orderHeader}>
                  <View style={styles.orderInfo}>
                    <Text style={styles.orderNumber}>{order.name}</Text>
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
                    {order.line_items.map((item) => (
                      <View key={item.id} style={styles.lineItem}>
                        <View style={styles.lineItemInfo}>
                          <Text style={styles.lineItemTitle}>{item.title}</Text>
                          {item.variant_title && (
                            <Text style={styles.lineItemVariant}>{item.variant_title}</Text>
                          )}
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
                  {isExpanded ? t('orders.tapToCollapse') : t('orders.tapToExpand')}
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
