import { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  Switch,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '../context/LanguageContext';
import { t } from '../i18n';
import { colors, spacing, borderRadius } from '../theme/colors';
import { usePushSubscription } from '../hooks/usePushSubscription';
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
 * Notification settings section for the profile screen.
 *
 * The enable control reflects the real browser permission, and every dead end
 * (iOS not installed, permission permanently denied, unsupported browser) gets
 * an explanation instead of a button that cannot work.
 */
export default function NotificationSettings() {
  useLanguage(); // re-render on language change
  const { permission, blocker, isBusy, feedback, enable, disable } = usePushSubscription();

  const [preferences, setPreferences] = useState<NotificationPreferences | null>(null);
  const [preferencesUnavailable, setPreferencesUnavailable] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<NotificationCategory | null>(null);

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

  async function handleToggle(key: NotificationCategory, value: boolean) {
    if (!preferences) return;
    const previous = preferences;

    setPreferences({ ...preferences, [key]: value } as NotificationPreferences);
    setSavingKey(key);
    setSaveError(null);

    try {
      const updated = await updateNotificationPreferences(
        { [key]: value } as Partial<NotificationPreferences>
      );
      setPreferences(updated);
    } catch (error) {
      console.log('[Notifications] Save preference failed:', error);
      setPreferences(previous); // revert
      setSaveError(t('notifications.saveError'));
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
  ];

  function renderEnableControl() {
    // iOS Safari only exposes push once the PWA is on the Home Screen.
    if (blocker === 'ios-not-installed') {
      return (
        <View style={styles.infoBlock}>
          <View style={styles.infoHeader}>
            <Ionicons name="phone-portrait-outline" size={20} color={colors.primary} />
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
            <Ionicons name="information-circle-outline" size={20} color={colors.textMuted} />
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
            <Ionicons name="notifications-off-outline" size={20} color={colors.warning} />
            <Text style={styles.infoTitle}>{t('notifications.deniedTitle')}</Text>
          </View>
          <Text style={styles.infoText}>{t('notifications.deniedText')}</Text>
        </View>
      );
    }

    if (permission === 'granted') {
      return (
        <View style={styles.grantedBlock}>
          <View style={styles.infoHeader}>
            <Ionicons name="checkmark-circle" size={20} color={colors.success} />
            <Text style={styles.infoTitle}>{t('notifications.enabled')}</Text>
          </View>
          <Text style={styles.infoText}>{t('notifications.enabledHint')}</Text>
          <TouchableOpacity
            style={styles.linkButton}
            onPress={disable}
            disabled={isBusy}
            activeOpacity={0.7}
          >
            <Text style={styles.linkButtonText}>{t('notifications.turnOff')}</Text>
          </TouchableOpacity>
        </View>
      );
    }

    // permission === 'default' — the one shot at the prompt, behind a tap.
    return (
      <View style={styles.enableBlock}>
        <Text style={styles.infoText}>{t('notifications.enableHint')}</Text>
        <TouchableOpacity
          style={[styles.enableButton, isBusy && styles.buttonDisabled]}
          onPress={enable}
          disabled={isBusy}
          activeOpacity={0.7}
        >
          {isBusy ? (
            <ActivityIndicator size="small" color={colors.background} />
          ) : (
            <>
              <Ionicons name="notifications" size={18} color={colors.background} />
              <Text style={styles.enableButtonText}>{t('notifications.enable')}</Text>
            </>
          )}
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{t('notifications.title')}</Text>
      <View style={styles.card}>
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
                  trackColor={{ false: colors.tertiary + '40', true: colors.primary + '80' }}
                  thumbColor={preferences[category.key] ? colors.primary : colors.textMuted}
                />
              </View>
            ))}
            {saveError && <Text style={styles.feedbackError}>{saveError}</Text>}
            <Text style={styles.mutedNote}>{t('notifications.emailFallbackNote')}</Text>
          </View>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    marginBottom: spacing.md,
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textMuted,
    textTransform: 'uppercase',
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  card: {
    backgroundColor: colors.surface,
    marginHorizontal: spacing.md,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
    padding: spacing.md,
  },

  // Enable control
  enableBlock: {
    gap: spacing.sm,
  },
  grantedBlock: {
    gap: spacing.xs,
  },
  infoBlock: {
    gap: spacing.xs,
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
    fontSize: 16,
    fontWeight: '600',
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
    marginTop: 2,
  },
  enableButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    backgroundColor: colors.primary,
    padding: spacing.md,
    borderRadius: borderRadius.md,
  },
  enableButtonText: {
    color: colors.background,
    fontSize: 16,
    fontWeight: '600',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  linkButton: {
    alignSelf: 'flex-start',
    paddingVertical: spacing.xs,
  },
  linkButtonText: {
    color: colors.primary,
    fontSize: 14,
    fontWeight: '500',
  },

  // Feedback
  feedbackText: {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: spacing.sm,
    lineHeight: 19,
  },
  feedbackError: {
    fontSize: 13,
    color: colors.error,
    marginTop: spacing.sm,
    lineHeight: 19,
  },
  feedbackSuccess: {
    color: colors.success,
  },
  mutedNote: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: spacing.sm,
    lineHeight: 17,
  },

  // Categories
  categories: {
    marginTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.tertiary + '20',
    paddingTop: spacing.md,
  },
  categoriesTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.sm,
  },
  categoryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    gap: spacing.md,
  },
  categoryContent: {
    flex: 1,
  },
  categoryLabel: {
    fontSize: 15,
    color: colors.text,
  },
  categoryHint: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
});
