import { useState, useEffect, useMemo, ReactNode } from 'react';
import {
  View,
  Text,
  FlatList,
  TextInput,
  Pressable,
  StyleSheet,
  RefreshControl,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { useAuth } from '../../../src/context/AuthContext';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import {
  getOrders,
  Order,
  DraftOrder,
  MissedSale,
} from '../../../src/api/orders';
import { colors, spacing, borderRadius, fonts } from '../../../src/theme/colors';
import { EmptyState, SkeletonCard } from '../../../src/components/ui';
import { PickupSection } from '../../../src/components/PickupSection';
import { DraftOrdersSection } from '../../../src/components/DraftOrdersSection';
import { MissedItemsBlock } from '../../../src/components/MissedItemsBlock';
import { MissedSalesSection } from '../../../src/components/MissedSalesSection';
import {
  ItemStateBadge,
  formatShortDate,
} from '../../../src/components/ItemStateBadge';
import { tokenize, highlightRanges } from '../../../src/utils/fuzzySearch';
import {
  buildOrderSearchIndex,
  searchOrders,
  countMatchedItems,
  filterMatchesByState,
  countItemsByState,
  filterMatchesByPeriod,
  orderStateSummary,
  orderYears,
  threeMonthsBefore,
  periodForYear,
  PERIOD_ALL,
  PERIOD_3M,
  ITEM_STATE_FILTERS,
  StateFilter,
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


/** A labelled row of chips inside the filter panel. */
function FilterGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <View style={styles.filterGroup}>
      <Text style={styles.filterGroupLabel}>{label}</Text>
      <View style={styles.filterRow}>{children}</View>
    </View>
  );
}

/** One filter chip. */
function FilterChip({
  label,
  count,
  active,
  onPress,
}: {
  label: string;
  count?: number;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      style={({ pressed }) => [
        styles.filterChip,
        active && styles.filterChipActive,
        pressed && styles.pressed,
      ]}
    >
      <Text style={[styles.filterChipText, active && styles.filterChipTextActive]}>
        {label}
        {count !== undefined ? ` ${count}` : ''}
      </Text>
    </Pressable>
  );
}

/** One "dot + text" segment of the collapsed card's status roll-up. */
function RollupSegment({ color, text }: { color: string; text: string }) {
  return (
    <View style={styles.rollupSegment}>
      <View style={[styles.rollupDot, { backgroundColor: color }]} />
      <Text style={[styles.rollupText, { color }]}>{text}</Text>
    </View>
  );
}

