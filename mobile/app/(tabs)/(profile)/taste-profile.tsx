import { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  ScrollView,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
  Dimensions,
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
import { colors, spacing, borderRadius } from '../../../src/theme/colors';

const { width: screenWidth } = Dimensions.get('window');

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

  // Simple radar chart using View transforms
  function renderRadarChart() {
    if (!profile?.radar_chart?.axes || profile.radar_chart.axes.length < 3) {
      return (
        <View style={styles.noChartContainer}>
          <Ionicons name="analytics-outline" size={48} color={colors.textMuted} />
          <Text style={styles.noChartText}>{t('recommendations.notEnoughData')}</Text>
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
            const boostedValue = value > 0 && value < 25 ? 25 + value * 0.5 : value;
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
        {/* Profile Source */}
        <View style={styles.sourceCard}>
          <Ionicons
            name={profile?.profile_source === 'untappd' ? 'beer' : 'cart'}
            size={24}
            color={colors.primary}
          />
          <View style={styles.sourceInfo}>
            <Text style={styles.sourceLabel}>
              {profile?.profile_source === 'untappd'
                ? t('recommendations.untappdProfile')
                : t('recommendations.orderHistory')}
            </Text>
            <Text style={styles.sourceValue}>
              {profile?.profile_source === 'untappd'
                ? untappdProfile?.username
                : profile?.profile_identifier}
            </Text>
          </View>
        </View>

        {/* Stats Grid */}
        <View style={styles.statsGrid}>
          <View style={styles.statCard}>
            <Ionicons name="checkmark-circle" size={24} color={colors.primary} />
            <Text style={styles.statValue}>{profile?.total_checkins || 0}</Text>
            <Text style={styles.statLabel}>
              {profile?.profile_source === 'untappd'
                ? t('recommendations.checkins')
                : t('recommendations.purchased')}
            </Text>
          </View>
          <View style={styles.statCard}>
            <Ionicons name="beer" size={24} color={colors.primary} />
            <Text style={styles.statValue}>{profile?.unique_beers || 0}</Text>
            <Text style={styles.statLabel}>{t('recommendations.uniqueBeers')}</Text>
          </View>
          <View style={styles.statCard}>
            <Ionicons name="flask" size={24} color={colors.primary} />
            <Text style={styles.statValue}>{profile?.abv_profile?.range_label || '-'}</Text>
            <Text style={styles.statLabel}>{t('recommendations.abvRange')}</Text>
          </View>
          {profile?.rating_profile && profile.profile_source === 'untappd' && (
            <View style={styles.statCard}>
              <Ionicons name="star" size={24} color={colors.primary} />
              <Text style={styles.statValue}>
                {profile.rating_profile.average?.toFixed(1) || '-'}
              </Text>
              <Text style={styles.statLabel}>{t('recommendations.avgRating')}</Text>
            </View>
          )}
        </View>

        {/* Radar Chart */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{t('recommendations.tasteWheel')}</Text>
          {renderRadarChart()}
        </View>

        {/* Style Distribution */}
        {profile?.style_distribution && profile.style_distribution.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>{t('recommendations.styleDistribution')}</Text>
            {profile.style_distribution.slice(0, 8).map((style, index) => (
              <View key={`style-${index}`} style={styles.styleBar}>
                <View style={styles.styleInfo}>
                  <Text style={styles.styleName}>{style.style}</Text>
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
          </View>
        )}

        {/* ABV Category */}
        {profile?.abv_profile?.category && (
          <View style={styles.categoryCard}>
            <Ionicons name="ribbon" size={32} color={colors.primary} />
            <Text style={styles.categoryTitle}>{profile.abv_profile.category}</Text>
            {profile.rating_profile?.category && (
              <Text style={styles.categorySubtitle}>{profile.rating_profile.category}</Text>
            )}
          </View>
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
    color: colors.textMuted,
    fontSize: 14,
  },
  errorText: {
    marginTop: spacing.md,
    color: colors.error,
    fontSize: 14,
    textAlign: 'center',
  },

  // Source Card
  sourceCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    margin: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.primary + '40',
  },
  sourceInfo: {
    marginLeft: spacing.md,
  },
  sourceLabel: {
    fontSize: 12,
    color: colors.textMuted,
  },
  sourceValue: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text,
  },

  // Stats Grid
  statsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginHorizontal: spacing.sm,
  },
  statCard: {
    width: '50%',
    padding: spacing.sm,
  },
  statValue: {
    fontSize: 24,
    fontWeight: '700',
    color: colors.text,
    marginTop: spacing.xs,
  },
  statLabel: {
    fontSize: 12,
    color: colors.textMuted,
  },

  // Sections
  section: {
    margin: spacing.md,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text,
    marginBottom: spacing.md,
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
    backgroundColor: colors.surface,
  },
  gridCircle: {
    position: 'absolute',
    borderWidth: 1,
    borderColor: colors.tertiary + '40',
    backgroundColor: 'transparent',
  },
  axisLine: {
    position: 'absolute',
    width: 2,
    backgroundColor: colors.tertiary + '30',
  },
  axisLabel: {
    position: 'absolute',
    width: 80,
    alignItems: 'center',
  },
  axisLabelText: {
    fontSize: 11,
    color: colors.text,
    textAlign: 'center',
    fontWeight: '500',
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
    padding: spacing.xl,
  },
  noChartText: {
    marginTop: spacing.md,
    color: colors.textMuted,
    fontSize: 14,
    textAlign: 'center',
  },

  // Style Distribution
  styleBar: {
    marginBottom: spacing.sm,
  },
  styleInfo: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  styleName: {
    fontSize: 14,
    color: colors.text,
  },
  styleCount: {
    fontSize: 14,
    color: colors.textMuted,
  },
  styleBarBg: {
    height: 8,
    backgroundColor: colors.surface,
    borderRadius: 4,
    overflow: 'hidden',
  },
  styleBarFill: {
    height: '100%',
    backgroundColor: colors.primary,
    borderRadius: 4,
  },

  // Category Card
  categoryCard: {
    backgroundColor: colors.surface,
    margin: spacing.md,
    padding: spacing.lg,
    borderRadius: borderRadius.lg,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.primary + '40',
  },
  categoryTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.primary,
    marginTop: spacing.sm,
  },
  categorySubtitle: {
    fontSize: 14,
    color: colors.textMuted,
    marginTop: 4,
  },

  bottomPadding: {
    height: spacing.xl,
  },
});
