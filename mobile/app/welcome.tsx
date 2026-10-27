import { useEffect, useState } from 'react';
import { Linking, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Redirect, router, useLocalSearchParams } from 'expo-router';
import { useAuth } from '../src/context/AuthContext';
import { useLanguage } from '../src/context/LanguageContext';
import { t } from '../src/i18n';
import { colors, spacing, borderRadius, fonts, type } from '../src/theme/colors';
import { Button, Card, Screen } from '../src/components/ui';
import { WHATSAPP_COMMUNITY_URL } from '../src/constants/community';
import { getRewards, Reward } from '../src/api/loyalty';

/**
 * The last step of the signup funnel: webshop popup -> register -> WhatsApp
 * community. Reached with `router.replace` from the register screen ONLY, so
 * logging in normally still lands straight on the tabs. Replacing (not
 * pushing) also means back never walks into a half-finished registration.
 *
 * `points` is the welcome bonus the register response reported. It is a
 * param rather than a fetch: the register endpoint is the only place that
 * says how much THIS registration earned.
 */
export default function WelcomeScreen() {
  const params = useLocalSearchParams<{ points?: string }>();
  const { isAuthenticated, isLoading } = useAuth();
  const { language } = useLanguage();

  const points = Math.max(0, Math.floor(Number(params.points) || 0));
  // null until the reward ladder answers (or fails). We never name a euro
  // amount of our own: it comes from the rewards the shop actually offers.
  const [rewardLabel, setRewardLabel] = useState<string | null>(null);

  useEffect(() => {
    if (points <= 0) return;
    let cancelled = false;

    getRewards()
      .then((response) => {
        if (cancelled) return;
        const all = [
          ...response.categories.flatMap((category) => category.rewards),
          ...response.uncategorized,
        ];
        // The best thing the bonus alone already buys. Nothing affordable
        // (or no ladder at all) leaves the points-only line standing, which
        // is always true.
        const best = all
          .filter((reward) => reward.is_active && reward.points_cost > 0)
          .filter((reward) => reward.points_cost <= points)
          .sort((a, b) => b.points_cost - a.points_cost)[0];
        if (best) setRewardLabel(describeReward(best, language));
      })
      .catch(() => {
        // Offline or a backend hiccup: say less rather than guess.
      });

    return () => {
      cancelled = true;
    };
  }, [points, language]);

  function goToApp() {
    router.replace('/(tabs)');
  }

  function joinCommunity() {
    Linking.openURL(WHATSAPP_COMMUNITY_URL).catch(() => {});
    // On web the invite opens in a new tab, so hand the original tab over to
    // the app: coming back must not land on a step that is already done.
    goToApp();
  }

  // Deep link or a reload on this route without an account: there is nothing
  // to welcome. Send them through the normal launch instead.
  if (!isLoading && !isAuthenticated) {
    return <Redirect href="/(auth)/login" />;
  }

  return (
    <Screen maxContentWidth={520}>
      <View style={styles.header}>
        <Text style={styles.kicker}>{t('welcome.kicker')}</Text>
        <Text style={styles.title}>{t('welcome.title')}</Text>
        <Text style={styles.intro}>{t('welcome.intro')}</Text>
      </View>

      {points > 0 ? (
        <Card variant="accent" style={styles.bonusCard}>
          <View style={styles.bonusHeader}>
            <View style={styles.iconWrap}>
              <Ionicons name="star" size={22} color={colors.primary} />
            </View>
            <Text style={styles.bonusLabel}>{t('welcome.bonusLabel')}</Text>
          </View>
          <Text style={styles.bonusPoints}>{t('welcome.bonusPoints', { points })}</Text>
          <Text style={styles.bonusWorth}>
            {rewardLabel
              ? t('welcome.bonusWorth', { reward: rewardLabel })
              : t('welcome.bonusPointsOnly')}
          </Text>
        </Card>
      ) : null}

      <Card style={styles.whatsappCard}>
        <View style={styles.bonusHeader}>
          <View style={styles.iconWrap}>
            <Ionicons name="logo-whatsapp" size={22} color={colors.primary} />
          </View>
          <Text style={styles.whatsappTitle}>{t('welcome.whatsappTitle')}</Text>
        </View>
        <Text style={styles.whatsappBody}>{t('welcome.whatsappBody')}</Text>
        <Button
          label={t('welcome.join')}
          icon="logo-whatsapp"
          onPress={joinCommunity}
          style={styles.joinButton}
        />
      </Card>

      <Button label={t('welcome.skip')} variant="ghost" onPress={goToApp} />
    </Screen>
  );
}

/**
 * What a reward is worth, in the shop's own numbers. Falls back to the
 * reward's name for types that carry no amount (free shipping, free product)
 * so the line never reads as a broken template.
 */
function describeReward(reward: Reward, language: string): string {
  if (reward.discount_amount) {
    const amount = parseFloat(reward.discount_amount);
    if (!Number.isNaN(amount)) {
      return t('welcome.rewardAmount', { amount: formatAmount(amount, language) });
    }
  }
  if (reward.discount_percentage) {
    const percentage = parseFloat(reward.discount_percentage);
    if (!Number.isNaN(percentage)) {
      return t('welcome.rewardPercentage', { percent: formatAmount(percentage, language) });
    }
  }
  return reward.name;
}

/** Decimal strings come off the API as "5.00"; show "5", and "7,50" in Dutch. */
function formatAmount(value: number, language: string): string {
  return value.toLocaleString(language === 'nl' ? 'nl-NL' : 'en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

const styles = StyleSheet.create({
  header: {
    paddingTop: spacing.xl,
    paddingBottom: spacing.lg,
  },
  kicker: {
    ...type.label,
    color: colors.primary,
  },
  title: {
    ...type.display,
    marginTop: spacing.xs,
  },
  intro: {
    ...type.serifLarge,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
  bonusCard: {
    marginBottom: spacing.md,
  },
  bonusHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  iconWrap: {
    width: 40,
    height: 40,
    borderRadius: borderRadius.md,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  bonusLabel: {
    ...type.label,
    flex: 1,
  },
  bonusPoints: {
    fontFamily: fonts.headingBold,
    fontSize: 34,
    letterSpacing: 0.5,
    color: colors.primary,
    marginTop: spacing.md,
  },
  bonusWorth: {
    ...type.serifBody,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  whatsappCard: {
    marginBottom: spacing.md,
  },
  whatsappTitle: {
    ...type.heading,
    flex: 1,
  },
  whatsappBody: {
    ...type.serifBody,
    color: colors.textMuted,
    marginTop: spacing.md,
  },
  joinButton: {
    marginTop: spacing.md,
  },
});
