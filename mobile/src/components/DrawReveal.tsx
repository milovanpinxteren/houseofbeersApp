import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Animated,
  Easing,
  Platform,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import * as Haptics from 'expo-haptics';
import { Ionicons } from '@expo/vector-icons';
import { t } from '../i18n';
import { colors, spacing, borderRadius, fonts } from '../theme/colors';

/**
 * Livestream draw reveal: the slot-machine choreography from the loyalty
 * RaffleReveal, adapted for live multi-winner draws — every winner gets a
 * spin of their own (first long, re-spins short) and locks into a growing
 * winners list with a confetti pop, so a 4-winner prize is four little
 * climaxes instead of one name-cycle and a dumped list.
 *
 * Leaner than RaffleReveal on purpose: no codes, no prize tiers, no replay
 * (the mechanics are copied, not shared — the loyalty flow stays untouched).
 * Runs once on mount; the host owns the overlay, queueing and dismissal.
 */

type Phase = 'intro' | 'countdown' | 'spinning' | 'finale';

const ROW_H = 56;
const VISIBLE_ROWS = 3;
const FIRST_REEL_ROWS = 18;
const NEXT_REEL_ROWS = 9;
const FIRST_SPIN_MS = 2400;
const NEXT_SPIN_MS = 1300;
const INTRO_MS = 1000;
const COUNT_BEAT_MS = 500;
const LAND_PAUSE_MS = 300;
const NEXT_SPIN_GAP_MS = 900;
const FINALE_DELAY_MS = 600;
const AUTO_DISMISS_MS = 5000;

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
function buildStrip(pool: string[], winner: string, reelRows: number): string[] {
  const names = pool.length > 0 ? pool : [winner];
  const rows: string[] = [];
  while (rows.length < reelRows) {
    for (const n of shuffled(names)) {
      if (rows.length >= reelRows) break;
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

type Burst = { id: number; count: number };

/** Hand-rolled confetti: one shared progress value, per-particle interpolations. */
function ConfettiBurst({ burst, height }: { burst: Burst | null; height: number }) {
  const progress = useRef(new Animated.Value(0)).current;

  const particles = useMemo<Particle[]>(() => {
    if (!burst) return [];
    return Array.from({ length: burst.count }, () => ({
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
          key={`${burst.id}-${i}`}
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

/** One locked winner row: springs in when it lands. */
function LockedName({ name, solo }: { name: string; solo: boolean }) {
  const scale = useRef(new Animated.Value(0.5)).current;
  useEffect(() => {
    Animated.spring(scale, {
      toValue: 1,
      friction: 4,
      tension: 80,
      useNativeDriver: true,
    }).start();
    // Springs exactly once, on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <Animated.Text
      style={[
        styles.lockedName,
        solo && styles.lockedNameSolo,
        { transform: [{ scale }] },
      ]}
      numberOfLines={1}
    >
      {name}
    </Animated.Text>
  );
}

interface DrawRevealProps {
  prizeName: string;
  /** Winner names in draw order — one reel landing per name. */
  winnerNames: string[];
  /** Shuffle pool (live viewer names, pre-padded by the host). */
  viewerNames: string[];
  didWin: boolean;
  /** Finale reached — the host may now allow tap-to-dismiss. */
  onFinale?: () => void;
  /** Auto-dismiss moment (~5s after the finale). */
  onDone?: () => void;
}

export default function DrawReveal({
  prizeName,
  winnerNames,
  viewerNames,
  didWin,
  onFinale,
  onDone,
}: DrawRevealProps) {
  const [phase, setPhase] = useState<Phase>('intro');
  const [countNum, setCountNum] = useState(3);
  const [strip, setStrip] = useState<string[]>([]);
  const [lockedCount, setLockedCount] = useState(0);
  const [burst, setBurst] = useState<Burst | null>(null);
  const [stageHeight, setStageHeight] = useState(380);

  const introScale = useRef(new Animated.Value(0.7)).current;
  const introOpacity = useRef(new Animated.Value(0)).current;
  const countScale = useRef(new Animated.Value(1.8)).current;
  const countOpacity = useRef(new Animated.Value(0)).current;
  const reelY = useRef(new Animated.Value(0)).current;
  const glowPulse = useRef(new Animated.Value(1)).current;
  const glowOpacity = useRef(new Animated.Value(0)).current;
  const trophyScale = useRef(new Animated.Value(0.4)).current;
  const youWonOpacity = useRef(new Animated.Value(0)).current;

  const pulseLoop = useRef<Animated.CompositeAnimation | null>(null);
  const timeouts = useRef<ReturnType<typeof setTimeout>[]>([]);
  const mountedRef = useRef(true);

  // Winners never fly by mid-spin: every winner is out of the pool from the
  // start, so a name only appears in the reel window when it actually lands.
  const pool = useMemo(() => {
    const p = viewerNames.filter((n) => !winnerNames.includes(n));
    return p.length > 0 ? p : viewerNames;
  }, [viewerNames, winnerNames]);

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

  const finale = useCallback(() => {
    setPhase('finale');
    pulseLoop.current?.stop();
    Animated.timing(glowOpacity, {
      toValue: 0,
      duration: 400,
      useNativeDriver: true,
    }).start();
    Animated.spring(trophyScale, {
      toValue: 1,
      friction: 4,
      tension: 80,
      useNativeDriver: true,
    }).start();
    if (didWin) {
      setBurst({ id: 1000, count: 44 });
      haptic('win');
      Animated.sequence([
        Animated.delay(350),
        Animated.timing(youWonOpacity, {
          toValue: 1,
          duration: 400,
          useNativeDriver: true,
        }),
      ]).start();
    }
    onFinale?.();
    later(() => onDone?.(), AUTO_DISMISS_MS);
  }, [didWin, glowOpacity, trophyScale, youWonOpacity, onFinale, onDone, later]);

  const lockWinner = useCallback(
    (index: number) => {
      setLockedCount(index + 1);
      setBurst({ id: index + 1, count: index === 0 ? 26 : 14 });
      haptic('win');
      if (index + 1 < winnerNames.length) {
        later(() => spinFor(index + 1), NEXT_SPIN_GAP_MS);
      } else {
        later(finale, FINALE_DELAY_MS);
      }
    },
    // spinFor is hoisted via function declaration below
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [winnerNames.length, later, finale]
  );

  function spinFor(index: number) {
    const reelRows = index === 0 ? FIRST_REEL_ROWS : NEXT_REEL_ROWS;
    const spinMs = index === 0 ? FIRST_SPIN_MS : NEXT_SPIN_MS;
    setStrip(buildStrip(pool, winnerNames[index], reelRows));
    setPhase('spinning');

    reelY.setValue(0);
    if (index === 0) {
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
    }

    // Land the winner row (index reelRows) in the middle of the 3-row window.
    const target = -(reelRows - 1) * ROW_H;
    Animated.timing(reelY, {
      toValue: target,
      duration: spinMs,
      easing: Easing.bezier(0.12, 0.68, 0.18, 1),
      useNativeDriver: true,
    }).start(({ finished }) => {
      if (!finished || !mountedRef.current) return;
      haptic('land');
      later(() => lockWinner(index), LAND_PAUSE_MS);
    });
  }

  const runCountdown = useCallback(
    (n: number) => {
      setPhase('countdown');
      setCountNum(n);
      haptic('tick');
      countScale.setValue(1.8);
      countOpacity.setValue(0);
      Animated.parallel([
        Animated.timing(countScale, {
          toValue: 1,
          duration: 320,
          easing: Easing.out(Easing.back(1.4)),
          useNativeDriver: true,
        }),
        Animated.timing(countOpacity, {
          toValue: 1,
          duration: 140,
          useNativeDriver: true,
        }),
      ]).start();
      if (n > 1) later(() => runCountdown(n - 1), COUNT_BEAT_MS);
      else later(() => spinFor(0), COUNT_BEAT_MS);
    },
    // spinFor is a stable function declaration in this scope
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [countScale, countOpacity, later]
  );

  // Run exactly once on mount — the host remounts (new key) per draw.
  useEffect(() => {
    Animated.parallel([
      Animated.spring(introScale, {
        toValue: 1,
        friction: 5,
        tension: 70,
        useNativeDriver: true,
      }),
      Animated.timing(introOpacity, {
        toValue: 1,
        duration: 250,
        useNativeDriver: true,
      }),
    ]).start();
    if (winnerNames.length === 0) {
      // Drawn with no winners (empty room) — nothing to spin.
      later(finale, INTRO_MS);
    } else {
      later(() => runCountdown(3), INTRO_MS);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const showReel = phase === 'spinning';
  const solo = winnerNames.length === 1;

  return (
    <View
      style={styles.stage}
      onLayout={(e) => setStageHeight(e.nativeEvent.layout.height)}
    >
      {/* Prize intro — stays as the header for the whole run */}
      <Animated.View
        style={[
          styles.prizeBlock,
          { opacity: introOpacity, transform: [{ scale: introScale }] },
        ]}
      >
        <View style={styles.prizeRow}>
          <Ionicons name="gift" size={18} color={colors.primary} />
          <Text style={styles.prizeLabel}>{t('events.drawingFor')}</Text>
        </View>
        <Text style={styles.prizeName}>{prizeName}</Text>
        {winnerNames.length > 1 && (
          <Text style={styles.prizeCount}>
            {t('events.winnersCount', { count: winnerNames.length })}
          </Text>
        )}
      </Animated.View>

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
        ) : showReel ? (
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
              <Ionicons
                name="caret-forward"
                size={14}
                color={colors.primary}
                style={styles.bandCaretLeft}
              />
              <Ionicons
                name="caret-back"
                size={14}
                color={colors.primary}
                style={styles.bandCaretRight}
              />
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
        ) : phase === 'finale' ? (
          <Animated.View style={{ transform: [{ scale: trophyScale }] }}>
            <Ionicons name="trophy" size={56} color={colors.warning} />
          </Animated.View>
        ) : null}
      </View>

      {/* Locked winners, growing one spin at a time */}
      {lockedCount > 0 && (
        <View style={styles.lockedList}>
          <Text style={styles.lockedLabel}>
            {solo ? t('raffle.winner') : t('raffle.winners')}
          </Text>
          {winnerNames.slice(0, lockedCount).map((name, index) => (
            <LockedName key={`${name}-${index}`} name={name} solo={solo} />
          ))}
        </View>
      )}

      {phase === 'finale' && (
        <>
          {didWin && (
            <Animated.View
              style={[styles.youWonPill, { opacity: youWonOpacity }]}
            >
              <Ionicons name="trophy" size={20} color={colors.warning} />
              <Text style={styles.youWonText}>{t('events.youWon')}</Text>
            </Animated.View>
          )}
          <Text style={styles.dismissHint}>{t('events.tapToDismiss')}</Text>
        </>
      )}

      <ConfettiBurst burst={burst} height={stageHeight} />
    </View>
  );
}

const styles = StyleSheet.create({
  stage: {
    width: '100%',
    maxWidth: 440,
    alignItems: 'center',
    overflow: 'hidden',
    paddingVertical: spacing.lg,
  },
  prizeBlock: {
    alignItems: 'center',
    marginBottom: spacing.lg,
  },
  prizeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  prizeLabel: {
    fontFamily: fonts.heading,
    color: colors.textMuted,
    fontSize: 12,
    letterSpacing: 1.8,
    textTransform: 'uppercase',
  },
  prizeName: {
    fontFamily: fonts.headingBold,
    color: colors.primary,
    fontSize: 22,
    letterSpacing: 0.6,
    textAlign: 'center',
  },
  prizeCount: {
    fontFamily: fonts.heading,
    color: colors.textMuted,
    fontSize: 13,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    marginTop: 2,
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
  // The overlay behind the stage is near-black; fades must match it, not
  // the card surface RaffleReveal sits on.
  fadeStrip: {
    height: 12,
    backgroundColor: 'rgba(0, 0, 0, 0.92)',
  },
  lockedList: {
    alignItems: 'center',
    alignSelf: 'stretch',
    marginTop: spacing.md,
  },
  lockedLabel: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 2,
    textTransform: 'uppercase',
    color: colors.warning,
    marginBottom: spacing.xs,
  },
  lockedName: {
    fontFamily: fonts.headingBold,
    color: colors.text,
    fontSize: 26,
    letterSpacing: 0.6,
    textAlign: 'center',
    marginBottom: 2,
    textShadowColor: 'rgba(213, 200, 173, 0.45)',
    textShadowOffset: { width: 0, height: 0 },
    textShadowRadius: 16,
  },
  lockedNameSolo: {
    fontSize: 34,
  },
  youWonPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.lg,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: borderRadius.pill,
    borderWidth: 2,
    borderColor: colors.warning,
    backgroundColor: 'rgba(224, 164, 60, 0.12)',
  },
  youWonText: {
    fontFamily: fonts.headingBold,
    color: colors.warning,
    fontSize: 24,
    textAlign: 'center',
    letterSpacing: 3,
    textTransform: 'uppercase',
  },
  dismissHint: {
    color: colors.textMuted,
    fontSize: 12,
    marginTop: spacing.xl,
  },
});
