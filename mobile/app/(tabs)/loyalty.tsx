import { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
  ScrollView,
} from 'react-native';
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
  redeemReward,
  syncPoints,
  LoyaltySummary,
  Reward,
  PointsTransaction,
  Redemption,
} from '../../src/api/loyalty';
import { colors, spacing, borderRadius } from '../../src/theme/colors';

type TabType = 'rewards' | 'history' | 'redemptions';

export default function LoyaltyScreen() {
  const { user } = useAuth();
  const { language } = useLanguage();
  const [activeTab, setActiveTab] = useState<TabType>('rewards');
  const [summary, setSummary] = useState<LoyaltySummary | null>(null);
  const [rewards, setRewards] = useState<Reward[]>([]);
  const [transactions, setTransactions] = useState<PointsTransaction[]>([]);
  const [redemptions, setRedemptions] = useState<Redemption[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isRedeeming, setIsRedeeming] = useState<number | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      setError('');
      const [summaryData, rewardsData, transactionsData, redemptionsData] = await Promise.all([
        getLoyaltySummary(),
        getRewards(),
        getTransactions(),
        getRedemptions(),
      ]);
      setSummary(summaryData);
      setRewards(rewardsData);
      setTransactions(transactionsData);
      setRedemptions(redemptionsData);
    } catch (err) {
      console.log('[Loyalty] Error:', err);
      setError(err instanceof Error ? err.message : 'Failed to load loyalty data');
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

  async function handleSync() {
    if (!user?.shopify_customer_id) {
      setError(t('orders.noShopifyText'));
      return;
    }

    setIsSyncing(true);
    setMessage('');
    setError('');
    try {
      const result = await syncPoints();
      if (result.success) {
        setMessage(`Synced! +${result.points_awarded} points from ${result.orders_processed} orders`);
        await loadData();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sync failed');
    } finally {
      setIsSyncing(false);
    }
  }

  async function handleRedeem(reward: Reward) {
    setIsRedeeming(reward.id);
    setMessage('');
    setError('');
    try {
      const result = await redeemReward(reward.id);
      if (result.success) {
        if (result.discount_code) {
          setMessage(`Redeemed! Your code: ${result.discount_code}`);
        } else {
          setMessage(`Successfully redeemed: ${reward.name}`);
        }
        await loadData();
      } else {
        setError(result.error || 'Redemption failed');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Redemption failed');
    } finally {
      setIsRedeeming(null);
    }
  }

  async function copyToClipboard(code: string) {
    await Clipboard.setStringAsync(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  }

  function formatDate(dateString: string): string {
    const locale = language === 'nl' ? 'nl-NL' : 'en-US';
    return new Date(dateString).toLocaleDateString(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  }

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
      {/* Points Balance Card */}
      <View style={styles.balanceCard}>
        <View style={styles.balanceHeader}>
          <Ionicons name="star" size={32} color={colors.primary} />
          <Text style={styles.balanceTitle}>{t('loyalty.pointsBalance')}</Text>
        </View>
        <Text style={styles.balanceAmount}>{summary?.balance || 0}</Text>
        <View style={styles.balanceStats}>
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

        <TouchableOpacity
          style={[styles.syncButton, isSyncing && styles.buttonDisabled]}
          onPress={handleSync}
          disabled={isSyncing}
        >
          <Ionicons name="sync" size={18} color={colors.background} />
          <Text style={styles.syncButtonText}>
            {isSyncing ? t('loyalty.syncing') : t('loyalty.syncPoints')}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Messages */}
      {message ? (
        <View style={styles.successMessage}>
          <Text style={styles.successText}>{message}</Text>
        </View>
      ) : null}

      {error ? (
        <View style={styles.errorMessage}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : null}

      {/* Tabs */}
      <View style={styles.tabs}>
        <TouchableOpacity
          style={[styles.tab, activeTab === 'rewards' && styles.tabActive]}
          onPress={() => setActiveTab('rewards')}
        >
          <Text style={[styles.tabText, activeTab === 'rewards' && styles.tabTextActive]}>
            {t('loyalty.rewards')}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, activeTab === 'history' && styles.tabActive]}
          onPress={() => setActiveTab('history')}
        >
          <Text style={[styles.tabText, activeTab === 'history' && styles.tabTextActive]}>
            {t('loyalty.history')}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, activeTab === 'redemptions' && styles.tabActive]}
          onPress={() => setActiveTab('redemptions')}
        >
          <Text style={[styles.tabText, activeTab === 'redemptions' && styles.tabTextActive]}>
            {t('loyalty.yourCodes')}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Tab Content */}
      <View style={styles.tabContent}>
        {activeTab === 'rewards' && (
          rewards.length === 0 ? (
            <View style={styles.emptyState}>
              <Ionicons name="gift-outline" size={48} color={colors.textMuted} />
              <Text style={styles.emptyText}>{t('loyalty.noRewards')}</Text>
            </View>
          ) : (
            rewards.map((reward) => (
              <View key={reward.id} style={styles.rewardCard}>
                <View style={styles.rewardInfo}>
                  <Text style={styles.rewardName}>{reward.name}</Text>
                  {reward.description ? (
                    <Text style={styles.rewardDescription}>{reward.description}</Text>
                  ) : null}
                  <View style={styles.rewardMeta}>
                    <Text style={styles.rewardType}>{reward.reward_type_display}</Text>
                    {reward.discount_amount && (
                      <Text style={styles.rewardValue}>\u20ac{reward.discount_amount}</Text>
                    )}
                    {reward.discount_percentage && (
                      <Text style={styles.rewardValue}>{reward.discount_percentage}% off</Text>
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
            ))
          )
        )}

        {activeTab === 'history' && (
          transactions.length === 0 ? (
            <View style={styles.emptyState}>
              <Ionicons name="time-outline" size={48} color={colors.textMuted} />
              <Text style={styles.emptyText}>{t('loyalty.noTransactions')}</Text>
            </View>
          ) : (
            transactions.map((tx) => (
              <View key={tx.id} style={styles.transactionCard}>
                <View style={styles.transactionInfo}>
                  <Text style={styles.transactionDesc}>{tx.description}</Text>
                  <Text style={styles.transactionDate}>{formatDate(tx.created_at)}</Text>
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
            ))
          )
        )}

        {activeTab === 'redemptions' && (
          redemptions.length === 0 ? (
            <View style={styles.emptyState}>
              <Ionicons name="ticket-outline" size={48} color={colors.textMuted} />
              <Text style={styles.emptyText}>{t('loyalty.noCodes')}</Text>
            </View>
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
      </View>
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
    backgroundColor: colors.surface,
    margin: spacing.md,
    padding: spacing.lg,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.primary + '40',
    alignItems: 'center',
  },
  balanceHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  balanceTitle: {
    fontSize: 18,
    color: colors.textMuted,
  },
  balanceAmount: {
    fontSize: 48,
    fontWeight: '700',
    color: colors.primary,
  },
  balanceStats: {
    flexDirection: 'row',
    marginTop: spacing.md,
    marginBottom: spacing.lg,
  },
  stat: {
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
  },
  statValue: {
    fontSize: 18,
    fontWeight: '600',
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
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
    gap: spacing.sm,
  },
  syncButtonText: {
    color: colors.background,
    fontSize: 14,
    fontWeight: '600',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  successMessage: {
    backgroundColor: colors.success + '20',
    marginHorizontal: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
  },
  successText: {
    color: colors.success,
    textAlign: 'center',
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
    fontSize: 13,
    color: colors.textMuted,
    fontWeight: '500',
    textAlign: 'center',
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
  rewardCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
    flexDirection: 'row',
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  rewardInfo: {
    flex: 1,
  },
  rewardName: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text,
  },
  rewardDescription: {
    fontSize: 13,
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
    fontSize: 20,
    fontWeight: '700',
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
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  transactionInfo: {
    flex: 1,
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
    fontSize: 16,
    fontWeight: '600',
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
});
