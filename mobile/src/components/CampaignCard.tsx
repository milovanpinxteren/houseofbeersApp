import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Pressable,
  ScrollView,
  StyleProp,
  StyleSheet,
  Text,
  View,
  ViewStyle,
} from 'react-native';
import * as Clipboard from 'expo-clipboard';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import { t } from '../i18n';
import { colors, spacing, borderRadius, fonts } from '../theme/colors';
import { Card, SectionHeader } from './ui';
import { getCampaigns, AppCampaign } from '../api/campaigns';

/**
 * A single campaign ("actie") card. Three states:
 * - not qualified: teaser with the rule sentence and the end date
 * - qualified, points: "Je hebt X punten verdiend"
 * - qualified, discount code: copyable code with expiry
 */
export function CampaignCard({
  campaign,
  language,
  style,
}: {
  campaign: AppCampaign;
  language: string;
  style?: StyleProp<ViewStyle>;
}) {
  const locale = language === 'nl' ? 'nl-NL' : 'en-US';
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (copyTimer.current) clearTimeout(copyTimer.current);
  }, []);

  function formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString(locale, {
      day: 'numeric',
      month: 'short',
    });
  }

  async function copyCode(code: string) {
    await Clipboard.setStringAsync(code);
    setCopied(true);
    copyTimer.current = setTimeout(() => setCopied(false), 2000);
  }

  // Qualified: show what was earned.
  if (campaign.qualified) {
    return (
      <Card variant="accent" style={[styles.card, style]}>
        <View style={styles.badgeRow}>
          <View style={styles.badge}>
            <Ionicons name="sparkles" size={12} color={colors.primary} />
            <Text style={styles.badgeText}>{t('campaign.badge')}</Text>
          </View>
        </View>
        {campaign.action_type === 'points' && campaign.points_awarded > 0 ? (
          <>
            <Text style={styles.title}>
              {t('campaign.earnedPoints', { points: campaign.points_awarded })}
            </Text>
            <Text style={styles.body} numberOfLines={2}>{campaign.name}</Text>
          </>
        ) : campaign.discount_code ? (
          <>
            <Text style={styles.title}>{t('campaign.earnedCode')}</Text>
            <Pressable
              style={({ pressed }) => [styles.codeBox, pressed && { opacity: 0.8 }]}
              onPress={() => copyCode(campaign.discount_code!)}
            >
              <View style={styles.codeLeft}>
                <Text style={styles.codeText}>{campaign.discount_code}</Text>
                <Text style={styles.copyHint}>
                  {copied ? t('campaign.copied') : t('campaign.tapToCopy')}
                </Text>
              </View>
              <Ionicons
                name={copied ? 'checkmark-circle' : 'copy-outline'}
                size={20}
                color={copied ? colors.success : colors.primary}
              />
            </Pressable>
            {campaign.discount_expires_at ? (
              <Text style={styles.expiresText}>
                {t('campaign.codeExpires', {
                  date: formatDate(campaign.discount_expires_at),
                })}
              </Text>
            ) : null}
          </>
        ) : (
          <>
            <Text style={styles.title}>{t('campaign.qualifiedTitle')}</Text>
            <Text style={styles.body} numberOfLines={2}>{campaign.name}</Text>
          </>
        )}
      </Card>
    );
  }

  // Not qualified: teaser explaining how to earn.
  return (
    <Card style={[styles.card, style]}>
      <View style={styles.badgeRow}>
        <View style={styles.badge}>
          <Ionicons name="sparkles" size={12} color={colors.primary} />
          <Text style={styles.badgeText}>{t('campaign.badge')}</Text>
        </View>
        <Text style={styles.until}>
          {t('campaign.until', { date: formatDate(campaign.window_end) })}
        </Text>
      </View>
      <Text style={styles.title}>{campaign.name}</Text>
      {campaign.rule_sentence ? (
        <Text style={styles.body} numberOfLines={3}>{campaign.rule_sentence}</Text>
      ) : null}
    </Card>
  );
}

/**
 * Self-contained campaigns section ("Acties"): fetches on focus and when
 * `refreshSignal` changes; renders NOTHING when there are no campaigns —
 * the normal state. Mirrors RaffleSection.
 */
export function CampaignSection({
  language,
  refreshSignal = 0,
  style,
}: {
  language: string;
  refreshSignal?: number;
  style?: StyleProp<ViewStyle>;
}) {
  const [campaigns, setCampaigns] = useState<AppCampaign[]>([]);

  const fetchCampaigns = useCallback(async () => {
    try {
      const data = await getCampaigns();
      // Fresh wins first, then open teasers (soonest ending first — the API
      // orders active by window_end already).
      const rank = (c: AppCampaign) => (c.qualified ? 0 : 1);
      setCampaigns([...data.campaigns].sort((a, b) => rank(a) - rank(b)));
    } catch {
      // Backend without the endpoint yet, or a transient error: show nothing.
      setCampaigns([]);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchCampaigns();
    }, [fetchCampaigns])
  );

  useEffect(() => {
    if (refreshSignal > 0) {
      fetchCampaigns();
    }
  }, [refreshSignal, fetchCampaigns]);

  if (campaigns.length === 0) {
    return null;
  }

  return (
    <View style={style}>
      <SectionHeader title={t('campaign.sectionTitle')} />
      {campaigns.length === 1 ? (
        <CampaignCard campaign={campaigns[0]} language={language} />
      ) : (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.rail}
          contentContainerStyle={styles.railContent}
        >
          {campaigns.map((campaign) => (
            <CampaignCard
              key={campaign.id}
              campaign={campaign}
              language={language}
              style={styles.railCard}
            />
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginBottom: spacing.sm,
  },
  rail: {
    marginHorizontal: -spacing.md,
  },
  railContent: {
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  railCard: {
    width: 280,
    marginBottom: spacing.sm,
  },
  badgeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: colors.primary + '1A',
    borderRadius: borderRadius.pill,
    paddingHorizontal: 9,
    paddingVertical: 3,
  },
  badgeText: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    color: colors.primary,
  },
  until: {
    fontSize: 12,
    color: colors.textMuted,
  },
  title: {
    fontFamily: fonts.heading,
    fontSize: 17,
    letterSpacing: 0.4,
    color: colors.text,
    marginBottom: 4,
  },
  body: {
    fontFamily: fonts.serif,
    fontSize: 15,
    lineHeight: 21,
    color: colors.textMuted,
  },
  codeBox: {
    backgroundColor: colors.primary + '15',
    padding: spacing.md,
    borderRadius: borderRadius.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: spacing.xs,
  },
  codeLeft: {
    flex: 1,
  },
  codeText: {
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
  expiresText: {
    fontSize: 11,
    color: colors.warning,
    marginTop: spacing.xs,
  },
});
