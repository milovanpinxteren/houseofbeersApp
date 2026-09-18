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

/**
 * Pickup RSVP for the orders screen. ~80% of members get delivery, so this
 * stays QUIET: one compact collapsed row; tapping it expands the offered
 * store days as one-tap toggle chips. Fetches on focus and on the host's
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
  // Date of the request in flight; all chips are disabled while set.
  const [busyDate, setBusyDate] = useState<string | null>(null);

  const locale = language === 'nl' ? 'nl-NL' : 'en-US';

  /** 'vr 26 sep' — built from the plain date string, noon to dodge TZ edges. */
  function formatDay(date: string): string {
    return new Date(`${date}T12:00:00`).toLocaleDateString(locale, {
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

  const rsvps = days.filter((d) => d.rsvp);
  const summary =
    rsvps.length === 0
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
          <Ionicons name="storefront-outline" size={18} color={colors.primary} />
        </View>
        <Text
          style={[styles.summary, rsvps.length > 0 && styles.summaryConfirmed]}
          numberOfLines={2}
        >
          {summary}
        </Text>
        <Ionicons
          name={expanded ? 'chevron-up' : 'chevron-down'}
          size={16}
          color={colors.textMuted}
        />
      </Pressable>

      {expanded && (
        <View style={styles.body}>
          <View style={styles.chipRow}>
            {days.map((day) => (
              <Pressable
                key={day.date}
                onPress={() => toggleDay(day)}
                disabled={busyDate !== null}
                accessibilityRole="button"
                accessibilityState={{ selected: day.rsvp, disabled: busyDate !== null }}
                style={({ pressed }) => [
                  styles.chip,
                  day.rsvp && styles.chipSelected,
                  busyDate !== null && styles.chipBusy,
                  pressed && styles.pressed,
                ]}
              >
                {day.rsvp && (
                  <Ionicons name="checkmark" size={13} color={colors.background} />
                )}
                <Text style={[styles.chipText, day.rsvp && styles.chipTextSelected]}>
                  {`${formatDay(day.date)} · ${day.open_time}–${day.close_time}`}
                </Text>
              </Pressable>
            ))}
          </View>

          <View style={styles.addressRow}>
            <Ionicons name="location-outline" size={13} color={colors.textMuted} />
            <Text style={styles.addressText}>{t('pickup.address')}</Text>
            <Pressable
              onPress={() =>
                Linking.openURL(MAPS_URL).catch((err) =>
                  console.log('[Pickup] Failed to open maps:', err)
                )
              }
              hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
              style={({ pressed }) => pressed && styles.pressed}
            >
              <Text style={styles.routeLink}>{t('pickup.route')}</Text>
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
    width: 34,
    height: 34,
    borderRadius: 12,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  summary: {
    flex: 1,
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
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: borderRadius.pill,
    paddingHorizontal: spacing.sm + spacing.xs,
    paddingVertical: 7,
  },
  chipSelected: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  chipBusy: {
    opacity: 0.6,
  },
  chipText: {
    fontSize: 13,
    color: colors.text,
  },
  chipTextSelected: {
    color: colors.background,
    fontWeight: '600',
  },
  addressRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    marginTop: spacing.md,
  },
  addressText: {
    flex: 1,
    fontSize: 12,
    color: colors.textMuted,
  },
  routeLink: {
    fontSize: 12,
    color: colors.primary,
    textDecorationLine: 'underline',
  },
});