export default function OrdersScreen() {
  const { user } = useAuth();
  const { language } = useLanguage();
  // /pickup deep link lands here with ?pickup=1 → open the RSVP section.
  // ?missed=1 mirrors it for the missed section: a future push notification
  // "je hebt bieren gemist" deep-links to /orders?missed=1 and lands on the
  // open answer.
  const { pickup, missed: missedParam } = useLocalSearchParams<{
    pickup?: string;
    missed?: string;
  }>();
  const [orders, setOrders] = useState<Order[]>([]);
  const [drafts, setDrafts] = useState<DraftOrder[]>([]);
  const [missed, setMissed] = useState<MissedSale[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [expandedOrderId, setExpandedOrderId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [stateFilter, setStateFilter] = useState<StateFilter>('all');
  const [periodFilter, setPeriodFilter] = useState<string>(PERIOD_ALL);
  const [filtersOpen, setFiltersOpen] = useState(false);
  // While searching or filtering, matching items are shown automatically; this
  // tracks orders where the user asked to see the full item list instead.
  const [showAllItemsFor, setShowAllItemsFor] = useState<Set<number>>(new Set());
  // Bumped on pull-to-refresh so the pickup section refetches with the orders.
  const [pickupRefresh, setPickupRefresh] = useState(0);

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
      setOrders(data.orders ?? []);
      setDrafts(data.drafts ?? []);
      setMissed(data.missed ?? []);
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
    setPickupRefresh((n) => n + 1);
    loadOrders();
  }

  function handleRetry() {
    setIsLoading(true);
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

  /** A card left on "show all items" would ignore the new filter entirely. */
  function selectState(filter: StateFilter) {
    setStateFilter(filter);
    setShowAllItemsFor(new Set());
  }

  function clearFilters() {
    setStateFilter('all');
    setPeriodFilter(PERIOD_ALL);
    setShowAllItemsFor(new Set());
  }

  const searchIndex = useMemo(
    () => buildOrderSearchIndex(orders, formatDate),
    // formatDate is locale-dependent, so the date haystack is rebuilt on
    // language change.
    [orders, language]
  );

  const queryTokens = useMemo(() => tokenize(searchQuery), [searchQuery]);
  const isSearching = queryTokens.length > 0;

  const searchMatches = useMemo(
    () => searchOrders(searchIndex, queryTokens),
    [searchIndex, queryTokens]
  );

  // Pinned to the payload rather than rendered fresh each pass, so the
  // 3-month cutoff can't shift mid-interaction.
  const now = useMemo(() => new Date(), [orders]);

  const periodMatches = useMemo(
    () => filterMatchesByPeriod(searchMatches, periodFilter, now),
    [searchMatches, periodFilter, now]
  );

  const matches = useMemo(
    () => filterMatchesByState(periodMatches, stateFilter),
    [periodMatches, stateFilter]
  );

  // Faceted counts: the state dimension is counted with the other filters
  // applied but not itself, so a chip always says what tapping it would give
  // you (and the active chip never reads "0").
  const stateCounts = useMemo(() => countItemsByState(periodMatches), [periodMatches]);

  const activeFilterCount =
    (stateFilter !== 'all' ? 1 : 0) + (periodFilter !== PERIOD_ALL ? 1 : 0);
  const isFiltering = activeFilterCount > 0;

  // Period is order-level: it changes which cards show, not which items inside
  // them, so it must NOT auto-expand every card the way the item filter does.
  const isItemNarrowed = isSearching || stateFilter !== 'all';

  const matchedItemCount = useMemo(
    () => (isItemNarrowed ? countMatchedItems(matches) : 0),
    [matches, isItemNarrowed]
  );

  // Only offer an option when it separates something, and never drop the one
  // that's active or it couldn't be switched off.
  const availableStates = ITEM_STATE_FILTERS.filter(
    (s) => stateCounts[s] > 0 || s === stateFilter
  );
  const showStateGroup = availableStates.length > 1 || stateFilter !== 'all';

  // Years and the 3-month shortcut only earn a chip if some order falls outside.
  const years = useMemo(() => orderYears(orders), [orders]);
  const hasOlderThanThreeMonths = useMemo(() => {
    const cutoff = threeMonthsBefore(now).getTime();
    return orders.some((o) => new Date(o.created_at).getTime() < cutoff);
  }, [orders, now]);
  const periodOptions = [
    ...(hasOlderThanThreeMonths ? [PERIOD_3M] : []),
    ...(years.length > 1 ? years.map(periodForYear) : []),
  ];
  const showPeriodGroup = periodOptions.length > 0;

  const showFilters = showStateGroup || showPeriodGroup;

  // Attach each missed-sale entry to its draft (handled inside the drafts
  // section), to its order, or keep it standalone. Draft attachment wins.
  const { missedForOrder, standaloneMissed } = useMemo(() => {
    const draftIds = new Set(drafts.map((d) => d.id));
    const orderIds = new Set(orders.map((o) => String(o.id)));
    const byOrder = new Map<string, MissedSale>();
    const standalone: MissedSale[] = [];
    for (const entry of missed) {
      if (entry.draft_order_id && draftIds.has(entry.draft_order_id)) continue;
      if (entry.shopify_order_id && orderIds.has(entry.shopify_order_id)) {
        byOrder.set(entry.shopify_order_id, entry);
      } else {
        standalone.push(entry);
      }
    }
    return { missedForOrder: byOrder, standaloneMissed: standalone };
  }, [missed, drafts, orders]);

  // Staleness guard for STANDALONE missed cards: a full miss whose product
  // shows up in ANY live order/draft line was delivered after all.
  const allLiveProductIds = useMemo(() => {
    const ids = new Set<number>();
    for (const order of orders) {
      for (const item of order.line_items) {
        if (item.product_id !== null) ids.add(item.product_id);
      }
    }
    for (const draft of drafts) {
      for (const item of draft.line_items) {
        if (item.product_id !== null) ids.add(item.product_id);
      }
    }
    return ids;
  }, [orders, drafts]);

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

  /** Shopify financial_status → translated badge text; unknown values render raw. */
  function getStatusLabel(status: string | null): string {
    switch (status) {
      case 'paid':
        return t('orders.statusPaid');
      case 'pending':
      case 'authorized':
        return t('orders.statusPending');
      case 'refunded':
        return t('orders.statusRefunded');
      case 'partially_refunded':
        return t('orders.statusPartiallyRefunded');
      case 'voided':
        return t('orders.statusVoided');
      default:
        return status ?? '';
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

  /** Short chip label — the full item labels are too long for a chip row. */
  function getFilterLabel(state: Exclude<StateFilter, 'all'>): string {
    switch (state) {
      case 'in_warehouse':
        return t('orders.filterInWarehouse');
      case 'incoming':
        return t('orders.filterIncoming');
      case 'shipped':
        return t('orders.filterShipped');
      default:
        return t('orders.filterPartial');
    }
  }

  function getPeriodLabel(period: string): string {
    if (period === PERIOD_3M) return t('orders.filterPeriod3m');
    const year = Number(period.slice(2));
    return year === now.getFullYear() ? t('orders.filterPeriodThisYear') : String(year);
  }

  /** Names the active filters, so a collapsed panel still says what's on. */
  function getActiveFilterLabels(): string[] {
    const labels: string[] = [];
    if (stateFilter !== 'all') labels.push(getFilterLabel(stateFilter));
    if (periodFilter !== PERIOD_ALL) labels.push(getPeriodLabel(periodFilter));
    return labels;
  }

  /**
   * Matching an order number matches no individual items, so reporting
   * "0 items" there would be wrong — show just the order count instead.
   */
  function getResultSummary(): string {
    const ordersLabel = getOrdersLabel(matches.length);
    const count =
      matchedItemCount === 0
        ? ordersLabel
        : t('orders.resultSummary', {
            items: getItemsLabel(matchedItemCount),
            orders: ordersLabel,
          });
    return [count, ...getActiveFilterLabels()].join('  ·  ');
  }

  /**
   * Collapsed-card status line: all shipped collapses to one calm success
   * line; anything else becomes compact per-state segments.
   */
  function renderRollup(order: Order) {
    const summary = orderStateSummary(order.line_items);
    const total = order.line_items.length;

    if (total > 0 && summary.shipped === total) {
      return <RollupSegment color={colors.success} text={t('orders.delivered')} />;
    }

    const segments: { color: string; text: string }[] = [];
    if (summary.inWarehouse > 0) {
      segments.push({
        color: colors.success,
        text: t('orders.rollupReady', { count: summary.inWarehouse }),
      });
    }
    if (summary.incoming > 0) {
      segments.push({
        color: colors.warning,
        text: summary.latestEta
          ? t('orders.rollupIncoming', {
              count: summary.incoming,
              date: formatShortDate(summary.latestEta, language),
            })
          : t('orders.rollupIncomingNoEta', { count: summary.incoming }),
      });
    }
    if (summary.partial > 0) {
      segments.push({
        color: colors.warning,
        text: t('orders.rollupPartial', { count: summary.partial }),
      });
    }
    if (summary.shipped > 0) {
      segments.push({
        color: colors.textMuted,
        text: t('orders.rollupShipped', { count: summary.shipped }),
      });
    }
    if (summary.unknown > 0) {
      segments.push({
        color: colors.textMuted,
        text: t('orders.rollupToShip', { count: summary.unknown }),
      });
    }

    return segments.map((segment, i) => (
      <View key={i} style={styles.rollupSegmentWrap}>
        {i > 0 && <Text style={styles.rollupSeparator}>·</Text>}
        <RollupSegment color={segment.color} text={segment.text} />
      </View>
    ));
  }

  const pickupSection = (
    <PickupSection
      language={language}
      refreshSignal={pickupRefresh}
      autoExpand={pickup != null}
      style={styles.pickupSection}
    />
  );

  // Members without a Shopify link can still announce a pickup — the
  // warehouse list flags them as unlinked.
  if (!user?.shopify_customer_id) {
    return (
      <View style={styles.container}>
        {/* Outside the padded list here, so it brings its own margins. */}
        <View style={styles.standalonePickupWrap}>{pickupSection}</View>
        <View style={styles.centerContainer}>
          <EmptyState
            icon="link-outline"
            title={t('orders.noShopifyTitle')}
            message={t('orders.noShopifyText')}
          />
        </View>
      </View>
    );
  }

  if (isLoading) {
    return (
      <View style={styles.container}>
        <View style={styles.skeletonList}>
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
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

  // Drafts and missed sales must render even with zero orders, so the screen
  // is one scrolling list and "no orders" is only the LIST's empty state.
  const listHeader = (
    <View>
      {pickupSection}

      <DraftOrdersSection
        drafts={drafts}
        missed={missed}
        language={language}
        formatPrice={formatPrice}
        formatDate={formatDate}
        style={styles.draftsSection}
      />

      <MissedSalesSection
        entries={standaloneMissed}
        fulfilledProductIds={allLiveProductIds}
        language={language}
        formatDate={formatDate}
        autoExpand={missedParam != null}
        style={styles.missedSection}
      />

      {orders.length > 0 && (
        <>
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
              <Pressable
                onPress={() => setSearchQuery('')}
                hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                style={({ pressed }) => pressed && styles.pressed}
              >
                <Ionicons name="close-circle" size={18} color={colors.textMuted} />
              </Pressable>
            ) : null}
          </View>

          {showFilters && (
            <View style={styles.toolbar}>
              <Pressable
                onPress={() => setFiltersOpen((open) => !open)}
                accessibilityRole="button"
                accessibilityState={{ expanded: filtersOpen }}
                style={({ pressed }) => [
                  styles.filterToggle,
                  (filtersOpen || isFiltering) && styles.filterToggleOn,
                  pressed && styles.pressed,
                ]}
              >
                <Ionicons
                  name="options-outline"
                  size={15}
                  color={filtersOpen || isFiltering ? colors.background : colors.text}
                />
                <Text
                  style={[
                    styles.filterToggleText,
                    (filtersOpen || isFiltering) && styles.filterToggleTextOn,
                  ]}
                >
                  {t('orders.filters')}
                  {activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}
                </Text>
                <Ionicons
                  name={filtersOpen ? 'chevron-up' : 'chevron-down'}
                  size={13}
                  color={filtersOpen || isFiltering ? colors.background : colors.textMuted}
                />
              </Pressable>

              {isFiltering && (
                <Pressable
                  onPress={clearFilters}
                  hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                  style={({ pressed }) => pressed && styles.pressed}
                >
                  <Text style={styles.clearFilters}>{t('orders.filterClearAll')}</Text>
                </Pressable>
              )}
            </View>
          )}

          {showFilters && filtersOpen && (
            <View style={styles.filterPanel}>
              {showStateGroup && (
                <FilterGroup label={t('orders.filterGroupStatus')}>
                  <FilterChip
                    label={t('orders.filterAll')}
                    active={stateFilter === 'all'}
                    onPress={() => selectState('all')}
                  />
                  {availableStates.map((state) => (
                    <FilterChip
                      key={state}
                      label={getFilterLabel(state)}
                      count={stateCounts[state]}
                      active={stateFilter === state}
                      onPress={() => selectState(stateFilter === state ? 'all' : state)}
                    />
                  ))}
                </FilterGroup>
              )}

              {showPeriodGroup && (
                <FilterGroup label={t('orders.filterGroupPeriod')}>
                  <FilterChip
                    label={t('orders.filterAll')}
                    active={periodFilter === PERIOD_ALL}
                    onPress={() => setPeriodFilter(PERIOD_ALL)}
                  />
                  {periodOptions.map((period) => (
                    <FilterChip
                      key={period}
                      label={getPeriodLabel(period)}
                      active={periodFilter === period}
                      onPress={() =>
                        setPeriodFilter(periodFilter === period ? PERIOD_ALL : period)
                      }
                    />
                  ))}
                </FilterGroup>
              )}
            </View>
          )}

          {/* Zero matches are covered by the list's empty state below. */}
          {(isSearching || isFiltering) && matches.length > 0 && (
            <Text style={styles.resultSummary} numberOfLines={1}>
              {getResultSummary()}
            </Text>
          )}
        </>
      )}
    </View>
  );

  return (
    <View style={styles.container}>
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
        ListHeaderComponent={listHeader}
        ListEmptyComponent={
          // The filter is the more specific "why is this empty" when both are on.
          isFiltering ? (
            <View style={styles.listEmpty}>
              <EmptyState
                icon="funnel-outline"
                title={t('orders.noResultsTitle')}
                message={t('orders.noFilterResultsText', {
                  filters: getActiveFilterLabels().join(' + '),
                })}
                actionLabel={t('orders.filterClearAll')}
                onAction={clearFilters}
              />
            </View>
          ) : isSearching ? (
            <View style={styles.listEmpty}>
              <EmptyState
                icon="search"
                title={t('orders.noResultsTitle')}
                message={t('orders.noResultsText', { query: searchQuery })}
              />
            </View>
          ) : (
            <View style={styles.listEmpty}>
              <EmptyState
                icon="receipt-outline"
                title={t('orders.noOrdersTitle')}
                message={t('orders.noOrdersText')}
              />
            </View>
          )
        }
        renderItem={({ item: match }) => {
          const order = match.order;
          const showingAll = showAllItemsFor.has(order.id);
          // While searching or filtering the matches are always visible — hiding
          // them behind a tap would defeat the point of narrowing the list.
          const isExpanded = isItemNarrowed ? true : expandedOrderId === order.id;
          const hiddenItemCount = order.line_items.length - match.matchedItems.length;
          const visibleItems =
            isItemNarrowed && !showingAll ? match.matchedItems : order.line_items;
          const missedEntry = missedForOrder.get(String(order.id));
          const orderProductIds = missedEntry
            ? new Set(
                order.line_items
                  .map((item) => item.product_id)
                  .filter((id): id is number => id !== null)
              )
            : null;

          return (
            <Pressable
              style={({ pressed }) => [
                styles.orderCard,
                pressed && { opacity: 0.85 },
              ]}
              onPress={() =>
                isItemNarrowed ? toggleShowAllItems(order.id) : toggleOrderExpanded(order.id)
              }
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
                      { backgroundColor: getStatusColor(order.financial_status) + '1f' },
                    ]}
                  >
                    <Text
                      style={[
                        styles.statusText,
                        { color: getStatusColor(order.financial_status) },
                      ]}
                    >
                      {getStatusLabel(order.financial_status)}
                    </Text>
                  </View>
                </View>
              </View>

              <View style={styles.fulfillmentRow}>
                <View style={styles.rollupRow}>{renderRollup(order)}</View>
                <Text style={styles.itemCount}>
                  {getItemsLabel(order.line_items.length)}
                </Text>
              </View>

              {isExpanded && (
                <View style={styles.lineItemsContainer}>
                  <View style={styles.divider} />
                  {visibleItems.map((item, itemIndex) => (
                    <View
                      key={item.id}
                      style={[styles.lineItem, itemIndex === 0 && styles.lineItemFirst]}
                    >
                      <View style={styles.lineItemInfo}>
                        <Text style={styles.lineItemTitle}>
                          {/* Plain prefix outside Highlighted, so search
                              matching never sees the quantity. */}
                          {item.quantity > 1 ? `${item.quantity}× ` : ''}
                          <Highlighted
                            text={item.display_title}
                            tokens={queryTokens}
                          />
                        </Text>
                        {item.variant_title && (
                          <Highlighted
                            text={item.variant_title}
                            tokens={queryTokens}
                            style={styles.lineItemVariant}
                          />
                        )}
                        <ItemStateBadge
                          state={item.state}
                          eta={item.estimated_delivery_date}
                          language={language}
                        />
                      </View>
                      <View style={styles.lineItemRight}>
                        <Text style={styles.lineItemPrice}>
                          {formatPrice(item.price, order.currency)}
                        </Text>
                      </View>
                    </View>
                  ))}

                  {missedEntry && orderProductIds && (
                    <>
                      <View style={styles.divider} />
                      <MissedItemsBlock
                        missed={missedEntry}
                        fulfilledProductIds={orderProductIds}
                        language={language}
                        style={styles.orderMissedBlock}
                      />
                    </>
                  )}
                </View>
              )}

              {/* Default mode: a chevron says "tappable" without repeating a
                  text hint down the whole list. Narrowed mode keeps the text —
                  it carries a count a chevron can't. */}
              {!isItemNarrowed ? (
                <Ionicons
                  name={isExpanded ? 'chevron-up' : 'chevron-down'}
                  size={14}
                  color={colors.textMuted}
                  style={styles.expandChevron}
                />
              ) : (
                <Text style={styles.expandHint}>
                  {showingAll
                    ? t('orders.tapToShowMatchesOnly')
                    : hiddenItemCount > 0
                    ? t('orders.tapToShowAllItems', { count: hiddenItemCount })
                    : ''}
                </Text>
              )}
            </Pressable>
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
    padding: spacing.lg,
    backgroundColor: colors.background,
  },
  pressed: {
    opacity: 0.7,
  },
  skeletonList: {
    padding: spacing.md,
  },
  listContent: {
    padding: spacing.md,
  },
  listEmpty: {
    marginTop: spacing.lg,
  },
  pickupSection: {
    marginBottom: spacing.md,
  },
  standalonePickupWrap: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
  },
  draftsSection: {
    marginBottom: spacing.sm,
  },

  // Consolidated section for missed sales with no draft/order to attach to
  missedSection: {
    marginBottom: spacing.md,
  },

  searchBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surfaceLow,
    marginTop: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.md,
    minHeight: 46,
  },
  searchInput: {
    flex: 1,
    color: colors.text,
    fontSize: 15,
    // Keeps the row height stable across platforms while typing.
    paddingVertical: 10,
  },
  toolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: spacing.sm,
  },
  filterToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.pill,
    paddingHorizontal: spacing.sm + spacing.xs,
    paddingVertical: 7,
  },
  filterToggleOn: {
    backgroundColor: colors.primary,
  },
  filterToggleText: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    color: colors.text,
  },
  filterToggleTextOn: {
    color: colors.background,
  },
  clearFilters: {
    fontSize: 12,
    color: colors.primary,
    textDecorationLine: 'underline',
  },
  filterPanel: {
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.md,
    marginTop: spacing.sm,
    paddingVertical: spacing.sm + spacing.xs,
  },
  filterGroup: {
    marginBottom: spacing.sm,
  },
  filterGroupLabel: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 1.4,
    textTransform: 'uppercase',
    color: colors.textMuted,
    marginHorizontal: spacing.md,
    marginBottom: 6,
  },
  // A plain wrapping row, not a horizontal ScrollView: RNW shrinks a ScrollView
  // inside this flex column to a sliver and clips the chips with overflow:hidden.
  // Wrapping also keeps every chip reachable without a hidden sideways scroll.
  filterRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginHorizontal: spacing.md,
  },
  filterChip: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.pill,
    paddingHorizontal: spacing.sm + spacing.xs,
    paddingVertical: 6,
  },
  filterChipActive: {
    backgroundColor: colors.primary,
  },
  filterChipText: {
    fontSize: 12,
    color: colors.textMuted,
  },
  filterChipTextActive: {
    color: colors.background,
    fontWeight: '600',
  },
  resultSummary: {
    color: colors.textMuted,
    fontSize: 13,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
  },
  highlight: {
    color: colors.primary,
    backgroundColor: colors.primary + '1f',
  },

  // Order card
  orderCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginTop: spacing.sm,
  },
  orderHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: spacing.md,
  },
  orderInfo: {
    flex: 1,
  },
  orderNumber: {
    fontFamily: fonts.heading,
    fontSize: 18,
    letterSpacing: 0.5,
    color: colors.text,
  },
  orderDate: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
  orderTotal: {
    alignItems: 'flex-end',
  },
  totalPrice: {
    fontFamily: fonts.heading,
    fontSize: 18,
    letterSpacing: 0.4,
    color: colors.primary,
  },
  statusBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.pill,
    marginTop: spacing.xs,
  },
  statusText: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  fulfillmentRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },

  // Status roll-up on the collapsed card
  rollupRow: {
    flex: 1,
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    rowGap: 2,
  },
  rollupSegmentWrap: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  rollupSegment: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  rollupDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    marginRight: 5,
  },
  rollupText: {
    fontSize: 12,
    fontWeight: '600',
  },
  rollupSeparator: {
    fontSize: 12,
    color: colors.textMuted,
    marginHorizontal: 6,
  },
  itemCount: {
    fontSize: 13,
    color: colors.textMuted,
  },

  // Line items
  lineItemsContainer: {
    marginTop: spacing.sm,
  },
  divider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: colors.borderStrong,
  },
  lineItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: spacing.sm + spacing.xs,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  lineItemFirst: {
    borderTopWidth: 0,
  },
  lineItemInfo: {
    flex: 1,
    marginRight: spacing.md,
  },
  lineItemTitle: {
    fontSize: 14,
    lineHeight: 19,
    color: colors.text,
  },
  lineItemVariant: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
  lineItemRight: {
    alignItems: 'flex-end',
  },
  lineItemPrice: {
    fontFamily: fonts.heading,
    fontSize: 14,
    letterSpacing: 0.3,
    color: colors.text,
    marginTop: 2,
  },
  orderMissedBlock: {
    marginTop: spacing.sm + spacing.xs,
  },
  expandHint: {
    fontSize: 11,
    color: colors.textMuted,
    textAlign: 'center',
    marginTop: spacing.sm + spacing.xs,
  },
  expandChevron: {
    alignSelf: 'center',
    marginTop: spacing.sm + spacing.xs,
  },
});
