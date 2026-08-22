import { useCallback, useEffect, useRef, useState } from 'react';
import { Animated, Pressable, StyleSheet, Text, View } from 'react-native';
import * as Clipboard from 'expo-clipboard';
import { Ionicons } from '@expo/vector-icons';
import { t } from '../i18n';
import { colors, spacing, borderRadius, fonts } from '../theme/colors';
import { Button } from './ui';

type Phase = 'idle' | 'shuffling' | 'revealing' | 'result';

interface RaffleRevealProps {
  /** Shuffled entrant first names from the API (post-draw). */
  entrantNames: string[];
  /** Winner first names in draw order. */
  winnerNames: string[];
  prizeName: string;
  didWin: boolean;
  /** Discount code for a winning caller (null for manual fulfillment). */
  myCode: string | null;
  myCodeExpiresAt?: string | null;
  /** Start the animation on mount. When false, jump straight to the result. */
  autoPlay?: boolean;
  /** Localized date formatter for the code expiry line. */
  formatDate?: (iso: string) => string;
  /** Fired every time the reveal finishes (also right after a replay). */
  onComplete?: () => void;
}

/**
 * The raffle draw reveal, ported from the livestream raffle overlay
 * (app/(tabs)/(community)/livestream.tsx): cycle entrant names with
 * decelerating timing, spring-reveal the winner name(s), then fade in the
 * personal result. Replayable via the button under the result.
 */
