import { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  Image,
  Modal,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  Dimensions,
  Pressable,
  LayoutAnimation,
  Platform,
  UIManager,
} from 'react-native';

if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}
import * as Clipboard from 'expo-clipboard';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../../src/context/AuthContext';
import { useLanguage } from '../../src/context/LanguageContext';
import { t } from '../../src/i18n';
import {
  getLoyaltySummary,
  getRewards,
  getTransactions,
  getRedemptions,
  getPointsRules,
  redeemReward,
  syncPoints,
  LoyaltySummary,
  Reward,
  RewardsResponse,
  PointsTransaction,
  PointsRule,
  Redemption,
} from '../../src/api/loyalty';
import { colors, spacing, borderRadius, fonts, type } from '../../src/theme/colors';
import { useToast } from '../../src/components/ui';
import { RaffleSection } from '../../src/components/RaffleCard';

type TabType = 'rewards' | 'history' | 'redemptions';

export default function LoyaltyScreen() {
  const { user } = useAuth();
  const { language } = useLanguage();
  const [activeTab, setActiveTab] = useState<TabType>('rewards');
  const [summary, setSummary] = useState<LoyaltySummary | null>(null);
  const [rewardsData, setRewardsData] = useState<RewardsResponse>({ categories: [], uncategorized: [] });
  const [collapsedCategories, setCollapsedCategories] = useState<Set<number>>(new Set());
  const [transactions, setTransactions] = useState<PointsTransaction[]>([]);
  const [redemptions, setRedemptions] = useState<Redemption[]>([]);
  const [raffleHistoryCount, setRaffleHistoryCount] = useState(0);
  const [rules, setRules] = useState<PointsRule[]>([]);
  const [showEarnInfo, setShowEarnInfo] = useState(false);
  const [expandedTxns, setExpandedTxns] = useState<Set<number>>(new Set());
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isRedeeming, setIsRedeeming] = useState<number | null>(null);
  const { showToast } = useToast();
  const [loadError, setLoadError] = useState('');
  const [copiedCode, setCopiedCode] = useState<string | null>(null);
  const [imageOverlay, setImageOverlay] = useState<string | null>(null);
  const [initialCollapseSet, setInitialCollapseSet] = useState(false);
  // Bumped on pull-to-refresh so the raffle section refetches along with the rest.
  const [raffleRefresh, setRaffleRefresh] = useState(0);

  const loadData = useCallback(async () => {
    try {
      setLoadError('');
      const [summaryData, rewardsResult, transactionsData, redemptionsData, rulesData] = await Promise.all([
        getLoyaltySummary(),
        getRewards(),
        getTransactions(),
        getRedemptions(),
        getPointsRules(),
      ]);
      setSummary(summaryData);
      setRewardsData(rewardsResult);
      setTransactions(transactionsData);
      setRedemptions(redemptionsData);
      setRules(rulesData);

      // Default all categories to collapsed on first load
      if (!initialCollapseSet && rewardsResult.categories.length > 0) {
        setCollapsedCategories(new Set(rewardsResult.categories.map(c => c.id)));
        setInitialCollapseSet(true);
      }
    } catch (err) {
      console.log('[Loyalty] Error:', err);
      setLoadError(err instanceof Error ? err.message : 'Failed to load loyalty data');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [initialCollapseSet]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  function handleRefresh() {
    setIsRefreshing(true);
    setRaffleRefresh((k) => k + 1);
    loadData();
  }

  async function handleSync() {
    if (!user?.shopify_customer_id) {
      showToast(t('orders.noShopifyText'), 'error');
      return;
    }

    setIsSyncing(true);
    try {
      const result = await syncPoints();
      if (result.success) {
        showToast(`+${result.points_awarded} ${t('loyalty.points')}`, 'success');
        await loadData();
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Sync failed', 'error');
    } finally {
      setIsSyncing(false);
    }
  }

  async function handleRedeem(reward: Reward) {
    setIsRedeeming(reward.id);
    try {
      const result = await redeemReward(reward.id);
      if (result.success) {
        showToast(`${reward.name} ✓`, 'success');
        await loadData();
        if (result.discount_code) {
          setActiveTab('redemptions');
        }
      } else {
        showToast(result.error || 'Redemption failed', 'error');
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Redemption failed', 'error');
    } finally {
      setIsRedeeming(null);
    }
  }

  async function copyToClipboard(code: string) {
    await Clipboard.setStringAsync(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  }

  function toggleCategory(categoryId: number) {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setCollapsedCategories(prev => {
      const next = new Set(prev);
      if (next.has(categoryId)) {
        next.delete(categoryId);
      } else {
        next.add(categoryId);
      }
      return next;
    });
  }

  function formatDate(dateString: string): string {
    const locale = language === 'nl' ? 'nl-NL' : 'en-US';
    return new Date(dateString).toLocaleDateString(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  }

  function ruleSentence(rule: PointsRule): string {
    switch (rule.rule_type) {
      case 'per_euro': {
        const multiplier = parseFloat(rule.multiplier);
        if (multiplier >= 1) {
          const points = Number.isInteger(multiplier) ? multiplier : multiplier.toFixed(2);
          return t('loyalty.rulePerEuro', { points });
        }
        return t('loyalty.rulePerEuroInverse', { euros: Math.round(1 / multiplier) });
      }
      case 'per_order':
        return t('loyalty.rulePerOrder', { points: rule.points });
      case 'product_sku':
      case 'product_title':
        return t('loyalty.ruleProduct', { points: rule.points, product: rule.condition_value || rule.name });
      case 'minimum_order':
        return t('loyalty.ruleMinimumOrder', { points: rule.points, amount: rule.condition_value });
      case 'first_order':
        return t('loyalty.ruleFirstOrder', { points: rule.points });
      default:
        return rule.name;
    }
  }

  function txnTitle(tx: PointsTransaction): string {
    if (tx.transaction_type === 'earned' && tx.shopify_order_name) {
      return t('loyalty.txnOrder', { order: tx.shopify_order_name });
    }
    if (tx.transaction_type === 'spent' && tx.reward_name) {
      return t('loyalty.txnRedeemed', { reward: tx.reward_name });
    }
    if (tx.transaction_type === 'adjusted') {
      if (tx.reward_name) {
        return t('loyalty.txnRefund', { reward: tx.reward_name });
      }
      return t('loyalty.txnAdjustment');
    }
    return tx.description;
  }

  function txnIcon(tx: PointsTransaction): keyof typeof Ionicons.glyphMap {
    if (tx.transaction_type === 'earned') return 'cart';
    if (tx.transaction_type === 'spent') return 'gift';
    if (tx.transaction_type === 'adjusted' && tx.reward_name) return 'arrow-undo';
    return 'options';
  }

  function toggleTxn(txId: number) {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setExpandedTxns(prev => {
      const next = new Set(prev);
      if (next.has(txId)) {
        next.delete(txId);
      } else {
        next.add(txId);
      }
      return next;
    });
  }

  const allRewards = [
    ...rewardsData.categories.flatMap(c => c.rewards),
    ...rewardsData.uncategorized,
  ];
  const balanceValue = summary?.balance || 0;
  const affordableCount = allRewards.filter(r => r.points_cost <= balanceValue).length;
  const nextReward = allRewards
    .filter(r => r.points_cost > balanceValue)
    .sort((a, b) => a.points_cost - b.points_cost)[0];

  if (isLoading) {
    return (
      <View style={styles.centerContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
        <Text style={styles.loadingText}>{t('loading')}</Text>
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
      {/* Points Balance Card — membership card look */}
      <View style={styles.balanceCard}>
        <View style={styles.cardBrandRow}>
          <View style={styles.cardBrandLeft}>
            <Ionicons name="star" size={13} color={colors.primary} />
            <Text style={styles.cardBrand}>House of Beers</Text>
          </View>
          <TouchableOpacity
            style={[styles.syncButton, isSyncing && styles.buttonDisabled]}
            onPress={handleSync}
            disabled={isSyncing}
          >
            <Ionicons name="sync" size={14} color={colors.background} />
            <Text style={styles.syncButtonText}>
              {isSyncing ? t('loyalty.syncing') : t('loyalty.sync')}
            </Text>
          </TouchableOpacity>
        </View>
        <View style={styles.balanceRow}>
          <Text style={styles.balanceAmount}>{summary?.balance || 0}</Text>
          <Text style={styles.balanceUnit}>{t('loyalty.points')}</Text>
        </View>

        {(nextReward || affordableCount > 0) && (
          <View style={styles.progressSection}>
            {nextReward && (
              <View style={styles.progressBarTrack}>
                <View
                  style={[
                    styles.progressBarFill,
                    { width: `${Math.min(100, Math.round((balanceValue / nextReward.points_cost) * 100))}%` },
                  ]}
                />
              </View>
            )}
            {affordableCount > 0 ? (
              <View style={styles.progressStatusRow}>
                <Ionicons name="gift" size={13} color={colors.primary} />
                <Text style={styles.progressTextHighlight}>
                  {t('loyalty.rewardsAvailable', { count: affordableCount })}
                </Text>
              </View>
            ) : nextReward ? (
              <Text style={styles.progressText}>
                {t('loyalty.nextRewardProgress', {
                  points: nextReward.points_cost - balanceValue,
                  reward: nextReward.name,
                })}
              </Text>
            ) : null}
          </View>
        )}
      </View>

      {/* Raffles — renders nothing when there are none */}
      <RaffleSection
        language={language}
        refreshSignal={raffleRefresh}
        style={styles.raffleSection}
      />

      {/* How to earn points */}
      {rules.length > 0 && (
        <View style={styles.earnCard}>
          <TouchableOpacity
            style={styles.earnHeader}
            onPress={() => {
              LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
              setShowEarnInfo(prev => !prev);
            }}
            activeOpacity={0.7}
          >
            <View style={styles.earnHeaderLeft}>
              <Ionicons name="help-circle-outline" size={20} color={colors.primary} />
              <Text style={styles.earnTitle}>{t('loyalty.howToEarn')}</Text>
            </View>
            <Ionicons
              name={showEarnInfo ? 'chevron-up' : 'chevron-down'}
              size={20}
              color={colors.primary}
            />
          </TouchableOpacity>
          {showEarnInfo && (
            <View style={styles.earnBody}>
              <Text style={styles.earnIntro}>{t('loyalty.howToEarnIntro')}</Text>
              {rules.map(rule => (
                <View key={rule.id} style={styles.earnRule}>
                  <Ionicons name="star" size={14} color={colors.primary} style={styles.earnRuleIcon} />
                  <View style={styles.earnRuleText}>
                    <Text style={styles.earnRuleSentence}>{ruleSentence(rule)}</Text>
                    {rule.description ? (
                      <Text style={styles.earnRuleDescription}>{rule.description}</Text>
                    ) : null}
                    {rule.only_after_registration && (
                      <Text style={styles.earnRuleNote}>{t('loyalty.onlyAfterRegistration')}</Text>
                    )}
                  </View>
                </View>
              ))}
              <Text style={styles.syncNote}>{t('loyalty.syncNote')}</Text>
            </View>
          )}
        </View>
      )}

      {loadError ? (
        <View style={styles.errorMessage}>
          <Text style={styles.errorText}>{loadError}</Text>
        </View>
      ) : null}

      {/* Tabs */}
      <View style={styles.tabs}>
        <TouchableOpacity
          style={[styles.tab, activeTab === 'rewards' && styles.tabActive]}
          onPress={() => setActiveTab('rewards')}
        >
          <Text style={[styles.tabText, activeTab === 'rewards' && styles.tabTextActive]} numberOfLines={1}>
            {t('loyalty.tabRewards')}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, activeTab === 'history' && styles.tabActive]}
          onPress={() => setActiveTab('history')}
        >
          <Text style={[styles.tabText, activeTab === 'history' && styles.tabTextActive]} numberOfLines={1}>
            {t('loyalty.tabHistory')}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, activeTab === 'redemptions' && styles.tabActive]}
          onPress={() => setActiveTab('redemptions')}
        >
          <Text style={[styles.tabText, activeTab === 'redemptions' && styles.tabTextActive]} numberOfLines={1}>
            {t('loyalty.tabCodes')}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Tab Content */}
      <View style={styles.tabContent}>
        {activeTab === 'rewards' && (
          rewardsData.categories.length === 0 && rewardsData.uncategorized.length === 0 ? (
            <View style={styles.emptyState}>
              <Ionicons name="gift-outline" size={48} color={colors.textMuted} />
              <Text style={styles.emptyText}>{t('loyalty.noRewards')}</Text>
            </View>
          ) : (
            <>
              {rewardsData.categories.map((category) => {
                const isCollapsed = collapsedCategories.has(category.id);
                return (
                  <View key={`cat-${category.id}`} style={styles.categorySection}>
                    <TouchableOpacity
                      style={styles.categoryHeader}
                      onPress={() => toggleCategory(category.id)}
                      activeOpacity={0.7}
                    >
                      <Text style={styles.categoryName}>{category.name}</Text>
                      <View style={styles.categoryRight}>
                        <View style={styles.categoryBadge}>
                          <Text style={styles.categoryCount}>{category.rewards.length}</Text>
                        </View>
                        <Ionicons
                          name={isCollapsed ? 'chevron-down' : 'chevron-up'}
                          size={20}
                          color={colors.primary}
                        />
                      </View>
                    </TouchableOpacity>
                    {!isCollapsed && category.rewards.map((reward) => (
                      <View key={reward.id} style={styles.rewardCard}>
                        {reward.image_url ? (
                          <TouchableOpacity activeOpacity={0.9} onPress={() => setImageOverlay(reward.image_url)}>
                            <Image source={{ uri: reward.image_url }} style={styles.rewardImage} resizeMode="cover" />
                          </TouchableOpacity>
                        ) : null}
                        <View style={styles.rewardBody}>
                          <View style={styles.rewardInfo}>
                            <Text style={styles.rewardName}>{reward.name}</Text>
                            {reward.description ? (
                              <Text style={styles.rewardDescription}>{reward.description}</Text>
                            ) : null}
                            <View style={styles.rewardMeta}>
                              <Text style={styles.rewardType}>{reward.reward_type_display}</Text>
                              {reward.discount_amount && (
                                <Text style={styles.rewardValue}>€{parseFloat(reward.discount_amount)} off</Text>
                              )}
                              {reward.discount_percentage && (
                                <Text style={styles.rewardValue}>{parseFloat(reward.discount_percentage)}% off</Text>
                              )}
                            </View>
                          </View>
                          <View style={styles.rewardAction}>
                            <Text style={styles.pointsCost}>{reward.points_cost}</Text>
                            <Text style={styles.pointsLabel}>{t('loyalty.points')}</Text>
                            <TouchableOpacity
                              style={[
                                styles.redeemButton,
                                !reward.can_redeem && styles.redeemButtonDisabled,
                              ]}
                              onPress={() => handleRedeem(reward)}
                              disabled={!reward.can_redeem || isRedeeming === reward.id}
                            >
                              <Text style={styles.redeemButtonText}>
                                {isRedeeming === reward.id ? '...' : t('loyalty.redeem')}
                              </Text>
                            </TouchableOpacity>
                          </View>
                        </View>
                      </View>
                    ))}
                  </View>
                );
              })}
              {rewardsData.uncategorized.map((reward) => (
                <View key={reward.id} style={styles.rewardCard}>
                  {reward.image_url ? (
                    <TouchableOpacity activeOpacity={0.9} onPress={() => setImageOverlay(reward.image_url)}>
                      <Image source={{ uri: reward.image_url }} style={styles.rewardImage} resizeMode="cover" />
                    </TouchableOpacity>
                  ) : null}
                  <View style={styles.rewardBody}>
                    <View style={styles.rewardInfo}>
                      <Text style={styles.rewardName}>{reward.name}</Text>
                      {reward.description ? (
                        <Text style={styles.rewardDescription}>{reward.description}</Text>
                      ) : null}
                      <View style={styles.rewardMeta}>
                        <Text style={styles.rewardType}>{reward.reward_type_display}</Text>
                        {reward.discount_amount && (
                          <Text style={styles.rewardValue}>€{parseFloat(reward.discount_amount)} off</Text>
                        )}
                        {reward.discount_percentage && (
                          <Text style={styles.rewardValue}>{parseFloat(reward.discount_percentage)}% off</Text>
                        )}
                      </View>
                    </View>
                    <View style={styles.rewardAction}>
                      <Text style={styles.pointsCost}>{reward.points_cost}</Text>
                      <Text style={styles.pointsLabel}>{t('loyalty.points')}</Text>
                      <TouchableOpacity
                        style={[
                          styles.redeemButton,
                          !reward.can_redeem && styles.redeemButtonDisabled,
                        ]}
                        onPress={() => handleRedeem(reward)}
                        disabled={!reward.can_redeem || isRedeeming === reward.id}
                      >
                        <Text style={styles.redeemButtonText}>
                          {isRedeeming === reward.id ? '...' : t('loyalty.redeem')}
                        </Text>
                      </TouchableOpacity>
                    </View>
                  </View>
                </View>
              ))}
            </>
          )
        )}

        {activeTab === 'history' && (
          transactions.length === 0 ? (
            <View style={styles.emptyState}>
              <Ionicons name="time-outline" size={48} color={colors.textMuted} />
              <Text style={styles.emptyText}>{t('loyalty.noTransactions')}</Text>
            </View>
          ) : (
            <>
              <View style={styles.lifetimeStatsCard}>
                <View style={styles.stat}>
                  <Text style={styles.statValue}>{summary?.lifetime_earned || 0}</Text>
                  <Text style={styles.statLabel}>{t('loyalty.lifetimeEarned')}</Text>
                </View>
                <View style={styles.statDivider} />
                <View style={styles.stat}>
                  <Text style={styles.statValue}>{summary?.lifetime_spent || 0}</Text>
                  <Text style={styles.statLabel}>{t('loyalty.lifetimeSpent')}</Text>
                </View>
              </View>
              {transactions.map((tx) => {
                const hasBreakdown = !!tx.breakdown && tx.breakdown.length > 0;
                const isExpanded = expandedTxns.has(tx.id);
                return (
                  <TouchableOpacity
                    key={tx.id}
                    style={styles.transactionCard}
                    onPress={() => hasBreakdown && toggleTxn(tx.id)}
                    activeOpacity={hasBreakdown ? 0.7 : 1}
                  >
                    <View style={styles.transactionRow}>
                      <View style={styles.transactionIconWrap}>
                        <Ionicons name={txnIcon(tx)} size={18} color={colors.primary} />
                      </View>
                      <View style={styles.transactionInfo}>
                        <Text style={styles.transactionDesc}>{txnTitle(tx)}</Text>
                        <Text style={styles.transactionDate}>
                          {formatDate(tx.created_at)}
                          {hasBreakdown && !isExpanded ? `  ·  ${t('loyalty.showBreakdown')}` : ''}
                        </Text>
                      </View>
                      <Text
                        style={[
                          styles.transactionPoints,
                          tx.points >= 0 ? styles.pointsPositive : styles.pointsNegative,
                        ]}
                      >
                        {tx.points >= 0 ? '+' : ''}{tx.points}
                      </Text>
                    </View>
                    {hasBreakdown && isExpanded && (
                      <View style={styles.breakdownBox}>
                        {tx.breakdown!.map((item, index) => (
                          <View key={index} style={styles.breakdownRow}>
                            <Text style={styles.breakdownName}>{item.rule_name}</Text>
                            <Text style={styles.breakdownPoints}>+{item.points}</Text>
                          </View>
                        ))}
                      </View>
                    )}
                  </TouchableOpacity>
                );
              })}
            </>
          )
        )}

        {activeTab === 'redemptions' && (
          redemptions.length === 0 ? (
            // With draw history below, "no codes" would read oddly next to a
            // won prize code — the history rows carry the tab on their own.
            raffleHistoryCount > 0 ? null : (
              <View style={styles.emptyState}>
                <Ionicons name="ticket-outline" size={48} color={colors.textMuted} />
                <Text style={styles.emptyText}>{t('loyalty.noCodes')}</Text>
              </View>
            )
          ) : (
            redemptions.map((redemption) => (
              <View key={redemption.id} style={styles.redemptionCard}>
                <View style={styles.redemptionInfo}>
                  <Text style={styles.redemptionName}>{redemption.reward_name}</Text>
                  <Text style={styles.redemptionDate}>
                    {formatDate(redemption.created_at)}
                  </Text>
                  {redemption.expires_at && (
                    <Text style={styles.redemptionExpires}>
                      {t('loyalty.expires')}: {formatDate(redemption.expires_at)}
                    </Text>
                  )}
                </View>
                {redemption.discount_code ? (
                  <TouchableOpacity
                    style={styles.codeContainer}
                    onPress={() => copyToClipboard(redemption.discount_code)}
                    activeOpacity={0.7}
                  >
                    <View style={styles.codeLeft}>
                      <Text style={styles.discountCode}>{redemption.discount_code}</Text>
                      <Text style={styles.copyHint}>
                        {copiedCode === redemption.discount_code ? t('loyalty.copiedToClipboard') : t('loyalty.tapToCopy')}
                      </Text>
                    </View>
                    <View style={styles.codeRight}>
                      <Ionicons
                        name={copiedCode === redemption.discount_code ? 'checkmark-circle' : 'copy-outline'}
                        size={20}
                        color={copiedCode === redemption.discount_code ? colors.success : colors.primary}
                      />
                      <Text
                        style={[
                          styles.codeStatus,
                          redemption.discount_code_used && styles.codeUsed,
                        ]}
                      >
                        {redemption.discount_code_used ? 'Used' : (redemption.status_display || 'Pending')}
                      </Text>
                    </View>
                  </TouchableOpacity>
                ) : null}
              </View>
            ))
          )
        )}

        {/* Past draws live with the codes: the raffle archive. Renders
            nothing when the user has no watched draws. */}
        {activeTab === 'redemptions' && (
          <RaffleSection
            variant="history"
            language={language}
            refreshSignal={raffleRefresh}
            style={styles.raffleHistory}
            onCount={setRaffleHistoryCount}
          />
        )}
      </View>

      {/* Image Overlay */}
      <Modal visible={!!imageOverlay} transparent animationType="fade" onRequestClose={() => setImageOverlay(null)}>
        <Pressable style={styles.overlay} onPress={() => setImageOverlay(null)}>
          <View style={styles.overlayContent}>
            {imageOverlay && (
              <Image source={{ uri: imageOverlay }} style={styles.overlayImage} resizeMode="contain" />
            )}
          </View>
          <TouchableOpacity style={styles.overlayClose} onPress={() => setImageOverlay(null)}>
            <Ionicons name="close-circle" size={36} color={colors.text} />
          </TouchableOpacity>
        </Pressable>
      </Modal>
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
  },
  loadingText: {
    marginTop: spacing.md,
    color: colors.textMuted,
    fontSize: 14,
  },
  balanceCard: {
    backgroundColor: colors.surfaceHigh,
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
    padding: spacing.md,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  cardBrandRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  cardBrandLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  cardBrand: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 2,
    textTransform: 'uppercase',
    color: colors.primary,
  },
  balanceRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  balanceAmount: {
    fontFamily: fonts.headingBold,
    fontSize: 46,
    lineHeight: 52,
    color: colors.text,
  },
  balanceUnit: {
    fontFamily: fonts.serifItalic,
    fontSize: 16,
    color: colors.textMuted,
  },
  progressSection: {
    width: '100%',
    marginTop: spacing.sm,
  },
  progressStatusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    marginTop: spacing.xs,
  },
  progressTextHighlight: {
    fontSize: 12,
    color: colors.primary,
    fontWeight: '600',
  },
  progressBarTrack: {
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.tertiary + '30',
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    borderRadius: 4,
    backgroundColor: colors.primary,
  },
  progressText: {
    fontSize: 12,
    color: colors.textMuted,
    textAlign: 'center',
    marginTop: spacing.xs,
  },
  syncNote: {
    fontSize: 11,
    color: colors.textMuted,
    fontStyle: 'italic',
    marginTop: spacing.xs,
  },
  raffleSection: {
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  raffleHistory: {
    marginTop: spacing.md,
  },
  earnCard: {
    backgroundColor: colors.surface,
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
    overflow: 'hidden',
  },
  earnHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.md,
  },
  earnHeaderLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  earnTitle: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.5,
    color: colors.text,
  },
  earnBody: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.md,
  },
  earnIntro: {
    fontFamily: fonts.serif,
    fontSize: 15,
    color: colors.textMuted,
    marginBottom: spacing.sm,
  },
  earnRule: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: spacing.sm,
  },
  earnRuleIcon: {
    marginTop: 2,
    marginRight: spacing.sm,
  },
  earnRuleText: {
    flex: 1,
  },
  earnRuleSentence: {
    fontSize: 14,
    color: colors.text,
    fontWeight: '500',
  },
  earnRuleDescription: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
  earnRuleNote: {
    fontSize: 11,
    color: colors.warning,
    marginTop: 2,
    fontStyle: 'italic',
  },
  lifetimeStatsCard: {
    flexDirection: 'row',
    justifyContent: 'center',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  stat: {
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
  },
  statValue: {
    fontFamily: fonts.heading,
    fontSize: 18,
    letterSpacing: 0.4,
    color: colors.text,
  },
  statLabel: {
    fontSize: 12,
    color: colors.textMuted,
  },
  statDivider: {
    width: 1,
    backgroundColor: colors.tertiary + '30',
  },
  syncButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.md,
    gap: spacing.xs,
  },
  syncButtonText: {
    color: colors.background,
    fontSize: 13,
    fontWeight: '600',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  errorMessage: {
    backgroundColor: colors.error + '20',
    marginHorizontal: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
  },
  errorText: {
    color: colors.error,
    textAlign: 'center',
  },
  tabs: {
    flexDirection: 'row',
    marginHorizontal: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: 4,
    gap: 4,
  },
  tab: {
    flex: 1,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: borderRadius.sm,
  },
  tabActive: {
    backgroundColor: colors.primary,
  },
  tabText: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    color: colors.textMuted,
    textAlign: 'center',
    paddingHorizontal: 2,
  },
  tabTextActive: {
    color: colors.background,
  },
  tabContent: {
    padding: spacing.md,
  },
  emptyState: {
    alignItems: 'center',
    padding: spacing.xl,
  },
  emptyText: {
    marginTop: spacing.md,
    color: colors.textMuted,
    fontSize: 14,
  },
  categorySection: {
    marginBottom: spacing.sm,
  },
  categoryHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.surface,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.primary + '30',
  },
  categoryName: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.6,
    color: colors.primary,
    flex: 1,
  },
  categoryRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  categoryBadge: {
    backgroundColor: colors.primary + '20',
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  categoryCount: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.primary,
  },
  rewardCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  rewardImage: {
    width: '100%',
    height: 140,
  },
  rewardBody: {
    flexDirection: 'row',
    padding: spacing.md,
  },
  rewardInfo: {
    flex: 1,
  },
  rewardName: {
    fontFamily: fonts.heading,
    fontSize: 16,
    letterSpacing: 0.4,
    color: colors.text,
  },
  rewardDescription: {
    fontFamily: fonts.serif,
    fontSize: 14,
    color: colors.textMuted,
    marginTop: 2,
  },
  rewardMeta: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  rewardType: {
    fontSize: 11,
    color: colors.textMuted,
    backgroundColor: colors.tertiary + '20',
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  rewardValue: {
    fontSize: 11,
    color: colors.primary,
    fontWeight: '600',
  },
  rewardAction: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingLeft: spacing.md,
  },
  pointsCost: {
    fontFamily: fonts.headingBold,
    fontSize: 20,
    color: colors.primary,
  },
  pointsLabel: {
    fontSize: 11,
    color: colors.textMuted,
  },
  redeemButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
    marginTop: spacing.sm,
  },
  redeemButtonDisabled: {
    backgroundColor: colors.textMuted,
    opacity: 0.5,
  },
  redeemButtonText: {
    color: colors.background,
    fontSize: 12,
    fontWeight: '600',
  },
  transactionCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  transactionRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  transactionIconWrap: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: colors.primary + '20',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.sm,
  },
  transactionInfo: {
    flex: 1,
  },
  breakdownBox: {
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
    paddingLeft: 34 + spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.tertiary + '20',
  },
  breakdownRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 2,
  },
  breakdownName: {
    fontSize: 12,
    color: colors.textMuted,
    flex: 1,
    marginRight: spacing.sm,
  },
  breakdownPoints: {
    fontSize: 12,
    color: colors.success,
    fontWeight: '600',
  },
  transactionDesc: {
    fontSize: 14,
    color: colors.text,
  },
  transactionDate: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
  transactionPoints: {
    fontSize: 18,
    fontWeight: '700',
  },
  pointsPositive: {
    color: colors.success,
  },
  pointsNegative: {
    color: colors.error,
  },
  redemptionCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  redemptionInfo: {
    marginBottom: spacing.sm,
  },
  redemptionName: {
    fontFamily: fonts.heading,
    fontSize: 16,
    letterSpacing: 0.4,
    color: colors.text,
  },
  redemptionDate: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
  redemptionExpires: {
    fontSize: 11,
    color: colors.warning,
    marginTop: 2,
  },
  codeContainer: {
    backgroundColor: colors.primary + '15',
    padding: spacing.sm,
    borderRadius: borderRadius.sm,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  codeLeft: {
    flex: 1,
  },
  codeRight: {
    alignItems: 'flex-end',
    gap: 4,
  },
  discountCode: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.primary,
    fontFamily: 'monospace',
  },
  copyHint: {
    fontSize: 10,
    color: colors.textMuted,
    marginTop: 2,
  },
  codeStatus: {
    fontSize: 11,
    color: colors.success,
    fontWeight: '600',
  },
  codeUsed: {
    color: colors.textMuted,
  },
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.9)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  overlayContent: {
    width: Dimensions.get('window').width - spacing.lg * 2,
    height: Dimensions.get('window').height * 0.6,
  },
  overlayImage: {
    width: '100%',
    height: '100%',
    borderRadius: borderRadius.md,
  },
  overlayClose: {
    position: 'absolute',
    top: 50,
    right: 20,
  },
});
