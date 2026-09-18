import { useCallback, useEffect, useState } from 'react';
import {
  Linking,
  Pressable,
  StyleProp,
  StyleSheet,
  Text,
  View,
  ViewStyle,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import { t } from '../i18n';
import { colors, spacing, borderRadius, fonts } from '../theme/colors';
import { Card, useToast } from './ui';
import {
  cancelPickupRsvp,
  getPickupDays,
  PickupDay,
  rsvpPickup,
} from '../api/pickup';

const MAPS_URL = 'https://maps.google.com/?q=Prior+van+Millstraat+2+Uden';

/** '10:00' -> '10', '10:30' -> '10:30' — compact times for the day tiles. */
function compactTime(time: string): string {
  return time.endsWith(':00') ? time.slice(0, -3) : time;
}

/**
 * Pickup RSVP for the orders screen. ~80% of members get delivery, so this
 * stays QUIET: one compact collapsed row; tapping it expands the offered
 * store days as one-tap date tiles. Fetches on focus and on the host's
 * pull-to-refresh (`refreshSignal`); renders NOTHING when the backend offers
 * no days or the request fails — the normal state for most users.
 */
export function PickupSection({
  language,
  refreshSignal = 0,
  autoExpand = false,
  style,
}: {
  language: string;
  refreshSignal?: number;
  /** Start expanded (deep link /pickup lands here with intent to RSVP). */
  autoExpand?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const { showToast } = useToast();
  const [days, setDays] = useState<PickupDay[]>([]);
  const [expanded, setExpanded] = useState(autoExpand);
  // Date of the request in flight; all tiles are disabled while set.
  const [busyDate, setBusyDate] = useState<string | null>(null);

  const locale = language === 'nl' ? 'nl-NL' : 'en-US';

  /** Noon avoids TZ edges when building a Date from the plain date string. */
  function toDate(date: string): Date {
    return new Date(`${date}T12:00:00`);
  }

  /** 'vr 26 sep' — for the summary line and toasts. */
  function formatDay(date: string): string {
    return toDate(date).toLocaleDateString(locale, {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
    });
  }

  const fetchDays = useCallback(async () => {
    try {
      const data = await getPickupDays();
      setDays(data.days);
    } catch {
      // Backend without the endpoint yet, or a transient error: show nothing.
      setDays([]);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchDays();
    }, [fetchDays])
  );

  useEffect(() => {
    if (refreshSignal > 0) {
      fetchDays();
    }
  }, [refreshSignal, fetchDays]);

  useEffect(() => {
    if (autoExpand) setExpanded(true);
  }, [autoExpand]);

  async function toggleDay(day: PickupDay) {
    if (busyDate) return;
    setBusyDate(day.date);
    try {
      const result = day.rsvp
        ? await cancelPickupRsvp(day.date)
        : await rsvpPickup(day.date);
      setDays((prev) =>
        prev.map((d) => (d.date === result.date ? { ...d, rsvp: result.rsvp } : d))
      );
      showToast(
        result.rsvp
          ? t('pickup.rsvpSuccess', { date: formatDay(day.date) })
          : t('pickup.rsvpCanceled', { date: formatDay(day.date) }),
        result.rsvp ? 'success' : 'info'
      );
    } catch {
      showToast(t('pickup.rsvpError'), 'error');
    } finally {
      setBusyDate(null);
    }
  }

  if (days.length === 0) {
    return null;
  }

  // 3-column grid; the last row gets invisible fillers so tiles keep width.
  const tileRows: (PickupDay | null)[][] = [];
  for (let i = 0; i < days.length; i += 3) {
    const row: (PickupDay | null)[] = days.slice(i, i + 3);
    while (row.length < 3) row.push(null);
    tileRows.push(row);
  }

  const rsvps = days.filter((d) => d.rsvp);
  const confirmed = rsvps.length > 0;
  const summary = !confirmed
    ? t('pickup.prompt')
    : t('pickup.confirmed', { date: formatDay(rsvps[0].date) }) +
      (rsvps.length > 1 ? ` ${t('pickup.plusMore', { count: rsvps.length - 1 })}` : '');

  return (
    <Card style={style} padded={false}>
      <Pressable
        onPress={() => setExpanded((open) => !open)}
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        style={({ pressed }) => [styles.headerRow, pressed && styles.pressed]}
      >
        <View style={styles.iconWrap}>
          <Ionicons name="storefront-outline" size={20} color={colors.primary} />
        </View>
        <View style={styles.headerText}>
          <Text style={styles.eyebrow}>{t('pickup.label')}</Text>
          <Text
            style={[styles.summary, confirmed && styles.summaryConfirmed]}
            numberOfLines={2}
          >
            {summary}
          </Text>
        </View>
        {confirmed && !expanded && (
          <Ionicons name="checkmark-circle" size={18} color={colors.primary} />
        )}
        <Ionicons
          name={expanded ? 'chevron-up' : 'chevron-down'}
          size={16}
          color={colors.textMuted}
        />
      </Pressable>

      {expanded && (
        <View style={styles.body}>
          <View style={styles.tileGrid}>
            {tileRows.map((row, rowIndex) => (
              <View key={rowIndex} style={styles.tileRow}>
                {row.map((day, colIndex) => {
                  if (!day) {
                    return <View key={`filler-${colIndex}`} style={styles.tileFiller} />;
                  }
                  const d = toDate(day.date);
              const weekday = d
                .toLocaleDateString(locale, { weekday: 'short' })
                .replace('.', '');
              const month = d
                .toLocaleDateString(locale, { month: 'short' })
                .replace('.', '');
              return (
                <Pressable
                  key={day.date}
                  onPress={() => toggleDay(day)}
                  disabled={busyDate !== null}
                  accessibilityRole="button"
                  accessibilityState={{
                    selected: day.rsvp,
                    disabled: busyDate !== null,
                  }}
                  style={({ pressed }) => [
                    styles.tile,
                    day.rsvp && styles.tileSelected,
                    busyDate !== null && styles.tileBusy,
                    pressed && styles.pressed,
                  ]}
                >
                  <View style={styles.tileWeekdayRow}>
                    {day.rsvp && (
                      <Ionicons
                        name="checkmark"
                        size={12}
                        color={colors.background}
                      />
                    )}
                    <Text
                      style={[
                        styles.tileWeekday,
                        day.rsvp && styles.tileTextSelected,
                      ]}
                    >
                      {weekday}
                    </Text>
                  </View>
                  <Text
                    style={[styles.tileDay, day.rsvp && styles.tileTextSelected]}
                  >
                    {d.getDate()}
                  </Text>
                  <Text
                    style={[styles.tileMonth, day.rsvp && styles.tileTextSelected]}
                  >
                    {month}
                  </Text>
                  <Text
                    style={[styles.tileTime, day.rsvp && styles.tileTimeSelected]}
                  >
                    {`${compactTime(day.open_time)}–${compactTime(day.close_time)} u`}
                  </Text>
                </Pressable>
              );
                })}
              </View>
            ))}
          </View>

          <View style={styles.divider} />

          <View style={styles.addressRow}>
            <Ionicons name="location-outline" size={14} color={colors.textMuted} />
            <Text style={styles.addressText}>{t('pickup.address')}</Text>
            <Pressable
              onPress={() =>
                Linking.openURL(MAPS_URL).catch((err) =>
                  console.log('[Pickup] Failed to open maps:', err)
                )
              }
              hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
              style={({ pressed }) => [styles.routeButton, pressed && styles.pressed]}
            >
              <Text style={styles.routeText}>{t('pickup.route')}</Text>
              <Ionicons name="chevron-forward" size={12} color={colors.primary} />
            </Pressable>
          </View>
        </View>
      )}
    </Card>
  );
}

const styles = StyleSheet.create({
  pressed: {
    opacity: 0.7,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm + spacing.xs,
    padding: spacing.md,
  },
  iconWrap: {
    width: 42,
    height: 42,
    borderRadius: 14,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  headerText: {
    flex: 1,
    gap: 1,
  },
  eyebrow: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: colors.primary,
  },
  summary: {
    fontFamily: fonts.serif,
    fontSize: 15,
    lineHeight: 20,
    color: colors.textMuted,
  },
  summaryConfirmed: {
    color: colors.text,
  },
  body: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.md,
  },
  tileGrid: {
    gap: spacing.sm,
  },
  tileRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  tileFiller: {
    flex: 1,
  },
  tile: {
    flex: 1,
    alignItems: 'center',
    backgroundColor: colors.surfaceHigh,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm + spacing.xs,
    paddingHorizontal: spacing.sm,
    gap: 1,
  },
  tileSelected: {
    backgroundColor: colors.primary,
  },
  tileBusy: {
    opacity: 0.6,
  },
  tileWeekdayRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
  },
  tileWeekday: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: 'uppercase',
    color: colors.textMuted,
  },
  tileDay: {
    fontFamily: fonts.headingBold,
    fontSize: 24,
    lineHeight: 28,
    color: colors.text,
  },
  tileMonth: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: 'uppercase',
    color: colors.textMuted,
  },
  tileTime: {
    fontSize: 11,
    color: colors.textMuted,
    marginTop: 3,
  },
  tileTextSelected: {
    color: colors.background,
  },
  tileTimeSelected: {
    color: colors.background,
    opacity: 0.75,
  },
  divider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: colors.borderStrong,
    marginVertical: spacing.md,
  },
  addressRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  addressText: {
    flex: 1,
    fontFamily: fonts.serif,
    fontSize: 15,
    color: colors.textMuted,
  },
  routeButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
  },
  routeText: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    color: colors.primary,
  },
});
