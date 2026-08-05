import { useCallback, useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import { useLanguage } from '../../src/context/LanguageContext';
import { t } from '../../src/i18n';
import { colors, spacing, fonts, type } from '../../src/theme/colors';
import { Card, Screen, SectionHeader, Badge } from '../../src/components/ui';
import { getFavorites } from '../../src/api/recommendations';

export default function OntdekScreen() {
  const router = useRouter();
  const { language } = useLanguage();
  const [favoritesCount, setFavoritesCount] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const favoritesData = await getFavorites();
      setFavoritesCount(favoritesData.favorites.length);
    } catch (err) {
      console.log('[Ontdek] Load error:', err);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      loadData();
    }, [loadData])
  );

  async function handleRefresh() {
    setRefreshing(true);
    await loadData();
    setRefreshing(false);
  }

  return (
    <Screen refreshing={refreshing} onRefresh={handleRefresh}>
      <Text style={styles.intro}>{t('discover.intro')}</Text>

      <SectionHeader title={t('discover.forYou')} />

      {/* Hero: recommendations */}
      <Card
        variant="accent"
        onPress={() => router.push('/(profile)/recommendations' as any)}
        style={styles.heroCard}
      >
        <View style={styles.heroIconWrap}>
          <Ionicons name="beer" size={30} color={colors.primary} />
        </View>
        <View style={styles.heroText}>
          <Text style={styles.heroTitle}>{t('discover.recommendationsTitle')}</Text>
          <Text style={styles.heroSubtitle}>{t('discover.recommendationsSubtitle')}</Text>
        </View>
        <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
      </Card>

      {/* Taste profile + favorites side by side */}
      <View style={styles.tileRow}>
        <Card
          onPress={() => router.push('/(profile)/taste-profile' as any)}
          style={styles.tile}
        >
          <Ionicons name="analytics" size={24} color={colors.primary} />
          <Text style={styles.tileTitle}>{t('discover.tasteProfileTitle')}</Text>
          <Text style={styles.tileSubtitle} numberOfLines={2}>
            {t('discover.tasteProfileSubtitle')}
          </Text>
        </Card>
        <Card
          onPress={() => router.push('/(profile)/favorites' as any)}
          style={styles.tile}
        >
          <View style={styles.tileHeader}>
            <Ionicons name="heart" size={24} color={colors.secondary} />
            {favoritesCount > 0 && <Badge value={favoritesCount} />}
          </View>
          <Text style={styles.tileTitle}>{t('discover.favoritesTitle')}</Text>
          <Text style={styles.tileSubtitle} numberOfLines={2}>
            {t('discover.favoritesSubtitle')}
          </Text>
        </Card>
      </View>

      {/* Random beer roulette */}
      <Card
        variant="elevated"
        onPress={() => router.push('/(profile)/random-beer' as any)}
        style={styles.rouletteCard}
      >
        <View style={styles.rouletteIconWrap}>
          <Ionicons name="dice" size={28} color={colors.primary} />
          <Ionicons
            name="sparkles"
            size={14}
            color={colors.primary}
            style={styles.rouletteSparkle}
          />
        </View>
        <View style={styles.heroText}>
          <Text style={styles.heroTitle}>{t('randomBeer.cardTitle')}</Text>
          <Text style={styles.heroSubtitle}>{t('randomBeer.cardSubtitle')}</Text>
        </View>
        <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
      </Card>

    </Screen>
  );
}

const styles = StyleSheet.create({
  intro: {
    ...type.serifLarge,
    fontFamily: fonts.serifItalic,
    color: colors.textMuted,
    marginTop: spacing.md,
  },
  heroCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.sm,
  },
  heroIconWrap: {
    width: 56,
    height: 56,
    borderRadius: 18,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  heroText: {
    flex: 1,
  },
  heroTitle: {
    fontFamily: fonts.heading,
    fontSize: 18,
    letterSpacing: 0.5,
    color: colors.text,
  },
  heroSubtitle: {
    fontFamily: fonts.serif,
    fontSize: 14,
    color: colors.textMuted,
    marginTop: 2,
  },
  rouletteCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.sm,
  },
  rouletteIconWrap: {
    width: 56,
    height: 56,
    borderRadius: 18,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  rouletteSparkle: {
    position: 'absolute',
    top: 8,
    right: 8,
  },
  tileRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  tile: {
    flex: 1,
    gap: spacing.xs,
  },
  tileHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  tileTitle: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.4,
    color: colors.text,
    marginTop: spacing.xs,
  },
  tileSubtitle: {
    fontSize: 12,
    lineHeight: 16,
    color: colors.textMuted,
  },
});