export function RaffleReveal({
  entrantNames,
  winnerNames,
  prizeName,
  didWin,
  myCode,
  myCodeExpiresAt,
  autoPlay = true,
  formatDate,
  onComplete,
}: RaffleRevealProps) {
  const [phase, setPhase] = useState<Phase>(autoPlay ? 'idle' : 'result');
  const [shuffleName, setShuffleName] = useState('');
  const [copied, setCopied] = useState(false);

  const winnerScale = useRef(new Animated.Value(autoPlay ? 0.5 : 1)).current;
  const resultOpacity = useRef(new Animated.Value(autoPlay ? 0 : 1)).current;
  const timeouts = useRef<ReturnType<typeof setTimeout>[]>([]);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      timeouts.current.forEach(clearTimeout);
      timeouts.current = [];
    };
  }, []);

  const play = useCallback(() => {
    timeouts.current.forEach(clearTimeout);
    timeouts.current = [];
    winnerScale.setValue(0.5);
    resultOpacity.setValue(0);
    setCopied(false);
    setPhase('shuffling');

    // Cycle names, avoiding the winners until the actual reveal.
    const pool = entrantNames.filter((n) => !winnerNames.includes(n));
    const names =
      pool.length > 0 ? pool : entrantNames.length > 0 ? entrantNames : winnerNames;

    let elapsed = 0;

    // Same deceleration curve as the livestream raffle: fast start, slow finish.
    function getDelay() {
      if (elapsed < 1000) return 50;
      if (elapsed < 1800) return 100;
      if (elapsed < 2300) return 200;
      return 400;
    }

    function tick() {
      if (!mountedRef.current) return;
      if (elapsed >= 2800 || names.length === 0) {
        // Reveal the winner(s)
        setPhase('revealing');
        Animated.spring(winnerScale, {
          toValue: 1,
          friction: 4,
          tension: 80,
          useNativeDriver: true,
        }).start();

        timeouts.current.push(
          setTimeout(() => {
            if (!mountedRef.current) return;
            setPhase('result');
            Animated.timing(resultOpacity, {
              toValue: 1,
              duration: 400,
              useNativeDriver: true,
            }).start();
            onComplete?.();
          }, 1400)
        );
        return;
      }

      setShuffleName(names[Math.floor(Math.random() * names.length)]);
      const delay = getDelay();
      elapsed += delay;
      timeouts.current.push(setTimeout(tick, delay));
    }

    tick();
  }, [entrantNames, winnerNames, winnerScale, resultOpacity, onComplete]);

  useEffect(() => {
    if (autoPlay) {
      play();
    }
    // Play exactly once on mount when autoPlay is set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function copyCode(code: string) {
    await Clipboard.setStringAsync(code);
    setCopied(true);
    timeouts.current.push(setTimeout(() => mountedRef.current && setCopied(false), 2000));
  }

  const showWinners = phase === 'revealing' || phase === 'result';
  const publicNames = winnerNames.join(', ');

  return (
    <View style={styles.stage}>
      <View style={styles.prizeRow}>
        <Ionicons name="gift" size={18} color={colors.primary} />
        <Text style={styles.prizeText}>
          {t('raffle.drawingFor', { prize: prizeName })}
        </Text>
      </View>

      <View style={styles.nameContainer}>
        {phase === 'shuffling' ? (
          <Text style={styles.shuffleName}>{shuffleName}</Text>
        ) : showWinners ? (
          <Animated.View style={{ transform: [{ scale: winnerScale }], alignItems: 'center' }}>
            {winnerNames.map((name, index) => (
              <Text key={`${name}-${index}`} style={styles.winnerName}>
                {name}
              </Text>
            ))}
          </Animated.View>
        ) : null}
      </View>

      {phase === 'result' && (
        <Animated.View style={[styles.result, { opacity: resultOpacity }]}>
          {didWin ? (
            <>
              <View style={styles.wonBanner}>
                <Text style={styles.wonBannerText}>{t('raffle.youWon')}</Text>
              </View>
              <Text style={styles.resultBody}>
                {t('raffle.youWonBody', { prize: prizeName })}
              </Text>
              {myCode ? (
                <>
                  <Text style={styles.codeLabel}>{t('raffle.yourCode')}</Text>
                  <Pressable
                    style={({ pressed }) => [styles.codeBox, pressed && { opacity: 0.8 }]}
                    onPress={() => copyCode(myCode)}
                  >
                    <View style={styles.codeLeft}>
                      <Text style={styles.codeText}>{myCode}</Text>
                      <Text style={styles.copyHint}>
                        {copied ? t('raffle.copiedToClipboard') : t('raffle.tapToCopy')}
                      </Text>
                    </View>
                    <Ionicons
                      name={copied ? 'checkmark-circle' : 'copy-outline'}
                      size={20}
                      color={copied ? colors.success : colors.primary}
                    />
                  </Pressable>
                  {myCodeExpiresAt ? (
                    <Text style={styles.expiresText}>
                      {t('raffle.codeExpires', {
                        date: formatDate
                          ? formatDate(myCodeExpiresAt)
                          : new Date(myCodeExpiresAt).toLocaleDateString(),
                      })}
                    </Text>
                  ) : null}
                </>
              ) : (
                <Text style={styles.manualNote}>{t('raffle.manualPrizeNote')}</Text>
              )}
            </>
          ) : (
            <>
              <Text style={styles.lostTitle}>{t('raffle.lostTitle')}</Text>
              <Text style={styles.resultBody}>
                {t('raffle.lostBody', { names: publicNames })}
              </Text>
            </>
          )}

          <Button
            label={t('raffle.replay')}
            icon="refresh"
            variant="secondary"
            size="sm"
            onPress={play}
            style={styles.replayButton}
          />
        </Animated.View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  stage: {
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.xl,
    paddingVertical: spacing.xl,
    paddingHorizontal: spacing.lg,
    alignItems: 'center',
  },
  prizeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  prizeText: {
    fontFamily: fonts.heading,
    color: colors.primary,
    fontSize: 16,
    letterSpacing: 0.5,
    textAlign: 'center',
    flexShrink: 1,
  },
  nameContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 90,
    alignSelf: 'stretch',
  },
  shuffleName: {
    fontFamily: fonts.headingRegular,
    color: colors.textMuted,
    fontSize: 28,
    letterSpacing: 0.6,
    textAlign: 'center',
  },
  winnerName: {
    fontFamily: fonts.headingBold,
    color: colors.text,
    fontSize: 34,
    letterSpacing: 0.6,
    textAlign: 'center',
  },
  result: {
    alignItems: 'center',
    alignSelf: 'stretch',
    marginTop: spacing.md,
  },
  wonBanner: {
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.pill,
    borderWidth: 2,
    borderColor: colors.warning,
    marginBottom: spacing.md,
  },
  wonBannerText: {
    fontFamily: fonts.headingBold,
    color: colors.warning,
    fontSize: 20,
    textAlign: 'center',
    letterSpacing: 3,
    textTransform: 'uppercase',
  },
  lostTitle: {
    fontFamily: fonts.heading,
    color: colors.text,
    fontSize: 18,
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
    textAlign: 'center',
  },
  resultBody: {
    fontFamily: fonts.serif,
    fontSize: 15,
    lineHeight: 22,
    color: colors.textMuted,
    textAlign: 'center',
  },
  codeLabel: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 1.4,
    textTransform: 'uppercase',
    color: colors.textMuted,
    marginTop: spacing.md,
    marginBottom: spacing.xs,
  },
  codeBox: {
    alignSelf: 'stretch',
    backgroundColor: colors.primary + '15',
    padding: spacing.md,
    borderRadius: borderRadius.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  codeLeft: {
    flex: 1,
  },
  codeText: {
    fontSize: 17,
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
  manualNote: {
    fontFamily: fonts.serif,
    fontSize: 15,
    lineHeight: 22,
    color: colors.text,
    textAlign: 'center',
    marginTop: spacing.md,
  },
  replayButton: {
    marginTop: spacing.lg,
  },
});
