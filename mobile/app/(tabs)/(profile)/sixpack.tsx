import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Animated,
  Easing,
  Image,
  Linking,
  Platform,
  Pressable,
  StyleSheet,
  Switch,
  Text,
  View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Haptics from 'expo-haptics';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius, fonts, type } from '../../../src/theme/colors';
import { Button, Card, Screen, useToast } from '../../../src/components/ui';
import {
  checkoutSixpack,
  getRecommendationStatus,
  getSixpack,
  isPendingSixpack,
  SixpackPricing,
  SixpackReason,
  SixpackResponse,
  SixpackRole,
  SixpackSlot,
} from '../../../src/api/recommendations';
import {
  Adventurousness,
  BUDGET_PRESETS,
  DEFAULT_PREFS,
  FAMILY_LABEL_KEYS,
  PREFS_STORAGE_KEY,
  STYLE_FAMILIES,
  SixpackPrefs,
  excludedCategoriesFor,
} from '../../../src/constants/sixpack';

const MIN_SPIN_MS = 1600;
const STAGGER_MS = 220;
const POLL_INTERVAL_MS = 2500;
const MAX_POLLS = 16;

type ScreenPhase = 'wizard' | 'machine';
type ReelState = 'spinning' | 'stopped';

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function buzz(fn: () => Promise<unknown>) {
  if (Platform.OS !== 'web') {
    fn().catch(() => {});
  }
}

function reasonText(reason: SixpackReason | undefined): string {
  if (!reason) return '';
  const p = reason.params || {};
  switch (reason.code) {
    case 'preferred_style':
      return t('sixpack.reasonPreferredStyle', { style: String(p.style ?? '') });
    case 'adjacent_style':
      return t('sixpack.reasonAdjacentStyle', { from: String(p.from_style ?? '') });
    case 'new_style':
      return t('sixpack.reasonNewStyle', { style: String(p.style ?? '') });
    case 'known_brewery':
      return t('sixpack.reasonKnownBrewery', { brewery: String(p.brewery ?? '') });
    case 'highly_rated':
      return t('sixpack.reasonHighlyRated', { rating: String(p.rating ?? '') });
    case 'barrel_aged':
      return t('sixpack.reasonBarrelAged', { method: String(p.method ?? '') });
    case 'vintage':
      return t('sixpack.reasonVintage', { year: String(p.year ?? '') });
    case 'big_bottle':
      return t('sixpack.reasonBigBottle', { inhoud: String(p.inhoud ?? '') });
    default:
      return '';
  }
}

// ---------------------------------------------------------------------------
// Reel

interface ReelProps {
  slot: SixpackSlot | null;
  state: ReelState;
  locked: boolean;
  jackpot: boolean;
  onToggleLock: () => void;
  onRespin: () => void;
  busy: boolean;
}

