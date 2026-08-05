import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Animated,
  Easing,
  Image,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius, fonts, type } from '../../../src/theme/colors';
import { Button, Card, Screen, useToast } from '../../../src/components/ui';
import { getRandomBeer, RandomBeer } from '../../../src/api/recommendations';

// Keep the pulse on screen long enough to feel like a real "spin"
const MIN_SPIN_MS = 1400;

const PRICE_PRESETS = [5, 10, 15, 25, 50, null] as const;

type Phase = 'idle' | 'spinning' | 'result';

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export default function RandomBeerScreen() {
  const { language } = useLanguage();
  const { showToast } = useToast();

  const [phase, setPhase] = useState<Phase>('idle');
  const [beer, setBeer] = useState<RandomBeer | null>(null);
  const [noMatch, setNoMatch] = useState(false);
  const [failLine, setFailLine] = useState('');

  // Filters (apply to the next spin)
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [maxPrice, setMaxPrice] = useState<number | null>(null);

  // Ignore responses from superseded spins
  const spinSeqRef = useRef(0);

  // Pulsing beer glass while "spinning"
  const pulse = useRef(new Animated.Value(1)).current;
  const wobble = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (phase !== 'spinning') return;
    const pulseLoop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, {
          toValue: 1.25,
          duration: 350,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true,
        }),
        Animated.timing(pulse, {
          toValue: 1,
          duration: 350,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true,
        }),
      ])
    );
    const wobbleLoop = Animated.loop(
      Animated.sequence([
        Animated.timing(wobble, { toValue: 1, duration: 175, useNativeDriver: true }),
        Animated.timing(wobble, { toValue: -1, duration: 350, useNativeDriver: true }),
        Animated.timing(wobble, { toValue: 0, duration: 175, useNativeDriver: true }),
      ])
    );
    pulseLoop.start();
    wobbleLoop.start();
    return () => {
      pulseLoop.stop();
      wobbleLoop.stop();
      pulse.setValue(1);
      wobble.setValue(0);
    };
  }, [phase, pulse, wobble]);

  // Easter egg: a random tongue-in-cheek line whenever the tap runs dry
  function funnyFailLine(): string {
    const index = 1 + Math.floor(Math.random() * 4);
    return t(`randomBeer.funnyFail${index}`);
  }

  const spin = useCallback(async () => {
    const seq = ++spinSeqRef.current;
    setPhase('spinning');
    setNoMatch(false);
    try {
      const [result] = await Promise.all([
        getRandomBeer({
          max_price: maxPrice ?? undefined,
        }),
        delay(MIN_SPIN_MS),
      ]);
      if (seq !== spinSeqRef.current) return;
      if (result.found && result.beer) {
        setBeer(result.beer);
        setPhase('result');
      } else {
        setBeer(null);
        setFailLine(funnyFailLine());
        setNoMatch(true);
        setPhase('idle');
        setFiltersOpen(true);
      }
    } catch (err) {
      console.log('[RandomBeer] Spin error:', err);
      if (seq !== spinSeqRef.current) return;
      showToast(funnyFailLine(), 'error');
      setPhase(beer ? 'result' : 'idle');
    }
  }, [maxPrice, beer, showToast]);

  function openShop() {
    if (beer?.shop_url) {
      Linking.openURL(beer.shop_url).catch((err) =>
        console.log('[RandomBeer] Open shop error:', err)
      );
    }
  }

  const isSpinning = phase === 'spinning';

  return (
    <Screen>
      <Text style={s.intro}>{t('randomBeer.intro')}</Text>

      {/* Stage: idle prompt / spinning animation / revealed beer */}
      {isSpinning ? (
        <Card variant="elevated" style={s.stageCard}>
          <Animated.View
            style={[
              s.stageIconWrap,
              {
                transform: [
                  { scale: pulse },
                  {
                    rotate: wobble.interpolate({
                      inputRange: [-1, 1],
                      outputRange: ['-12deg', '12deg'],
                    }),
                  },
                ],
              },
            ]}
          >
            <Ionicons name="beer" size={52} color={colors.primary} />
          </Animated.View>
          <Text style={s.spinningText}>{t('randomBeer.spinning')}</Text>
        </Card>
      ) : phase === 'result' && beer ? (
        <Card variant="elevated" padded={false} style={s.resultCard}>
          {beer.image_url ? (
            <Image source={{ uri: beer.image_url }} style={s.beerImage} resizeMode="cover" />
          ) : (
            <View style={s.imagePlaceholder}>
              <Ionicons name="beer-outline" size={56} color={colors.textMuted} />
            </View>
          )}
          <View style={s.resultBody}>
            <Text style={s.resultLabel}>{t('randomBeer.resultLabel')}</Text>
            <Text style={s.beerTitle}>{beer.title}</Text>
            <View style={s.chipRow}>
              {!!beer.product_type && (
                <View style={s.infoChip}>
                  <Text style={s.infoChipText}>{beer.product_type}</Text>
                </View>
              )}
              {!!beer.price && (
                <View style={s.infoChip}>
                  <Text style={s.infoChipText}>
                    {'€'}{Number(beer.price).toFixed(2)}
                  </Text>
                </View>
              )}
            </View>
            <Button
              label={t('randomBeer.viewInShop')}
              icon="cart-outline"
              onPress={openShop}
              style={s.resultButton}
            />
            <Button
              label={t('randomBeer.spinAgain')}
              icon="dice-outline"
              variant="ghost"
              onPress={spin}
            />
          </View>
        </Card>
      ) : (
        <Card variant="elevated" style={s.stageCard}>
          <View style={s.stageIconWrap}>
            <Ionicons name="dice" size={44} color={colors.primary} />
            <Ionicons name="sparkles" size={18} color={colors.primary} style={s.sparkle} />
          </View>
          {noMatch && (
            <View style={s.noMatchRow}>
              <Ionicons name="filter" size={16} color={colors.warning} />
              <View style={s.noMatchTextWrap}>
                <Text style={s.noMatchText}>{failLine}</Text>
                <Text style={s.noMatchHint}>{t('randomBeer.noMatch')}</Text>
              </View>
            </View>
          )}
          <Button
            label={t('randomBeer.spin')}
            icon="sparkles"
            onPress={spin}
            style={s.spinButton}
          />
        </Card>
      )}

      {/* Optional filters */}
      <Card style={s.filterCard}>
        <Pressable
          onPress={() => setFiltersOpen((open) => !open)}
          style={({ pressed }) => [s.filterHeader, pressed && { opacity: 0.7 }]}
        >
          <Text style={s.filterTitle}>{t('randomBeer.filtersTitle')}</Text>
          <Ionicons
            name={filtersOpen ? 'chevron-up' : 'chevron-down'}
            size={18}
            color={colors.textMuted}
          />
        </Pressable>

        {filtersOpen && (
          <View style={s.filterBody}>
            {/* Style filter intentionally omitted for now: the shop's
                product_type values are internal (Auction, Fee, ...), not
                consumer beer styles. Price only until curated styles exist. */}
            <Text style={s.filterLabel}>{t('randomBeer.filterMaxPrice')}</Text>
            <View style={s.chipWrap}>
              {PRICE_PRESETS.map((preset) => {
                const selected = maxPrice === preset;
                return (
                  <Pressable
                    key={preset === null ? 'none' : preset}
                    onPress={() => setMaxPrice(preset)}
                    style={[s.chip, selected && s.chipSelected]}
                  >
                    <Text style={[s.chipText, selected && s.chipTextSelected]}>
                      {preset === null ? t('randomBeer.noLimit') : `€${preset}`}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
        )}
      </Card>
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
  stageCard: {
    alignItems: 'center',
    paddingVertical: spacing.xl,
    marginBottom: spacing.sm,
  },
  stageIconWrap: {
    width: 96,
    height: 96,
    borderRadius: 32,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.lg,
  },
  sparkle: {
    position: 'absolute',
    top: 14,
    right: 14,
  },
  spinButton: {
    alignSelf: 'stretch',
  },
  spinningText: {
    fontFamily: fonts.serifItalic,
    fontSize: 16,
    color: colors.textMuted,
  },
  noMatchRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    marginBottom: spacing.md,
    paddingHorizontal: spacing.sm,
  },
  noMatchTextWrap: {
    flex: 1,
  },
  noMatchText: {
    fontFamily: fonts.serifItalic,
    fontSize: 15,
    lineHeight: 21,
    color: colors.text,
    marginBottom: 2,
  },
  noMatchHint: {
    fontFamily: fonts.serif,
    fontSize: 15,
    lineHeight: 21,
    color: colors.textMuted,
  },
  resultCard: {
    marginBottom: spacing.sm,
  },
  beerImage: {
    width: '100%',
    height: 240,
    backgroundColor: colors.surfaceLow,
  },
  imagePlaceholder: {
    width: '100%',
    height: 160,
    backgroundColor: colors.surfaceLow,
    justifyContent: 'center',
    alignItems: 'center',
  },
  resultBody: {
    padding: spacing.md,
  },
  resultLabel: {
    ...type.label,
    color: colors.primary,
    marginBottom: spacing.xs,
  },
  beerTitle: {
    fontFamily: fonts.headingBold,
    fontSize: 24,
    lineHeight: 30,
    letterSpacing: 0.5,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  infoChip: {
    backgroundColor: colors.surfaceHigh,
    borderRadius: borderRadius.pill,
    paddingVertical: 5,
    paddingHorizontal: spacing.md,
  },
  infoChipText: {
    fontFamily: fonts.heading,
    fontSize: 13,
    letterSpacing: 0.6,
    color: colors.primary,
  },
  resultButton: {
    marginBottom: spacing.sm,
  },
  filterCard: {
    marginBottom: spacing.sm,
  },
  filterHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  filterTitle: {
    fontFamily: fonts.heading,
    fontSize: 16,
    letterSpacing: 0.4,
    color: colors.text,
  },
  filterBody: {
    marginTop: spacing.md,
  },
  filterLabel: {
    ...type.label,
    marginBottom: spacing.sm,
  },
  chipWrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  chip: {
    backgroundColor: colors.surfaceHigh,
    borderRadius: borderRadius.pill,
    paddingVertical: 7,
    paddingHorizontal: spacing.md,
  },
  chipSelected: {
    backgroundColor: colors.primary,
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
});
