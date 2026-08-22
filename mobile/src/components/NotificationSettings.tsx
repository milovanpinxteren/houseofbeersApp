import { useCallback, useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  Switch,
  Pressable,
  StyleSheet,
  Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '../context/LanguageContext';
import { t } from '../i18n';
import { colors, spacing, fonts } from '../theme/colors';
import { usePushSubscription } from '../hooks/usePushSubscription';
import { syncExistingSubscription } from '../utils/webPush';
import { Button, useToast } from './ui';
import {
  getNotificationPreferences,
  updateNotificationPreferences,
  NotificationCategory,
  NotificationPreferences,
} from '../api/push';

interface CategoryRow {
  key: NotificationCategory;
  label: string;
  hint: string;
}

/**
 * Notification row for the profile screen's preferences card. Collapsed it is
 * a single ListItem-style row showing the current status; expanding it reveals
 * the enable control and per-category toggles.
 *
 * The enable control reflects the real browser permission, and every dead end
 * (iOS not installed, permission permanently denied, unsupported browser) gets
 * an explanation instead of a button that cannot work.
 *
 * Notifications are ON by default (the server-side preference defaults to
 * enabled). What is still needed per device is the browser permission, so:
 * - if permission is already granted, the device is (re)subscribed silently;
 * - if permission was never asked, the prompt fires on the user's first
 *   interaction with this row — never on page load, browsers punish that.
 */
export default function NotificationSettings() {
  useLanguage(); // re-render on language change
  const { permission, blocker, isBusy, feedback, enable, disable } = usePushSubscription();
  const { showToast } = useToast();

  const [expanded, setExpanded] = useState(false);
  const [preferences, setPreferences] = useState<NotificationPreferences | null>(null);
  const [preferencesUnavailable, setPreferencesUnavailable] = useState(false);
  const [savingKey, setSavingKey] = useState<NotificationCategory | null>(null);

  // One attempt each per mount: silent re-subscribe, and the first-interaction
  // permission prompt.
  const silentSyncDone = useRef(false);
  const autoEnableAttempted = useRef(false);

  const loadPreferences = useCallback(async () => {
    try {
      const data = await getNotificationPreferences();
      setPreferences(data);
      setPreferencesUnavailable(false);
    } catch (error) {
      // The endpoint may not exist yet — degrade to just the enable control.
      console.log('[Notifications] Preferences unavailable:', error);
      setPreferencesUnavailable(true);
    }
  }, []);

  useEffect(() => {
    loadPreferences();
  }, [loadPreferences]);

  // Preference on + permission already granted: make sure this device really
  // has a subscription (it can be lost when the PWA is re-installed or the
  // push service rotates it). Never prompts — permission is already granted.
  useEffect(() => {
    if (silentSyncDone.current) return;
    if (permission !== 'granted') return;
    if (!preferences) return; // wait until we know the user's choice
    if (!preferences.push_enabled) return; // explicit opt-out
    silentSyncDone.current = true;
    void syncExistingSubscription();
  }, [permission, preferences]);

  // Tapping the row is the user's first interaction with notifications. If
  // the preference is on (the default) and permission was never decided, this
  // tap is the user gesture we use to run the permission + subscribe flow.
  function handleRowPress() {
    const willExpand = !expanded;
    setExpanded(willExpand);

    if (
      willExpand &&
      !autoEnableAttempted.current &&
      !isBusy &&
      permission === 'default' &&
      blocker === 'none' &&
      preferences?.push_enabled !== false // unset counts as the on-default
    ) {
      autoEnableAttempted.current = true;
      void enable();
    }
  }

  async function handleToggle(key: NotificationCategory, value: boolean) {
    if (!preferences) return;
    const previous = preferences;

    setPreferences({ ...preferences, [key]: value } as NotificationPreferences);
    setSavingKey(key);

    try {
      const updated = await updateNotificationPreferences(
        { [key]: value } as Partial<NotificationPreferences>
      );
      setPreferences(updated);
    } catch (error) {
      console.log('[Notifications] Save preference failed:', error);
      setPreferences(previous); // revert
      showToast(t('notifications.saveError'), 'error');
    } finally {
      setSavingKey(null);
    }
  }

  const categories: CategoryRow[] = [
    {
      key: 'birthday',
      label: t('notifications.categoryBirthday'),
      hint: t('notifications.categoryBirthdayHint'),
    },
    {
      key: 'announcements',
      label: t('notifications.categoryAnnouncements'),
      hint: t('notifications.categoryAnnouncementsHint'),
    },
    {
      key: 'recommendations',
      label: t('notifications.categoryRecommendations'),
      hint: t('notifications.categoryRecommendationsHint'),
    },
    {
      key: 'raffle',
      label: t('notifications.categoryRaffle'),
      hint: t('notifications.categoryRaffleHint'),
    },
  ];

  function statusSubtitle(): string {
    if (blocker === 'ios-not-installed') return t('notifications.iosInstallTitle');
    if (permission === 'unsupported') return t('notifications.unsupportedTitle');
    if (permission === 'denied') return t('notifications.deniedTitle');
    if (permission === 'granted') return t('notifications.enabled');
    // Permission not decided yet. The preference itself defaults to on, so
    // read as "on, just activate this device" unless the user opted out.
    if (preferences?.push_enabled === false) return t('notifications.statusOff');
    return t('notifications.statusReady');
  }

  function renderEnableControl() {
    // iOS Safari only exposes push once the PWA is on the Home Screen.
    if (blocker === 'ios-not-installed') {
      return (
        <View style={styles.infoBlock}>
          <View style={styles.infoHeader}>
            <Ionicons name="phone-portrait-outline" size={18} color={colors.primary} />
            <Text style={styles.infoTitle}>{t('notifications.iosInstallTitle')}</Text>
          </View>
          <Text style={styles.infoText}>{t('notifications.iosInstallText')}</Text>
          <Text style={styles.stepText}>1. {t('install.step1')}</Text>
          <Text style={styles.stepText}>2. {t('install.step2')}</Text>
          <Text style={styles.stepText}>3. {t('notifications.iosStep3')}</Text>
        </View>
      );
    }

    if (permission === 'unsupported') {
      return (
        <View style={styles.infoBlock}>
          <View style={styles.infoHeader}>
            <Ionicons name="information-circle-outline" size={18} color={colors.textMuted} />
            <Text style={styles.infoTitle}>{t('notifications.unsupportedTitle')}</Text>
          </View>
          <Text style={styles.infoText}>
            {Platform.OS === 'web'
              ? t('notifications.unsupportedText')
              : t('notifications.nativeUnsupportedText')}
          </Text>
        </View>
      );
    }

    // A denial cannot be re-prompted, so point at system settings instead.
    if (permission === 'denied') {
      return (
        <View style={[styles.infoBlock, styles.warningBlock]}>
          <View style={styles.infoHeader}>
            <Ionicons name="notifications-off-outline" size={18} color={colors.warning} />
            <Text style={styles.infoTitle}>{t('notifications.deniedTitle')}</Text>
          </View>
          <Text style={styles.infoText}>{t('notifications.deniedText')}</Text>
        </View>
      );
    }

    if (permission === 'granted') {
      return (
        <View style={styles.infoBlock}>
          <View style={styles.infoHeader}>
            <Ionicons name="checkmark-circle" size={18} color={colors.success} />
            <Text style={styles.infoTitle}>{t('notifications.enabled')}</Text>
          </View>
          <Text style={styles.infoText}>{t('notifications.enabledHint')}</Text>
          <Button
            label={t('notifications.turnOff')}
            variant="ghost"
            size="sm"
            onPress={disable}
            disabled={isBusy}
            style={styles.turnOffButton}
          />
        </View>
      );
    }

    // permission === 'default' — the one shot at the prompt, behind a tap.
    // With the on-by-default preference the copy explains that notifications
    // are already on for the account and only this device needs activating.
    return (
      <View style={styles.infoBlock}>
        <Text style={styles.infoText}>
          {preferences?.push_enabled === false
            ? t('notifications.enableHint')
            : t('notifications.defaultOnHint')}
        </Text>
        <Button
          label={t('notifications.enable')}
          icon="notifications-outline"
          onPress={enable}
          loading={isBusy}
        />
      </View>
    );
  }

  return (
    <View style={styles.wrap}>
      {/* Collapsed row — matches the ListItem look of the surrounding card */}
      <Pressable
        onPress={handleRowPress}
        style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
      >
        <View style={styles.iconWrap}>
          <Ionicons name="notifications-outline" size={20} color={colors.primary} />
        </View>
        <View style={styles.rowContent}>
          <Text style={styles.rowLabel}>{t('notifications.title')}</Text>
          <Text style={styles.rowSubtitle} numberOfLines={1}>
            {statusSubtitle()}
          </Text>
        </View>
        {permission === 'granted' && (
          <View style={styles.statusDot} />
        )}
        <Ionicons
          name={expanded ? 'chevron-up' : 'chevron-down'}
          size={18}
          color={colors.textMuted}
        />
      </Pressable>

      {expanded && (
        <View style={styles.body}>
          {renderEnableControl()}

          {feedback && (
            <Text
              style={[
                styles.feedbackText,
                feedback.type === 'error' && styles.feedbackError,
                feedback.type === 'success' && styles.feedbackSuccess,
              ]}
            >
              {feedback.message}
            </Text>
          )}

          {preferencesUnavailable && (
            <Text style={styles.mutedNote}>{t('notifications.prefsUnavailable')}</Text>
          )}

          {preferences && (
            <View style={styles.categories}>
              <Text style={styles.categoriesTitle}>{t('notifications.categories')}</Text>
              {categories.map((category) => (
                <View key={category.key} style={styles.categoryRow}>
                  <View style={styles.categoryContent}>
                    <Text style={styles.categoryLabel}>{category.label}</Text>
                    <Text style={styles.categoryHint}>{category.hint}</Text>
                  </View>
                  <Switch
                    value={preferences[category.key]}
                    onValueChange={(value) => handleToggle(category.key, value)}
                    disabled={savingKey !== null}
                    trackColor={{ false: colors.surfaceLow, true: colors.primary + '80' }}
                    thumbColor={preferences[category.key] ? colors.primary : colors.textMuted}
                  />
                </View>
              ))}
              <Text style={styles.mutedNote}>{t('notifications.pushOnlyNote')}</Text>
            </View>
          )}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },

  // Collapsed row — mirrors the kit ListItem metrics
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: spacing.md,
    gap: spacing.md,
  },
  rowPressed: {
    backgroundColor: colors.surfaceHigh,
  },
  iconWrap: {
    width: 38,
    height: 38,
    borderRadius: 12,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  rowContent: {
    flex: 1,
  },
  rowLabel: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text,
  },
  rowSubtitle: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.success,
  },

  // Expanded body
  body: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.md,
    gap: spacing.sm,
  },
  infoBlock: {
    gap: spacing.sm,
  },
  warningBlock: {
    borderLeftWidth: 2,
    borderLeftColor: colors.warning,
    paddingLeft: spacing.sm,
  },
  infoHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  infoTitle: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.4,
    color: colors.text,
    flex: 1,
  },
  infoText: {
    fontSize: 13,
    color: colors.textMuted,
    lineHeight: 19,
  },
  stepText: {
    fontSize: 13,
    color: colors.text,
    lineHeight: 18,
  },
  turnOffButton: {
    alignSelf: 'flex-start',
  },

  // Feedback
  feedbackText: {
    fontSize: 13,
    color: colors.textMuted,
    lineHeight: 19,
  },
  feedbackError: {
    color: colors.error,
  },
  feedbackSuccess: {
    color: colors.success,
  },
  mutedNote: {
    fontSize: 12,
    color: colors.textMuted,
    lineHeight: 17,
    marginTop: spacing.xs,
  },

  // Categories
  categories: {
    marginTop: spacing.xs,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingTop: spacing.md,
  },
  categoriesTitle: {
    fontFamily: fonts.heading,
    fontSize: 13,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: colors.textMuted,
    marginBottom: spacing.sm,
  },
  categoryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    gap: spacing.md,
    minHeight: 44,
  },
  categoryContent: {
    flex: 1,
  },
  categoryLabel: {
    fontSize: 14,
    color: colors.text,
  },
  categoryHint: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
});