function Reel({ slot, state, locked, jackpot, onToggleLock, onRespin, busy }: ReelProps) {
  const roll = useRef(new Animated.Value(0)).current;
  const appear = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (state === 'spinning') {
      appear.setValue(0);
      // Self-restarting loop: Animated.loop with the native driver only runs
      // a single cycle on react-native-web, freezing the reel mid-load.
      let active = true;
      const cycle = () => {
        if (!active) return;
        roll.setValue(0);
        Animated.timing(roll, {
          toValue: 1,
          duration: 380,
          easing: Easing.linear,
          useNativeDriver: true,
        }).start(({ finished }) => {
          if (finished) cycle();
        });
      };
      cycle();
      return () => {
        active = false;
        roll.stopAnimation();
        roll.setValue(0);
      };
    }
    // Reel stopped: pop the result in.
    Animated.parallel([
      Animated.spring(appear, { toValue: 1, friction: 6, useNativeDriver: true }),
    ]).start();
    return undefined;
  }, [state, roll, appear]);

  if (state === 'spinning' || !slot) {
    return (
      <View style={s.reel}>
        <View style={s.reelSpinBox}>
          <Animated.View
            style={{
              transform: [
                {
                  translateY: roll.interpolate({
                    inputRange: [0, 1],
                    outputRange: [0, -64],
                  }),
                },
              ],
            }}
          >
            {[0, 1, 2].map((i) => (
              <View key={i} style={s.reelSpinIcon}>
                <Ionicons name="beer" size={36} color={colors.primary + '66'} />
              </View>
            ))}
          </Animated.View>
        </View>
        <Text style={s.reelSpinText}>{t('sixpack.spinning')}</Text>
      </View>
    );
  }

  const beer = slot.beer;
  const why = reasonText(slot.reasons[0]);

  return (
    <Animated.View
      style={[
        s.reel,
        locked && s.reelLocked,
        jackpot && s.reelJackpot,
        {
          opacity: appear,
          transform: [
            {
              scale: appear.interpolate({ inputRange: [0, 1], outputRange: [0.85, 1] }),
            },
          ],
        },
      ]}
    >
      <Pressable onPress={onToggleLock} disabled={busy}>
        <View style={s.reelImageWrap}>
          {beer.image_url ? (
            <Image source={{ uri: beer.image_url }} style={s.reelImage} resizeMode="cover" />
          ) : (
            <View style={s.reelImagePlaceholder}>
              <Ionicons name="beer-outline" size={36} color={colors.textMuted} />
            </View>
          )}
          {locked && (
            <View style={s.lockBadge}>
              <Ionicons name="lock-closed" size={13} color={colors.background} />
            </View>
          )}
          {!locked && (
            <Pressable
              onPress={onRespin}
              disabled={busy}
              hitSlop={8}
              style={({ pressed }) => [s.respinButton, pressed && { opacity: 0.6 }]}
            >
              <Ionicons name="refresh" size={15} color={colors.text} />
            </Pressable>
          )}
        </View>
        <View style={s.reelBody}>
          <Text style={s.reelTitle} numberOfLines={2}>
            {beer.title}
          </Text>
          <View style={s.reelChipRow}>
            {!!beer.style_category && (
              <View style={s.reelChip}>
                <Text style={s.reelChipText}>{beer.style_category}</Text>
              </View>
            )}
            {beer.abv != null && (
              <View style={s.reelChip}>
                <Text style={s.reelChipText}>{beer.abv}%</Text>
              </View>
            )}
            {beer.untappd_rating != null && (
              <View style={s.reelChip}>
                <Ionicons name="star" size={9} color={colors.primary} />
                <Text style={s.reelChipText}>{beer.untappd_rating.toFixed(2)}</Text>
              </View>
            )}
          </View>
          {!!why && (
            <Text style={s.reelWhy} numberOfLines={2}>
              {why}
            </Text>
          )}
          <Text style={s.reelPrice}>
            {beer.price != null ? `€${Number(beer.price).toFixed(2)}` : ''}
            {beer.inhoud ? <Text style={s.reelInhoud}> · {beer.inhoud}</Text> : null}
          </Text>
        </View>
      </Pressable>
    </Animated.View>
  );
}

// ---------------------------------------------------------------------------
// Screen

