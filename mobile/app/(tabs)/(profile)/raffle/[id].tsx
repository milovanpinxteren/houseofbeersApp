import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useLanguage } from '../../../../src/context/LanguageContext';
import { t } from '../../../../src/i18n';
import { colors, spacing, borderRadius, fonts, type } from '../../../../src/theme/colors';
import { Card, EmptyState, Screen } from '../../../../src/components/ui';
import { RaffleReveal } from '../../../../src/components/RaffleReveal';
import {
  getRaffles,
  markRaffleSeen,
  markRaffleResultSeen,
  Raffle,
} from '../../../../src/api/raffles';

/** Live countdown to the draw: D/H/M tiles, seconds ticking under a day. */
function DrawCountdown({ target }: { target: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, []);

  const diff = Math.floor((new Date(target).getTime() - now) / 1000);
  if (diff <= 0) {
    return <Text style={styles.anyMoment}>{t('raffle.drawAnyMoment')}</Text>;
  }
  const days = Math.floor(diff / 86400);
  const cells: Array<[number, string]> = [
    ...(days > 0 ? ([[days, t('raffle.days')]] as Array<[number, string]>) : []),
    [Math.floor((diff % 86400) / 3600), t('raffle.hours')],
    [Math.floor((diff % 3600) / 60), t('raffle.minutes')],
    ...(days === 0 ? ([[diff % 60, t('raffle.seconds')]] as Array<[number, string]>) : []),
  ];
  return (
    <View style={styles.countdownRow}>
      {cells.map(([value, label], index) => (
        <View key={index} style={styles.countdownTile}>
          <Text style={styles.countdownValue}>{String(value).padStart(2, '0')}</Text>
          <Text style={styles.countdownLabel}>{label}</Text>
        </View>
      ))}
    </View>
  );
}

