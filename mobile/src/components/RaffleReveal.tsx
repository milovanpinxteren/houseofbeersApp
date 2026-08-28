import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Animated,
  Easing,
  Linking,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import * as Clipboard from 'expo-clipboard';
import * as Haptics from 'expo-haptics';
import { Ionicons } from '@expo/vector-icons';
import { t } from '../i18n';
import { colors, spacing, borderRadius, fonts } from '../theme/colors';
import { Button } from './ui';

type Phase = 'idle' | 'countdown' | 'spinning' | 'revealing' | 'result';

const ROW_H = 56;
const VISIBLE_ROWS = 3;
const REEL_ROWS = 26;
const SPIN_MS = 3800;

const CONFETTI_COLORS = [
  colors.primary,
  colors.secondary,
  colors.tertiary,
  colors.warning,
  colors.text,
];

function haptic(kind: 'tick' | 'land' | 'win') {
  if (Platform.OS === 'web') return;
  try {
    if (kind === 'tick') Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    else if (kind === 'land') Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    else Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
  } catch {
    // Haptics are decoration; never let them break the reveal.
  }
}

function shuffled(arr: string[]): string[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/** Reel strip ending on the winner, one filler row below so the window stays full. */
function buildStrip(pool: string[], winner: string): string[] {
  const names = pool.length > 0 ? pool : [winner];
  const rows: string[] = [];
  while (rows.length < REEL_ROWS) {
    for (const n of shuffled(names)) {
      if (rows.length >= REEL_ROWS) break;
      if (names.length > 1 && rows[rows.length - 1] === n) continue;
      rows.push(n);
    }
  }
  rows.push(winner);
  rows.push(names[Math.floor(Math.random() * names.length)]);
  return rows;
}

interface Particle {
  x: number;
  drift: number;
  size: number;
  color: string;
  delay: number;
  spin: number;
  radius: number;
  fallScale: number;
}

/** Hand-rolled confetti: one shared progress value, per-particle interpolations. */
function ConfettiBurst({ burst, height }: { burst: number; height: number }) {
  const progress = useRef(new Animated.Value(0)).current;

  const particles = useMemo<Particle[]>(() => {
    if (!burst) return [];
    return Array.from({ length: 28 }, () => ({
      x: (Math.random() - 0.5) * 260,
      drift: (Math.random() - 0.5) * 150,
      size: 5 + Math.random() * 6,
      color: CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)],
      delay: Math.random() * 0.25,
      spin: (Math.random() < 0.5 ? -1 : 1) * (360 + Math.random() * 540),
      radius: Math.random() < 0.3 ? 99 : 2,
      fallScale: 0.75 + Math.random() * 0.45,
    }));
  }, [burst]);

  useEffect(() => {
    if (!burst) return;
    progress.setValue(0);
    Animated.timing(progress, {
      toValue: 1,
      duration: 2100,
      easing: Easing.out(Easing.quad),
      useNativeDriver: true,
    }).start();
  }, [burst, progress]);

  if (!burst) return null;
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      {particles.map((p, i) => (
        <Animated.View
          key={`${burst}-${i}`}
          style={{
            position: 'absolute',
            top: 0,
            left: '50%',
            width: p.size,
            height: p.size * 1.8,
            borderRadius: p.radius,
            backgroundColor: p.color,
            opacity: progress.interpolate({
              inputRange: [0, p.delay, Math.min(p.delay + 0.05, 0.6), 0.8, 1],
              outputRange: [0, 0, 1, 1, 0],
            }),
            transform: [
              {
                translateX: progress.interpolate({
                  inputRange: [0, p.delay, 1],
                  outputRange: [p.x, p.x, p.x + p.drift],
                }),
              },
              {
                translateY: progress.interpolate({
                  inputRange: [0, p.delay, 1],
                  outputRange: [-24, -24, height * p.fallScale],
                }),
              },
              {
                rotate: progress.interpolate({
                  inputRange: [0, 1],
                  outputRange: ['0deg', `${p.spin}deg`],
                }),
              },
            ],
          }}
        />
      ))}
    </View>
  );
}

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
  /**
   * Storefront link that applies the prize code AND puts the prize product in
   * the cart. Prize products are usually unlisted, so a bare code cannot be
   * redeemed by browsing the shop — this link is the real redeem path.
   */
  myCodeCartUrl?: string | null;
  /** Start the animation on mount. When false, jump straight to the result. */
  autoPlay?: boolean;
  /** Localized date formatter for the code expiry line. */
  formatDate?: (iso: string) => string;
  /** Fired every time the reveal finishes (also right after a replay). */
  onComplete?: () => void;
}

