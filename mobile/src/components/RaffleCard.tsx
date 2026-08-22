import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ScrollView,
  StyleProp,
  StyleSheet,
  Text,
  View,
  ViewStyle,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import { t } from '../i18n';
import { colors, spacing, borderRadius, fonts } from '../theme/colors';
import { Card, SectionHeader } from './ui';
import { getRaffles, Raffle } from '../api/raffles';

function ticketLabel(count: number): string {
  return count === 1 ? t('raffle.oneTicket') : t('raffle.manyTickets', { count });
}

/**
 * A single raffle card. Four states:
 * - open + entered: "🎟️ Je doet mee" with ticket count and draw time
 * - open + not entered: teaser with the rule sentence
 * - drawn + result not seen: prominent "Bekijk de trekking"
 * - drawn + seen: compact winners line, code access for winners
 * Pressing always opens the raffle screen at /(tabs)/(profile)/raffle/{id}.
 */
export function RaffleCard({
  raffle,
  language,
  style,
}: {
  raffle: Raffle;
  language: string;
  style?: StyleProp<ViewStyle>;
}) {
  const locale = language === 'nl' ? 'nl-NL' : 'en-US';

  function formatDrawAt(iso: string): string {
    return new Date(iso).toLocaleString(locale, {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function open() {
    router.push(`/(tabs)/(profile)/raffle/${raffle.id}` as any);
  }

  const drawn = raffle.status === 'drawn';
  const winners = raffle.public_winner_names || raffle.winner_first_names || [];

  // Drawn, reveal not watched yet: the big call-to-action.
  if (drawn && !raffle.result_seen) {
    return (
      <Card variant="accent" onPress={open} style={[styles.card, style]}>
        <View style={styles.badgeRow}>
          <View style={styles.raffleBadge}>
            <Ionicons name="ticket" size={12} color={colors.primary} />
            <Text style={styles.raffleBadgeText}>{t('raffle.badge')}</Text>
          </View>
        </View>
        <Text style={styles.title}>{t('raffle.drawDone')}</Text>
        <Text style={styles.body} numberOfLines={2}>
          {t('raffle.drawDoneHint', { prize: raffle.prize_name })}
        </Text>
        <View style={styles.ctaRow}>
          <Ionicons name="play-circle" size={18} color={colors.primary} />
          <Text style={styles.ctaText}>{t('raffle.viewDraw')}</Text>
          <Ionicons name="chevron-forward" size={15} color={colors.primary} />
        </View>
      </Card>
    );
  }

  // Drawn and watched: compact winners recap.
  if (drawn) {
    return (
      <Card onPress={open} style={[styles.card, style]}>
        <View style={styles.compactRow}>
          <View style={styles.iconWrap}>
            <Ionicons name="trophy" size={20} color={colors.primary} />
          </View>
          <View style={styles.compactText}>
            <Text style={styles.compactTitle} numberOfLines={1}>
              {raffle.prize_name}
            </Text>
            <Text style={styles.compactSub} numberOfLines={1}>
              {winners.length > 0
                ? t('raffle.wonBy', { names: winners.join(', ') })
                : t('raffle.drawDone')}
            </Text>
            {raffle.did_win ? (
              <Text style={styles.compactWin}>{t('raffle.viewCode')}</Text>
            ) : null}
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
        </View>
      </Card>
    );
  }

  // Open + entered.
  if (raffle.entered) {
    return (
      <Card variant="accent" onPress={open} style={[styles.card, style]}>
        <View style={styles.badgeRow}>
          <View style={styles.raffleBadge}>
            <Ionicons name="ticket" size={12} color={colors.primary} />
            <Text style={styles.raffleBadgeText}>{t('raffle.badge')}</Text>
          </View>
          <Text style={styles.entrants}>
            {t('raffle.entrants', { count: raffle.entrant_count })}
          </Text>
        </View>
        <Text style={styles.title}>{t('raffle.entered')}</Text>
        <Text style={styles.body} numberOfLines={2}>
          {t('raffle.enteredBody', {
            tickets: ticketLabel(raffle.ticket_count),
            prize: raffle.prize_name,
          })}
        </Text>
        <View style={styles.metaRow}>
          <Ionicons name="time-outline" size={14} color={colors.textMuted} />
          <Text style={styles.metaText}>
            {raffle.draw_at
              ? t('raffle.drawAt', { date: formatDrawAt(raffle.draw_at) })
              : t('raffle.drawManual')}
          </Text>
        </View>
      </Card>
    );
  }

  // Open + not entered: teaser explaining how to join.
  return (
    <Card onPress={open} style={[styles.card, style]}>
      <View style={styles.badgeRow}>
        <View style={styles.raffleBadge}>
          <Ionicons name="ticket" size={12} color={colors.primary} />
          <Text style={styles.raffleBadgeText}>{t('raffle.badge')}</Text>
        </View>
      </View>
      <Text style={styles.title}>{t('raffle.teaserTitle', { prize: raffle.prize_name })}</Text>
      {raffle.rule_sentence ? (
        <Text style={styles.body} numberOfLines={3}>
          {raffle.rule_sentence}
        </Text>
      ) : null}
      <View style={styles.ctaRow}>
        <Text style={styles.ctaText}>{t('raffle.teaserHint')}</Text>
        <Ionicons name="chevron-forward" size={15} color={colors.primary} />
      </View>
    </Card>
  );
}

/**
 * Self-contained raffles section: fetches on focus (so returning from the
 * reveal updates the card state) and when `refreshSignal` changes (wired to
 * the host's pull-to-refresh). Renders NOTHING when there are no raffles —
 * the normal state.
 *
 * Two variants keep Home clean when draws pile up:
 * - 'active' (Home + Loyalty top): open raffles and a finished draw the user
 *   hasn't watched yet. Once the reveal is watched the card leaves here.
 * - 'history' (Loyalty codes tab): watched past draws as a compact vertical
 *   list — the archive, with code access for wins.
 */
export function RaffleSection({
  language,
  refreshSignal = 0,
  style,
  variant = 'active',
  onCount,
}: {
  language: string;
  refreshSignal?: number;
  style?: StyleProp<ViewStyle>;
  variant?: 'active' | 'history';
  /** Reports how many raffles this section shows (0 when hidden), so a host
      screen can adapt around it — e.g. the Loyalty codes tab hides its
      "no codes" empty state when the draw archive has rows. */
  onCount?: (count: number) => void;
}) {
  const [raffles, setRaffles] = useState<Raffle[]>([]);
  // Ref so an inline callback prop can't retrigger the focus-fetch loop.
  const onCountRef = useRef(onCount);
  onCountRef.current = onCount;

  const fetchRaffles = useCallback(async () => {
    try {
      const data = await getRaffles();
      const isHistory = (r: Raffle) => r.status === 'drawn' && r.result_seen;
      const mine = data.raffles.filter((r) =>
        variant === 'history' ? isHistory(r) : !isHistory(r)
      );
      // Most actionable first: unseen draws, then open raffles, then recaps.
      // History keeps the API's newest-draw-first order (rank ties).
      const rank = (r: Raffle) =>
        r.status === 'drawn' && !r.result_seen ? 0 : r.status === 'open' ? (r.entered ? 1 : 2) : 3;
      setRaffles(mine.sort((a, b) => rank(a) - rank(b)));
      onCountRef.current?.(mine.length);
    } catch {
      // Backend without the endpoint yet, or a transient error: show nothing.
      setRaffles([]);
      onCountRef.current?.(0);
    }
  }, [variant]);

  useFocusEffect(
    useCallback(() => {
      fetchRaffles();
    }, [fetchRaffles])
  );

  useEffect(() => {
    if (refreshSignal > 0) {
      fetchRaffles();
    }
  }, [refreshSignal, fetchRaffles]);

  if (raffles.length === 0) {
    return null;
  }

  // History: always a compact vertical list — an archive, not a carousel.
  if (variant === 'history') {
    return (
      <View style={style}>
        <SectionHeader title={t('raffle.historyTitle')} />
        {raffles.map((raffle) => (
          <RaffleCard key={raffle.id} raffle={raffle} language={language} />
        ))}
      </View>
    );
  }

  return (
    <View style={style}>
      <SectionHeader title={t('raffle.sectionTitle')} />
      {raffles.length === 1 ? (
        <RaffleCard raffle={raffles[0]} language={language} />
      ) : (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.rail}
          contentContainerStyle={styles.railContent}
        >
          {raffles.map((raffle) => (
            <RaffleCard
              key={raffle.id}
              raffle={raffle}
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
  raffleBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: colors.primary + '1A',
    borderRadius: borderRadius.pill,
    paddingHorizontal: 9,
    paddingVertical: 3,
  },
  raffleBadgeText: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    color: colors.primary,
  },
  entrants: {
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
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginTop: spacing.sm,
  },
  metaText: {
    fontSize: 12,
    color: colors.textMuted,
  },
  ctaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginTop: spacing.sm,
  },
  ctaText: {
    fontFamily: fonts.heading,
    fontSize: 13,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    color: colors.primary,
  },
  compactRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  iconWrap: {
    width: 42,
    height: 42,
    borderRadius: 14,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  compactText: {
    flex: 1,
  },
  compactTitle: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.4,
    color: colors.text,
  },
  compactSub: {
    fontFamily: fonts.serif,
    fontSize: 14,
    color: colors.textMuted,
    marginTop: 1,
  },
  compactWin: {
    fontSize: 12,
    color: colors.primary,
    fontWeight: '600',
    marginTop: 2,
  },
});