export default function RaffleScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const raffleId = Number(id);
  const { language } = useLanguage();
  const locale = language === 'nl' ? 'nl-NL' : 'en-US';

  const [raffle, setRaffle] = useState<Raffle | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // Frozen on first load so a refetch doesn't flip autoPlay mid-visit.
  const [autoPlay, setAutoPlay] = useState<boolean | null>(null);
  const seenMarked = useRef(false);
  const resultMarked = useRef(false);

  const load = useCallback(async () => {
    try {
      const data = await getRaffles();
      const found = data.raffles.find((r) => r.id === raffleId) || null;
      setRaffle(found);
      if (found) {
        setAutoPlay((prev) => (prev === null ? !found.result_seen : prev));
        // Pre-draw: opening this screen counts as "seen the raffle".
        if (found.status === 'open' && !found.seen && !seenMarked.current) {
          seenMarked.current = true;
          markRaffleSeen(found.id).catch(() => {});
        }
        if (found.result_seen) {
          resultMarked.current = true;
        }
      }
    } catch (err) {
      console.log('[Raffle] Load error:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [raffleId]);

  // On focus, not mount: the stack keeps this screen alive, so returning
  // after the draw must refetch or the user sees the stale pre-draw state.
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    load();
  }, [load]);

  // The reveal finished playing: record that the user watched the draw.
  const handleRevealComplete = useCallback(() => {
    if (resultMarked.current) return;
    resultMarked.current = true;
    markRaffleResultSeen(raffleId).catch(() => {});
  }, [raffleId]);

  const formatDate = useCallback(
    (iso: string) =>
      new Date(iso).toLocaleDateString(locale, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      }),
    [locale]
  );

  const formatDrawAt = useCallback(
    (iso: string) =>
      new Date(iso).toLocaleString(locale, {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
        hour: '2-digit',
        minute: '2-digit',
      }),
    [locale]
  );

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (!raffle) {
    // Also the fetch-failure state: pull-to-refresh retries the load.
    return (
      <Screen refreshing={refreshing} onRefresh={onRefresh}>
        <EmptyState icon="ticket-outline" title={t('raffle.notFound')} />
      </Screen>
    );
  }

  const drawn = raffle.status === 'drawn';
  const winners = raffle.public_winner_names || raffle.winner_first_names || [];

  return (
    <Screen refreshing={refreshing} onRefresh={onRefresh}>
      {drawn ? (
        <>
          {/* Post-draw: the reveal, then the prize context below it */}
          <View style={styles.revealWrap}>
            <RaffleReveal
              entrantNames={raffle.entrant_first_names || []}
              winnerNames={winners}
              prizeName={raffle.prize_name}
              didWin={raffle.did_win === true}
              myCode={raffle.my_code}
              myCodeExpiresAt={raffle.my_code_expires_at}
              autoPlay={autoPlay !== false}
              formatDate={formatDate}
              onComplete={handleRevealComplete}
            />
          </View>
          <Card style={styles.sectionCard}>
            <Text style={styles.sectionLabel}>{t('raffle.prizeLabel')}</Text>
            <Text style={styles.prizeName}>{raffle.prize_name}</Text>
            {raffle.prize_image_url ? (
              <Image
                source={{ uri: raffle.prize_image_url }}
                style={styles.prizeImage}
                resizeMode="cover"
              />
            ) : null}
            {raffle.prize_description ? (
              <Text style={styles.prizeDescription}>{raffle.prize_description}</Text>
            ) : null}
          </Card>
        </>
      ) : (
        <>
          {/* Pre-draw: prize, how to enter, your tickets, draw time */}
          {raffle.prize_image_url ? (
            <Image
              source={{ uri: raffle.prize_image_url }}
              style={styles.prizeImage}
              resizeMode="cover"
            />
          ) : null}

          <View style={styles.badgeRow}>
            <View style={styles.raffleBadge}>
              <Ionicons name="ticket" size={12} color={colors.primary} />
              <Text style={styles.raffleBadgeText}>{t('raffle.badge')}</Text>
            </View>
          </View>
          <Text style={styles.prizeName}>{raffle.prize_name}</Text>
          {raffle.prize_description ? (
            <Text style={styles.prizeDescription}>{raffle.prize_description}</Text>
          ) : null}

          {raffle.entered ? (
            <Card variant="accent" style={styles.sectionCard}>
              <View style={styles.enteredRow}>
                <Text style={styles.enteredTitle}>{t('raffle.entered')}</Text>
                <View style={styles.ticketPill}>
                  <Ionicons name="ticket" size={13} color={colors.background} />
                  <Text style={styles.ticketPillText}>
                    {raffle.ticket_count === 1
                      ? t('raffle.oneTicket')
                      : t('raffle.manyTickets', { count: raffle.ticket_count })}
                  </Text>
                </View>
              </View>
              {raffle.matched_products.length > 0 ? (
                <>
                  <Text style={styles.matchedLabel}>{t('raffle.matchedProducts')}</Text>
                  {raffle.matched_products.map((product, index) => (
                    <View key={index} style={styles.matchedRow}>
                      <Ionicons name="beer-outline" size={14} color={colors.primary} />
                      <Text style={styles.matchedText}>{product}</Text>
                    </View>
                  ))}
                </>
              ) : null}
              <Text style={styles.goodLuck}>{t('raffle.goodLuck')}</Text>
            </Card>
          ) : null}

          {raffle.rule_sentence ? (
            <Card style={styles.sectionCard}>
              <Text style={styles.sectionLabel}>{t('raffle.howToEnter')}</Text>
              <Text style={styles.ruleSentence}>{raffle.rule_sentence}</Text>
            </Card>
          ) : null}

          {raffle.draw_at ? (
            <Card style={styles.sectionCard}>
              <Text style={styles.sectionLabel}>{t('raffle.drawIn')}</Text>
              <DrawCountdown target={raffle.draw_at} />
              <View style={[styles.metaRow, styles.entrantsRow]}>
                <Ionicons name="people-outline" size={16} color={colors.textMuted} />
                <Text style={styles.metaText}>
                  {t('raffle.entrants', { count: raffle.entrant_count })}
                </Text>
              </View>
              <View style={styles.metaRow}>
                <Ionicons name="time-outline" size={16} color={colors.textMuted} />
                <Text style={styles.metaText}>
                  {t('raffle.drawAt', { date: formatDrawAt(raffle.draw_at) })}
                </Text>
              </View>
            </Card>
          ) : (
            <View style={styles.metaBox}>
              <View style={styles.metaRow}>
                <Ionicons name="time-outline" size={16} color={colors.textMuted} />
                <Text style={styles.metaText}>{t('raffle.drawManual')}</Text>
              </View>
              <View style={styles.metaRow}>
                <Ionicons name="people-outline" size={16} color={colors.textMuted} />
                <Text style={styles.metaText}>
                  {t('raffle.entrants', { count: raffle.entrant_count })}
                </Text>
              </View>
            </View>
          )}
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  revealWrap: {
    marginTop: spacing.md,
    marginBottom: spacing.md,
  },
  prizeImage: {
    width: '100%',
    aspectRatio: 1.5,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.surfaceLow,
    marginTop: spacing.md,
    marginBottom: spacing.md,
  },
  badgeRow: {
    flexDirection: 'row',
    marginTop: spacing.sm,
    marginBottom: spacing.sm,
  },
  raffleBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: colors.primary + '1A',
    borderRadius: borderRadius.pill,
    paddingHorizontal: 9,
    paddingVertical: 4,
  },
  raffleBadgeText: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    color: colors.primary,
  },
  prizeName: {
    ...type.title,
    marginBottom: spacing.xs,
  },
  prizeDescription: {
    fontFamily: fonts.serif,
    fontSize: 15,
    lineHeight: 22,
    color: colors.textMuted,
    marginBottom: spacing.sm,
  },
  sectionCard: {
    marginTop: spacing.sm,
  },
  enteredRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  enteredTitle: {
    fontFamily: fonts.heading,
    fontSize: 16,
    letterSpacing: 0.4,
    color: colors.text,
    flexShrink: 1,
  },
  ticketPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: colors.primary,
    borderRadius: borderRadius.pill,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  ticketPillText: {
    fontFamily: fonts.heading,
    fontSize: 12,
    color: colors.background,
    letterSpacing: 0.4,
  },
  matchedLabel: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: colors.textMuted,
    marginBottom: spacing.xs,
  },
  matchedRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: 4,
  },
  matchedText: {
    fontSize: 13,
    color: colors.text,
    flexShrink: 1,
  },
  goodLuck: {
    fontFamily: fonts.serifItalic,
    fontSize: 15,
    color: colors.primary,
    marginTop: spacing.sm,
  },
  sectionLabel: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: colors.textMuted,
    marginBottom: spacing.xs,
  },
  ruleSentence: {
    fontFamily: fonts.serif,
    fontSize: 15,
    lineHeight: 22,
    color: colors.text,
  },
  metaBox: {
    marginTop: spacing.md,
    gap: spacing.xs,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  metaText: {
    fontSize: 13,
    color: colors.textMuted,
  },
  countdownRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  countdownTile: {
    flex: 1,
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  countdownValue: {
    fontFamily: fonts.headingBold,
    fontSize: 30,
    color: colors.text,
    letterSpacing: 1,
  },
  countdownLabel: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: colors.textMuted,
    marginTop: 2,
  },
  anyMoment: {
    fontFamily: fonts.serifItalic,
    fontSize: 15,
    color: colors.primary,
    marginTop: spacing.xs,
  },
  entrantsRow: {
    marginTop: spacing.md,
    marginBottom: spacing.xs,
  },
});