/**
 * The raffle draw reveal: 3-2-1 countdown, slot-machine reel of entrant
 * names decelerating onto the winner, confetti burst, then the personal
 * result. Replayable via the button under the result.
 */
export function RaffleReveal({
  entrantNames,
  winnerNames,
  prizeName,
  didWin,
  myCode,
  myCodeExpiresAt,
  myCodeCartUrl,
  autoPlay = true,
  formatDate,
  onComplete,
}: RaffleRevealProps) {
  const [phase, setPhase] = useState<Phase>(autoPlay ? 'idle' : 'result');
  const [countNum, setCountNum] = useState(3);
  const [strip, setStrip] = useState<string[]>([]);
  const [burst, setBurst] = useState(0);
  const [copied, setCopied] = useState(false);
  const [stageHeight, setStageHeight] = useState(380);

  const countScale = useRef(new Animated.Value(1.8)).current;
  const countOpacity = useRef(new Animated.Value(0)).current;
  const reelY = useRef(new Animated.Value(0)).current;
  const glowPulse = useRef(new Animated.Value(1)).current;
  const glowOpacity = useRef(new Animated.Value(0)).current;
  const winnerScale = useRef(new Animated.Value(autoPlay ? 0.5 : 1)).current;
  const resultOpacity = useRef(new Animated.Value(autoPlay ? 0 : 1)).current;

  const pulseLoop = useRef<Animated.CompositeAnimation | null>(null);
  const timeouts = useRef<ReturnType<typeof setTimeout>[]>([]);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      pulseLoop.current?.stop();
      timeouts.current.forEach(clearTimeout);
      timeouts.current = [];
    };
  }, []);

  const later = useCallback((fn: () => void, ms: number) => {
    timeouts.current.push(
      setTimeout(() => {
        if (mountedRef.current) fn();
      }, ms)
    );
  }, []);

  const finish = useCallback(() => {
    setPhase('result');
    Animated.timing(resultOpacity, {
      toValue: 1,
      duration: 400,
      useNativeDriver: true,
    }).start();
    onComplete?.();
  }, [resultOpacity, onComplete]);

  const reveal = useCallback(() => {
    setPhase('revealing');
    setBurst((b) => b + 1);
    haptic('win');
    winnerScale.setValue(0.6);
    Animated.spring(winnerScale, {
      toValue: 1,
      friction: 4,
      tension: 80,
      useNativeDriver: true,
    }).start();
    later(finish, 1500);
  }, [winnerScale, later, finish]);

  const startSpin = useCallback(() => {
    const pool = entrantNames.filter((n) => !winnerNames.includes(n));
    const names = pool.length > 0 ? pool : entrantNames;
    const rows = buildStrip(names, winnerNames[0]);
    setStrip(rows);
    setPhase('spinning');

    reelY.setValue(0);
    Animated.timing(glowOpacity, {
      toValue: 1,
      duration: 500,
      useNativeDriver: true,
    }).start();
    pulseLoop.current = Animated.loop(
      Animated.sequence([
        Animated.timing(glowPulse, {
          toValue: 1.14,
          duration: 700,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: true,
        }),
        Animated.timing(glowPulse, {
          toValue: 1,
          duration: 700,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: true,
        }),
      ])
    );
    pulseLoop.current.start();

    // Land the winner row (index REEL_ROWS) in the middle of the 3-row window.
    const target = -(REEL_ROWS - 1) * ROW_H;
    Animated.timing(reelY, {
      toValue: target,
      duration: SPIN_MS,
      easing: Easing.bezier(0.12, 0.68, 0.18, 1),
      useNativeDriver: true,
    }).start(({ finished }) => {
      if (!finished || !mountedRef.current) return;
      haptic('land');
      later(reveal, 400);
    });
  }, [entrantNames, winnerNames, reelY, glowOpacity, glowPulse, later, reveal]);

  const runCountdown = useCallback(
    (n: number) => {
      setCountNum(n);
      haptic('tick');
      countScale.setValue(1.8);
      countOpacity.setValue(0);
      Animated.parallel([
        Animated.timing(countScale, {
          toValue: 1,
          duration: 380,
          easing: Easing.out(Easing.back(1.4)),
          useNativeDriver: true,
        }),
        Animated.timing(countOpacity, {
          toValue: 1,
          duration: 160,
          useNativeDriver: true,
        }),
      ]).start();
      if (n > 1) later(() => runCountdown(n - 1), 700);
      else later(startSpin, 700);
    },
    [countScale, countOpacity, later, startSpin]
  );

  const play = useCallback(() => {
    timeouts.current.forEach(clearTimeout);
    timeouts.current = [];
    pulseLoop.current?.stop();
    winnerScale.setValue(0.5);
    resultOpacity.setValue(0);
    glowOpacity.setValue(0);
    setCopied(false);

    // A raffle can be drawn with zero winners (no entrants) — nothing to spin.
    if (winnerNames.length === 0) {
      resultOpacity.setValue(1);
      setPhase('result');
      onComplete?.();
      return;
    }
    setPhase('countdown');
    runCountdown(3);
  }, [winnerScale, resultOpacity, glowOpacity, winnerNames, runCountdown, onComplete]);

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

  function openCart(url: string) {
    Linking.openURL(url).catch((err) =>
      console.log('[Raffle] Open cart error:', err)
    );
  }

  const showWinners = phase === 'revealing' || phase === 'result';
  const publicNames = winnerNames.join(', ');

  return (
    <View
      style={styles.stage}
      onLayout={(e) => setStageHeight(e.nativeEvent.layout.height)}
    >
      <View style={styles.prizeRow}>
        <Ionicons name="gift" size={16} color={colors.primary} />
        <Text style={styles.prizeText}>
          {t('raffle.drawingFor', { prize: prizeName })}
        </Text>
      </View>

      <View style={styles.window}>
        {/* Soft glow behind the reel while it spins */}
        <Animated.View
          pointerEvents="none"
          style={[
            styles.glowWrap,
            { opacity: glowOpacity, transform: [{ scale: glowPulse }] },
          ]}
        >
          <View style={styles.glowOuter}>
            <View style={styles.glowInner} />
          </View>
        </Animated.View>

        {phase === 'countdown' ? (
          <Animated.Text
            style={[
              styles.countNumber,
              { opacity: countOpacity, transform: [{ scale: countScale }] },
            ]}
          >
            {countNum}
          </Animated.Text>
        ) : phase === 'spinning' ? (
          <>
            <View style={styles.reelClip}>
              <Animated.View style={{ transform: [{ translateY: reelY }] }}>
                {strip.map((name, index) => (
                  <View key={`${name}-${index}`} style={styles.reelRow}>
                    <Text style={styles.reelName} numberOfLines={1}>
                      {name}
                    </Text>
                  </View>
                ))}
              </Animated.View>
            </View>
            {/* Center highlight band */}
            <View pointerEvents="none" style={styles.highlightBand}>
              <Ionicons name="caret-forward" size={14} color={colors.primary} style={styles.bandCaretLeft} />
              <Ionicons name="caret-back" size={14} color={colors.primary} style={styles.bandCaretRight} />
            </View>
            {/* Edge fades (no gradient lib: stacked strips) */}
            <View pointerEvents="none" style={styles.fadeTop}>
              <View style={[styles.fadeStrip, { opacity: 0.9 }]} />
              <View style={[styles.fadeStrip, { opacity: 0.55 }]} />
              <View style={[styles.fadeStrip, { opacity: 0.22 }]} />
            </View>
            <View pointerEvents="none" style={styles.fadeBottom}>
              <View style={[styles.fadeStrip, { opacity: 0.22 }]} />
              <View style={[styles.fadeStrip, { opacity: 0.55 }]} />
              <View style={[styles.fadeStrip, { opacity: 0.9 }]} />
            </View>
          </>
        ) : showWinners && winnerNames.length > 0 ? (
          <Animated.View
            style={{ transform: [{ scale: winnerScale }], alignItems: 'center' }}
          >
            <Text style={styles.winnerLabel}>
              {winnerNames.length === 1 ? t('raffle.winner') : t('raffle.winners')}
            </Text>
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
                <Ionicons name="trophy" size={18} color={colors.warning} />
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
                  {myCodeCartUrl ? (
                    <>
                      <Button
                        label={t('raffle.redeemCta')}
                        icon="cart-outline"
                        size="sm"
                        onPress={() => openCart(myCodeCartUrl)}
                        style={styles.redeemButton}
                      />
                      <Text style={styles.redeemHint}>
                        {t('raffle.redeemHint')}
                      </Text>
                    </>
                  ) : null}
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
              <Ionicons
                name="beer-outline"
                size={22}
                color={colors.textMuted}
                style={styles.lostIcon}
              />
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

      <ConfettiBurst burst={burst} height={stageHeight} />
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
    overflow: 'hidden',
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
    fontSize: 13,
    letterSpacing: 1.4,
    textTransform: 'uppercase',
    textAlign: 'center',
    flexShrink: 1,
  },
  window: {
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: ROW_H * VISIBLE_ROWS,
    alignSelf: 'stretch',
  },
  glowWrap: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  glowOuter: {
    width: 210,
    height: 210,
    borderRadius: 105,
    backgroundColor: 'rgba(213, 200, 173, 0.06)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  glowInner: {
    width: 130,
    height: 130,
    borderRadius: 65,
    backgroundColor: 'rgba(213, 200, 173, 0.08)',
  },
  countNumber: {
    fontFamily: fonts.headingBold,
    fontSize: 64,
    color: colors.primary,
    textShadowColor: 'rgba(213, 200, 173, 0.4)',
    textShadowOffset: { width: 0, height: 0 },
    textShadowRadius: 18,
  },
  reelClip: {
    height: ROW_H * VISIBLE_ROWS,
    alignSelf: 'stretch',
    overflow: 'hidden',
  },
  reelRow: {
    height: ROW_H,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  reelName: {
    fontFamily: fonts.headingRegular,
    color: colors.textMuted,
    fontSize: 24,
    letterSpacing: 0.6,
    textAlign: 'center',
  },
  highlightBand: {
    position: 'absolute',
    top: ROW_H,
    height: ROW_H,
    left: 0,
    right: 0,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: 'rgba(213, 200, 173, 0.05)',
    justifyContent: 'center',
  },
  bandCaretLeft: {
    position: 'absolute',
    left: 2,
  },
  bandCaretRight: {
    position: 'absolute',
    right: 2,
  },
  fadeTop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
  },
  fadeBottom: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
  },
  fadeStrip: {
    height: 12,
    backgroundColor: colors.surfaceLow,
  },
  winnerLabel: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 2,
    textTransform: 'uppercase',
    color: colors.warning,
    marginBottom: spacing.xs,
  },
  winnerName: {
    fontFamily: fonts.headingBold,
    color: colors.text,
    fontSize: 34,
    letterSpacing: 0.6,
    textAlign: 'center',
    textShadowColor: 'rgba(213, 200, 173, 0.45)',
    textShadowOffset: { width: 0, height: 0 },
    textShadowRadius: 16,
  },
  result: {
    alignItems: 'center',
    alignSelf: 'stretch',
    marginTop: spacing.md,
  },
  wonBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.pill,
    borderWidth: 1,
    borderColor: colors.warning,
    backgroundColor: 'rgba(224, 164, 60, 0.12)',
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
  lostIcon: {
    marginBottom: spacing.xs,
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
  redeemButton: {
    marginTop: spacing.sm,
  },
  redeemHint: {
    fontSize: 11,
    color: colors.textMuted,
    marginTop: 6,
    textAlign: 'center',
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