export default function SixpackScreen() {
  const { language } = useLanguage();
  const { showToast } = useToast();

  const [phase, setPhase] = useState<ScreenPhase>('wizard');
  const [prefs, setPrefs] = useState<SixpackPrefs>(DEFAULT_PREFS);
  const [slots, setSlots] = useState<(SixpackSlot | null)[]>(Array(6).fill(null));
  const [reelStates, setReelStates] = useState<ReelState[]>(Array(6).fill('spinning'));
  const [lockedIds, setLockedIds] = useState<Set<string>>(new Set());
  const [pricing, setPricing] = useState<SixpackPricing | null>(null);
  const [busy, setBusy] = useState(false);
  const [buildingProfile, setBuildingProfile] = useState(false);
  const [checkingOut, setCheckingOut] = useState(false);

  const spinSeqRef = useRef(0);
  const seenIdsRef = useRef<Set<string>>(new Set());
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    AsyncStorage.getItem(PREFS_STORAGE_KEY)
      .then((raw) => {
        if (raw) setPrefs({ ...DEFAULT_PREFS, ...JSON.parse(raw) });
      })
      .catch(() => {});
    return () => {
      spinSeqRef.current += 1;
      timersRef.current.forEach(clearTimeout);
    };
  }, []);

  function toggleFamily(key: string) {
    setPrefs((p) => ({
      ...p,
      excludedFamilies: p.excludedFamilies.includes(key)
        ? p.excludedFamilies.filter((k) => k !== key)
        : [...p.excludedFamilies, key],
    }));
  }

  // Wait until a profile-build task settles. Both outcomes lead to a re-call
  // of the sixpack endpoint: after 'completed' the warm cache answers
  // synchronously, after 'failed' (e.g. Untappd build) the backend falls
  // back to the next profile source inline.
  async function pollUntilSettled(taskId: string, seq: number): Promise<boolean> {
    for (let i = 0; i < MAX_POLLS; i++) {
      await delay(POLL_INTERVAL_MS);
      if (seq !== spinSeqRef.current) return false;
      try {
        const status = await getRecommendationStatus(taskId);
        if (status.status === 'completed' || status.status === 'failed') {
          return true;
        }
      } catch (err) {
        // Status endpoint hiccup — keep polling until the cap.
        console.log('[Sixpack] Poll error:', err);
      }
    }
    throw new Error(t('sixpack.errorGeneric'));
  }

  const spin = useCallback(
    async (keep: { shopify_id: string; role: SixpackRole }[]) => {
      const seq = ++spinSeqRef.current;
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
      setBusy(true);
      setPricing(null);

      const keepIds = new Set(keep.map((k) => k.shopify_id));
      setReelStates((states) =>
        states.map((state, i) => {
          const id = slots[i]?.beer.shopify_id;
          return id && keepIds.has(id) ? 'stopped' : 'spinning';
        })
      );

      const payload = {
        budget: prefs.budget,
        exclude_style_categories: excludedCategoriesFor(prefs),
        include_alcohol_free: prefs.includeAlcoholFree,
        adventurousness: prefs.adventurousness,
        locked: keep,
        exclude: Array.from(seenIdsRef.current).filter((id) => !keepIds.has(id)),
      };

      try {
        let [result] = await Promise.all([getSixpack(payload), delay(MIN_SPIN_MS)]);
        if (seq !== spinSeqRef.current) return;

        // Up to two pending rounds: the Untappd build may settle first, then
        // the Shopify build for brand-new users.
        for (let round = 0; round < 2 && isPendingSixpack(result); round++) {
          setBuildingProfile(true);
          const settled = await pollUntilSettled(result.task_id, seq);
          if (!settled || seq !== spinSeqRef.current) return;
          result = await getSixpack(payload);
          if (seq !== spinSeqRef.current) return;
        }
        setBuildingProfile(false);
        if (isPendingSixpack(result)) {
          throw new Error(t('sixpack.errorGeneric'));
        }

        const pack = result as SixpackResponse;
        pack.slots.forEach((slot) => seenIdsRef.current.add(slot.beer.shopify_id));

        // Locked reels keep their index; fresh slots fill the open indices.
        const nextSlots: (SixpackSlot | null)[] = Array(6).fill(null);
        const freshSlots = pack.slots.filter((sl) => !keepIds.has(sl.beer.shopify_id));
        const openIndices: number[] = [];
        for (let i = 0; i < 6; i++) {
          const id = slots[i]?.beer.shopify_id;
          if (id && keepIds.has(id)) {
            nextSlots[i] = slots[i];
          } else {
            openIndices.push(i);
          }
        }
        openIndices.forEach((reelIndex, j) => {
          nextSlots[reelIndex] = freshSlots[j] ?? null;
        });
        setSlots(nextSlots);

        // Staggered reel stops, left to right.
        openIndices.forEach((reelIndex, j) => {
          const timer = setTimeout(() => {
            if (seq !== spinSeqRef.current) return;
            setReelStates((states) => {
              const next = [...states];
              next[reelIndex] = 'stopped';
              return next;
            });
            buzz(() => Haptics.selectionAsync());
            if (j === openIndices.length - 1) {
              setPricing(pack.pricing);
              setBusy(false);
              buzz(() =>
                Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)
              );
            }
          }, (j + 1) * STAGGER_MS);
          timersRef.current.push(timer);
        });

        if (openIndices.length === 0) {
          setPricing(pack.pricing);
          setBusy(false);
        }
      } catch (err: any) {
        console.log('[Sixpack] Spin error:', err);
        if (seq !== spinSeqRef.current) return;
        setBuildingProfile(false);
        setBusy(false);
        setReelStates(Array(6).fill('stopped'));
        showToast(err?.message || t('sixpack.errorGeneric'), 'error');
        if (!slots.some(Boolean)) {
          setPhase('wizard');
        }
      }
    },
    [prefs, slots, showToast]
  );

  async function startFromWizard() {
    try {
      await AsyncStorage.setItem(PREFS_STORAGE_KEY, JSON.stringify(prefs));
    } catch {}
    seenIdsRef.current = new Set();
    setLockedIds(new Set());
    setSlots(Array(6).fill(null));
    setPhase('machine');
    spin([]);
  }

  function keptPayloadFrom(ids: Set<string>) {
    return slots
      .filter((slot): slot is SixpackSlot => !!slot && ids.has(slot.beer.shopify_id))
      .map((slot) => ({ shopify_id: slot.beer.shopify_id, role: slot.role }));
  }

  function respinUnlocked() {
    spin(keptPayloadFrom(lockedIds));
  }

  function respinOne(reelIndex: number) {
    const others = new Set<string>();
    slots.forEach((slot, i) => {
      if (i !== reelIndex && slot) others.add(slot.beer.shopify_id);
    });
    spin(keptPayloadFrom(others));
  }

  function toggleLock(reelIndex: number) {
    const slot = slots[reelIndex];
    if (!slot || busy) return;
    buzz(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium));
    setLockedIds((ids) => {
      const next = new Set(ids);
      if (next.has(slot.beer.shopify_id)) {
        next.delete(slot.beer.shopify_id);
      } else {
        next.add(slot.beer.shopify_id);
      }
      return next;
    });
  }

  async function checkout() {
    const filled = slots.filter((slot): slot is SixpackSlot => !!slot);
    if (filled.length !== 6 || busy) return;
    setCheckingOut(true);
    try {
      const result = await checkoutSixpack(
        filled.map((slot) => ({
          shopify_id: slot.beer.shopify_id,
          variant_id: slot.beer.variant_id,
        }))
      );
      Linking.openURL(result.cart_url).catch((err) =>
        console.log('[Sixpack] Open cart error:', err)
      );
    } catch (err: any) {
      console.log('[Sixpack] Checkout error:', err);
      if (String(err?.message || '').includes('pack_unavailable')) {
        showToast(t('sixpack.packUnavailable'), 'error');
        setLockedIds(new Set());
        spin([]);
      } else {
        showToast(t('sixpack.checkoutError'), 'error');
      }
    } finally {
      setCheckingOut(false);
    }
  }

  // -------------------------------------------------------------------------

  if (phase === 'wizard') {
    return (
      <Screen>
        <Text style={s.intro}>{t('sixpack.wizardIntro')}</Text>

        <Card style={s.wizardCard}>
          <Text style={s.wizardLabel}>{t('sixpack.budgetLabel')}</Text>
          <View style={s.chipWrap}>
            {BUDGET_PRESETS.map((preset) => {
              const selected = prefs.budget === preset;
              return (
                <Pressable
                  key={preset}
                  onPress={() => setPrefs((p) => ({ ...p, budget: preset }))}
                  style={[s.chip, selected && s.chipSelected]}
                >
                  <Text style={[s.chipText, selected && s.chipTextSelected]}>
                    €{preset}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </Card>

        <Card style={s.wizardCard}>
          <Text style={s.wizardLabel}>{t('sixpack.stylesLabel')}</Text>
          <Text style={s.wizardHint}>{t('sixpack.stylesHint')}</Text>
          <View style={s.chipWrap}>
            {STYLE_FAMILIES.map((family) => {
              const selected = prefs.excludedFamilies.includes(family.key);
              return (
                <Pressable
                  key={family.key}
                  onPress={() => toggleFamily(family.key)}
                  style={[s.chip, s.familyChip, selected && s.chipExcluded]}
                >
                  <Ionicons
                    name={selected ? 'close-circle' : family.icon}
                    size={14}
                    color={selected ? colors.background : colors.textMuted}
                  />
                  <Text style={[s.chipText, selected && s.chipTextSelected]}>
                    {t(FAMILY_LABEL_KEYS[family.key])}
                  </Text>
                </Pressable>
              );
            })}
          </View>
          <View style={s.switchRow}>
            <Text style={s.switchLabel}>{t('sixpack.alcoholFreeLabel')}</Text>
            <Switch
              value={prefs.includeAlcoholFree}
              onValueChange={(value) =>
                setPrefs((p) => ({ ...p, includeAlcoholFree: value }))
              }
              trackColor={{ false: colors.surfaceHigh, true: colors.primary }}
              thumbColor={colors.text}
            />
          </View>
        </Card>

        <Card style={s.wizardCard}>
          <Text style={s.wizardLabel}>{t('sixpack.advLabel')}</Text>
          {(['safe', 'balanced', 'adventurous'] as Adventurousness[]).map((level) => {
            const selected = prefs.adventurousness === level;
            const labelKey =
              level === 'safe'
                ? 'advSafe'
                : level === 'balanced'
                  ? 'advBalanced'
                  : 'advAdventurous';
            return (
              <Pressable
                key={level}
                onPress={() => setPrefs((p) => ({ ...p, adventurousness: level }))}
                style={[s.advOption, selected && s.advOptionSelected]}
              >
                <Ionicons
                  name={selected ? 'radio-button-on' : 'radio-button-off'}
                  size={18}
                  color={selected ? colors.primary : colors.textMuted}
                />
                <View style={s.advTextWrap}>
                  <Text style={s.advTitle}>{t(`sixpack.${labelKey}`)}</Text>
                  <Text style={s.advDesc}>{t(`sixpack.${labelKey}Desc`)}</Text>
                </View>
              </Pressable>
            );
          })}
        </Card>

        <Button
          label={t('sixpack.start')}
          icon="sparkles"
          onPress={startFromWizard}
          style={s.startButton}
        />
      </Screen>
    );
  }

  const allStopped = reelStates.every((state) => state === 'stopped');
  const filledCount = slots.filter(Boolean).length;

  return (
    <Screen>
      <View style={s.reelGrid}>
        {slots.map((slot, i) => (
          <Reel
            key={i}
            slot={slot}
            state={reelStates[i]}
            locked={!!slot && lockedIds.has(slot.beer.shopify_id)}
            jackpot={
              !!slot && slot.beer.untappd_rating != null && slot.beer.untappd_rating >= 4.3
            }
            onToggleLock={() => toggleLock(i)}
            onRespin={() => respinOne(i)}
            busy={busy}
          />
        ))}
      </View>

      {buildingProfile && (
        <Text style={s.buildingText}>{t('sixpack.buildingProfile')}</Text>
      )}

      {pricing && allStopped && (
        <Card variant="accent" style={s.priceCard}>
          <Text style={s.priceLine}>
            {t('sixpack.priceLine', {
              value: Number(pricing.value).toFixed(2),
              price: Number(pricing.price).toFixed(2),
            })}
          </Text>
          {Number(pricing.discount) > 0 && (
            <Text style={s.priceSub}>
              {t('sixpack.discountLine', {
                discount: Number(pricing.discount).toFixed(2),
              })}
            </Text>
          )}
        </Card>
      )}

      {allStopped && !busy && (
        <Text style={s.lockHint}>{t('sixpack.lockHint')}</Text>
      )}

      <Button
        label={t('sixpack.checkout')}
        icon="cart-outline"
        onPress={checkout}
        disabled={busy || checkingOut || filledCount !== 6}
        loading={checkingOut}
        style={s.actionButton}
      />
      <Button
        label={t('sixpack.spinAgain')}
        icon="dice-outline"
        variant="secondary"
        onPress={respinUnlocked}
        disabled={busy || checkingOut}
        style={s.actionButton}
      />
      <Button
        label={t('sixpack.editPrefs')}
        icon="options-outline"
        variant="ghost"
        onPress={() => setPhase('wizard')}
        disabled={busy || checkingOut}
      />
    </Screen>
  );
}

const s = StyleSheet.create({
  intro: {
    ...type.serifLarge,
    fontFamily: fonts.serifItalic,
    color: colors.textMuted,
    marginTop: spacing.md,
    marginBottom: spacing.md,
  },
  wizardCard: {
    marginBottom: spacing.sm,
  },
  wizardLabel: {
    ...type.label,
    marginBottom: spacing.sm,
  },
  wizardHint: {
    fontFamily: fonts.serif,
    fontSize: 14,
    color: colors.textMuted,
    marginBottom: spacing.sm,
  },
  chipWrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  chip: {
    backgroundColor: colors.surfaceHigh,
    borderRadius: borderRadius.pill,
    paddingVertical: 7,
    paddingHorizontal: spacing.md,
  },
  familyChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  chipSelected: {
    backgroundColor: colors.primary,
  },
  chipExcluded: {
    backgroundColor: colors.secondary,
  },
  chipText: {
    fontFamily: fonts.heading,
    fontSize: 13,
    letterSpacing: 0.5,
    color: colors.textMuted,
  },
  chipTextSelected: {
    color: colors.background,
  },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: spacing.md,
  },
  switchLabel: {
    fontFamily: fonts.serif,
    fontSize: 15,
    color: colors.text,
    flex: 1,
    marginRight: spacing.sm,
  },
  advOption: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.md,
  },
  advOptionSelected: {
    backgroundColor: colors.primary + '14',
  },
  advTextWrap: {
    flex: 1,
  },
  advTitle: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.4,
    color: colors.text,
  },
  advDesc: {
    fontFamily: fonts.serif,
    fontSize: 14,
    lineHeight: 19,
    color: colors.textMuted,
    marginTop: 1,
  },
  startButton: {
    marginTop: spacing.sm,
    marginBottom: spacing.lg,
  },
  reelGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
    marginTop: spacing.md,
  },
  reel: {
    width: '48.5%',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    overflow: 'hidden',
    marginBottom: spacing.sm,
  },
  reelLocked: {
    borderWidth: 1.5,
    borderColor: colors.primary,
  },
  reelJackpot: {
    shadowColor: colors.primary,
    shadowOpacity: 0.35,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 0 },
    elevation: 4,
  },
  reelSpinBox: {
    height: 128,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'flex-start',
    backgroundColor: colors.surfaceLow,
  },
  reelSpinIcon: {
    height: 64,
    alignItems: 'center',
    justifyContent: 'center',
  },
  reelSpinText: {
    fontFamily: fonts.serifItalic,
    fontSize: 13,
    color: colors.textMuted,
    textAlign: 'center',
    paddingVertical: spacing.md,
  },
  reelImageWrap: {
    width: '100%',
    aspectRatio: 1.2,
    backgroundColor: colors.surfaceLow,
  },
  reelImage: {
    width: '100%',
    height: '100%',
  },
  reelImagePlaceholder: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  lockBadge: {
    position: 'absolute',
    top: 8,
    left: 8,
    backgroundColor: colors.primary,
    borderRadius: borderRadius.pill,
    width: 24,
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  respinButton: {
    position: 'absolute',
    top: 8,
    right: 8,
    backgroundColor: colors.background + 'B3',
    borderRadius: borderRadius.pill,
    width: 26,
    height: 26,
    alignItems: 'center',
    justifyContent: 'center',
  },
  reelBody: {
    padding: spacing.sm,
  },
  reelTitle: {
    fontFamily: fonts.heading,
    fontSize: 13,
    lineHeight: 17,
    letterSpacing: 0.3,
    color: colors.text,
    minHeight: 34,
  },
  reelChipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
    marginTop: 6,
  },
  reelChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: colors.surfaceHigh,
    borderRadius: borderRadius.pill,
    paddingVertical: 2,
    paddingHorizontal: 7,
  },
  reelChipText: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 0.4,
    color: colors.primary,
  },
  reelWhy: {
    fontFamily: fonts.serifItalic,
    fontSize: 12,
    lineHeight: 16,
    color: colors.textMuted,
    marginTop: 6,
    minHeight: 32,
  },
  reelPrice: {
    fontFamily: fonts.heading,
    fontSize: 15,
    color: colors.primary,
    marginTop: 6,
  },
  reelInhoud: {
    fontFamily: fonts.heading,
    fontSize: 11,
    color: colors.textMuted,
  },
  buildingText: {
    fontFamily: fonts.serifItalic,
    fontSize: 14,
    color: colors.textMuted,
    textAlign: 'center',
    marginBottom: spacing.sm,
  },
  priceCard: {
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  priceLine: {
    fontFamily: fonts.headingBold,
    fontSize: 17,
    letterSpacing: 0.4,
    color: colors.text,
    textAlign: 'center',
  },
  priceSub: {
    fontFamily: fonts.serif,
    fontSize: 14,
    color: colors.primary,
    marginTop: 2,
  },
  lockHint: {
    fontFamily: fonts.serif,
    fontSize: 13,
    color: colors.textMuted,
    textAlign: 'center',
    marginBottom: spacing.sm,
  },
  actionButton: {
    marginBottom: spacing.sm,
  },
});
