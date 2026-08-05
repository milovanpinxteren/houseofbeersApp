import { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import {
  getTasteProfile,
  getUntappdProfile,
  TasteProfileResponse,
  UntappdProfile,
} from '../../../src/api/recommendations';
import { colors, spacing, borderRadius, fonts, type } from '../../../src/theme/colors';
import { Card, EmptyState, Screen, SectionHeader, Skeleton } from '../../../src/components/ui';

export default function TasteProfileScreen() {
  const { language } = useLanguage();
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [profile, setProfile] = useState<TasteProfileResponse | null>(null);
  const [untappdProfile, setUntappdProfile] = useState<UntappdProfile | null>(null);

  const loadData = useCallback(async () => {
    try {
      setError('');
      const [profileData, untappdData] = await Promise.all([
        getTasteProfile(),
        getUntappdProfile(),
      ]);
      setProfile(profileData);
      setUntappdProfile(untappdData.untappd);
    } catch (err) {
      console.log('[TasteProfile] Error:', err);
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

  // Simple radar chart using View transforms
  function renderRadarChart() {
    if (!profile?.radar_chart?.axes || profile.radar_chart.axes.length < 3) {
      return (
        <View style={styles.noChartContainer}>
          <Ionicons name="analytics-outline" size={40} color={colors.textMuted} />
          <Text style={styles.noChartText}>
            {profile?.message || t('recommendations.notEnoughData')}
          </Text>
        </View>
      );
    }

    const { axes, values } = profile.radar_chart;
    const numAxes = axes.length;
    const centerX = 150;
    const centerY = 150;
    const maxRadius = 100;

    // Generate grid circles and axis lines
    const gridCircles = [25, 50, 75, 100];

    return (
      <View style={styles.radarContainer}>
        <View style={styles.radarChart}>
          {/* Background circle */}
          <View style={styles.radarBackground} />

          {/* Grid circles */}
          {gridCircles.map((percent) => {
            const size = (percent / 100) * maxRadius * 2;
            return (
              <View
                key={`grid-${percent}`}
                style={[
                  styles.gridCircle,
                  {
                    width: size,
                    height: size,
                    left: centerX - size / 2,
                    top: centerY - size / 2,
                    borderRadius: size / 2,
                  },
                ]}
              />
            );
          })}

          {/* Axis lines */}
          {axes.map((_, i) => {
            const angle = (2 * Math.PI * i) / numAxes - Math.PI / 2;
            const endX = centerX + maxRadius * Math.cos(angle);
            const endY = centerY + maxRadius * Math.sin(angle);
            const length = Math.sqrt(Math.pow(endX - centerX, 2) + Math.pow(endY - centerY, 2));
            const rotation = (angle * 180) / Math.PI + 90;

            return (
              <View
                key={`line-${i}`}
                style={[
                  styles.axisLine,
                  {
                    left: centerX - 1,
                    top: centerY,
                    height: length,
                    transform: [{ rotate: `${rotation}deg` }],
                    transformOrigin: 'top center',
                  },
                ]}
              />
            );
          })}

          {/* Axis labels */}
          {axes.map((axis, i) => {
            const angle = (2 * Math.PI * i) / numAxes - Math.PI / 2;
            const labelRadius = maxRadius + 35;
            const x = centerX + labelRadius * Math.cos(angle) - 40;
            const y = centerY + labelRadius * Math.sin(angle) - 10;

            return (
              <View
                key={`axis-${i}`}
                style={[
                  styles.axisLabel,
                  { left: x, top: y },
                ]}
              >
                <Text style={styles.axisLabelText} numberOfLines={1}>
                  {axis}
                </Text>
              </View>
            );
          })}

          {/* Data points as dots */}
          {values.map((value, i) => {
            const angle = (2 * Math.PI * i) / numAxes - Math.PI / 2;
            // Monotonic boost: map (0, 100] onto [25, 100] so small values stay
            // visible without ever plotting a lower score outside a higher one
            const boostedValue = value > 0 ? 25 + value * 0.75 : 0;
            const radius = (boostedValue / 100) * maxRadius;
            const x = centerX + radius * Math.cos(angle) - 10;
            const y = centerY + radius * Math.sin(angle) - 10;

            return (
              <View
                key={`dot-${i}`}
                style={[
                  styles.dataPoint,
                  { left: x, top: y },
                ]}
              />
            );
          })}

          {/* Center dot */}
          <View style={styles.centerDot} />
        </View>
      </View>
    );
  }

  if (isLoading) {
    return (
      <Screen scroll={false}>
        <View style={styles.skeletonHeader}>
          <Skeleton width={42} height={42} radius={14} />
          <View style={{ flex: 1 }}>
            <Skeleton width="40%" height={11} />
            <Skeleton width="60%" height={14} style={{ marginTop: spacing.sm }} />
          </View>
        </View>
        <View style={styles.skeletonGrid}>
          {[0, 1, 2, 3].map((i) => (
            <View key={i} style={styles.skeletonTile}>
              <Skeleton width={22} height={22} radius={11} />
              <Skeleton width="55%" height={18} style={{ marginTop: spacing.sm }} />
              <Skeleton width="70%" height={11} style={{ marginTop: spacing.xs }} />
            </View>
          ))}
        </View>
        <Skeleton width={130} height={13} style={{ marginTop: spacing.lg }} />
        <Skeleton width="100%" height={260} radius={borderRadius.lg} style={{ marginTop: spacing.sm }} />
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

  return (
    <Screen refreshing={isRefreshing} onRefresh={handleRefresh}>
      {/* Profile Source */}
      <Card variant="elevated" style={styles.sourceCard}>
        <View style={styles.sourceRow}>
          <View style={styles.sourceIconWrap}>
            <Ionicons
              name={profile?.profile_source === 'untappd' ? 'beer' : 'cart'}
              size={20}
              color={colors.primary}
            />
          </View>
          <View style={styles.sourceInfo}>
            <Text style={styles.sourceLabel}>
              {profile?.profile_source === 'untappd'
                ? t('recommendations.untappdProfile')
                : t('recommendations.orderHistory')}
            </Text>
            <Text style={styles.sourceValue} numberOfLines={1}>
              {profile?.profile_source === 'untappd'
                ? untappdProfile?.username
                : profile?.profile_identifier}
            </Text>
          </View>
        </View>
      </Card>

      {/* Stats Grid */}
      <View style={styles.statsGrid}>
        <Card variant="inset" style={styles.statCard}>
          <Ionicons name="checkmark-circle" size={20} color={colors.primary} />
          <Text style={styles.statValue}>{profile?.total_checkins || 0}</Text>
          <Text style={styles.statLabel}>
            {profile?.profile_source === 'untappd'
              ? t('recommendations.checkins')
              : t('recommendations.purchased')}
          </Text>
        </Card>
        <Card variant="inset" style={styles.statCard}>
          <Ionicons name="beer" size={20} color={colors.primary} />
          <Text style={styles.statValue}>{profile?.unique_beers || 0}</Text>
          <Text style={styles.statLabel}>{t('recommendations.uniqueBeers')}</Text>
        </Card>
        <Card variant="inset" style={styles.statCard}>
          <Ionicons name="flask" size={20} color={colors.primary} />
          <Text style={styles.statValue}>{profile?.abv_profile?.range_label || '-'}</Text>
          <Text style={styles.statLabel}>{t('recommendations.abvRange')}</Text>
        </Card>
        {profile?.rating_profile && profile.profile_source === 'untappd' && (
          <Card variant="inset" style={styles.statCard}>
            <Ionicons name="star" size={20} color={colors.primary} />
            <Text style={styles.statValue}>
              {profile.rating_profile.average?.toFixed(1) || '-'}
            </Text>
            <Text style={styles.statLabel}>{t('recommendations.avgRating')}</Text>
          </Card>
        )}
      </View>

      {/* Radar Chart */}
      <SectionHeader title={t('recommendations.tasteWheel')} />
      <Card>
        {renderRadarChart()}
      </Card>

      {/* Style Distribution */}
      {profile?.style_distribution && profile.style_distribution.length > 0 && (
        <>
          <SectionHeader title={t('recommendations.styleDistribution')} />
          <Card>
            {profile.style_distribution.slice(0, 8).map((style, index) => (
              <View
                key={`style-${index}`}
                style={[styles.styleBar, index > 0 && { marginTop: spacing.md }]}
              >
                <View style={styles.styleInfo}>
                  <Text style={styles.styleName} numberOfLines={1}>{style.style}</Text>
                  <Text style={styles.styleCount}>{style.count}</Text>
                </View>
                <View style={styles.styleBarBg}>
                  <View
                    style={[
                      styles.styleBarFill,
                      { width: `${style.percentage}%` },
                    ]}
                  />
                </View>
              </View>
            ))}
          </Card>
        </>
      )}

      {/* Top Breweries */}
      {profile?.top_breweries && profile.top_breweries.length > 0 && (
        <>
          <SectionHeader title={t('recommendations.topBreweries')} />
          <Card padded={false}>
            {profile.top_breweries.slice(0, 5).map((brewery, index) => (
              <View
                key={`brewery-${index}`}
                style={[styles.breweryRow, index > 0 && styles.breweryRowDivider]}
              >
                <Text style={styles.breweryRank}>{index + 1}</Text>
                <Text style={styles.breweryName} numberOfLines={1}>
                  {brewery.brewery}
                </Text>
                <Text style={styles.breweryCount}>
                  {brewery.count} {t('recommendations.beers')}
                </Text>
              </View>
            ))}
          </Card>
        </>
      )}

      {/* ABV Category */}
      {profile?.abv_profile?.category && (
        <Card variant="accent" style={styles.categoryCard}>
          <View style={styles.categoryIconWrap}>
            <Ionicons name="ribbon" size={26} color={colors.primary} />
          </View>
          <Text style={styles.categoryTitle}>{profile.abv_profile.category}</Text>
          {profile.rating_profile?.category && (
            <Text style={styles.categorySubtitle}>{profile.rating_profile.category}</Text>
          )}
        </Card>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  centerContainer: {
    flex: 1,
    justifyContent: 'center',
  },

  // Skeletons
  skeletonHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.surfaceHigh,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginTop: spacing.md,
  },
  skeletonGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  skeletonTile: {
    width: '48%',
    flexGrow: 1,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
  },

  // Source Card
  sourceCard: {
    marginTop: spacing.md,
  },
  sourceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  sourceIconWrap: {
    width: 42,
    height: 42,
    borderRadius: 14,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  sourceInfo: {
    flex: 1,
  },
  sourceLabel: {
    ...type.label,
    fontSize: 11,
    letterSpacing: 1.4,
  },
  sourceValue: {
    fontFamily: fonts.heading,
    fontSize: 16,
    letterSpacing: 0.4,
    color: colors.text,
    marginTop: 1,
  },

  // Stats Grid
  statsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  statCard: {
    width: '48%',
    flexGrow: 1,
    alignItems: 'flex-start',
  },
  statValue: {
    fontFamily: fonts.headingBold,
    fontSize: 22,
    letterSpacing: 0.4,
    color: colors.text,
    marginTop: spacing.sm,
  },
  statLabel: {
    fontSize: 11,
    letterSpacing: 0.3,
    color: colors.textMuted,
    marginTop: 2,
  },

  // Radar Chart
  radarContainer: {
    alignItems: 'center',
    marginVertical: spacing.md,
  },
  radarChart: {
    width: 300,
    height: 300,
    position: 'relative',
  },
  radarBackground: {
    position: 'absolute',
    width: 200,
    height: 200,
    left: 50,
    top: 50,
    borderRadius: 100,
    backgroundColor: colors.surfaceHigh,
  },
  gridCircle: {
    position: 'absolute',
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: 'transparent',
  },
  axisLine: {
    position: 'absolute',
    width: 2,
    backgroundColor: colors.border,
  },
  axisLabel: {
    position: 'absolute',
    width: 80,
    alignItems: 'center',
  },
  axisLabelText: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    color: colors.textMuted,
    textAlign: 'center',
  },
  dataPoint: {
    position: 'absolute',
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: colors.primary,
    borderWidth: 3,
    borderColor: colors.secondary,
    shadowColor: colors.primary,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.8,
    shadowRadius: 6,
    elevation: 5,
  },
  centerDot: {
    position: 'absolute',
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.tertiary,
    left: 145,
    top: 145,
  },
  noChartContainer: {
    alignItems: 'center',
    padding: spacing.lg,
  },
  noChartText: {
    fontFamily: fonts.serif,
    fontSize: 15,
    lineHeight: 21,
    marginTop: spacing.md,
    color: colors.textMuted,
    textAlign: 'center',
  },

  // Style Distribution
  styleBar: {},
  styleInfo: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    gap: spacing.md,
    marginBottom: spacing.xs,
  },
  styleName: {
    fontFamily: fonts.serif,
    fontSize: 15,
    color: colors.text,
    flex: 1,
  },
  styleCount: {
    fontFamily: fonts.heading,
    fontSize: 13,
    letterSpacing: 0.4,
    color: colors.textMuted,
  },
  styleBarBg: {
    height: 6,
    backgroundColor: colors.surfaceLow,
    borderRadius: 3,
    overflow: 'hidden',
  },
  styleBarFill: {
    height: '100%',
    backgroundColor: colors.primary,
    borderRadius: 3,
  },

  // Top Breweries
  breweryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingVertical: 14,
    paddingHorizontal: spacing.md,
  },
  breweryRowDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  breweryRank: {
    fontFamily: fonts.headingBold,
    fontSize: 15,
    letterSpacing: 0.4,
    color: colors.primary,
    width: 20,
    textAlign: 'center',
  },
  breweryName: {
    fontFamily: fonts.serif,
    fontSize: 16,
    color: colors.text,
    flex: 1,
  },
  breweryCount: {
    fontSize: 12,
    color: colors.textMuted,
  },

  // Category Card
  categoryCard: {
    marginTop: spacing.lg,
    alignItems: 'center',
    paddingVertical: spacing.lg,
  },
  categoryIconWrap: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  categoryTitle: {
    fontFamily: fonts.heading,
    fontSize: 19,
    letterSpacing: 0.5,
    color: colors.primary,
    marginTop: spacing.sm,
    textAlign: 'center',
  },
  categorySubtitle: {
    fontFamily: fonts.serif,
    fontSize: 15,
    color: colors.textMuted,
    marginTop: 2,
    textAlign: 'center',
  },
});
