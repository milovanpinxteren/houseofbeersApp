import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../context/AuthContext';
import { useLanguage } from '../context/LanguageContext';
import { t } from '../i18n';
import { colors, spacing, borderRadius } from '../theme/colors';
import { updateBirthdate } from '../api/auth';
import { usePushSubscription } from '../hooks/usePushSubscription';

/** Matches the backend's anti-abuse window; the backend stays the authority. */
const LEAD_TIME_DAYS = 30;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function isRealDate(iso: string): boolean {
  if (!ISO_DATE.test(iso)) return false;
  const [year, month, day] = iso.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  return (
    date.getFullYear() === year &&
    date.getMonth() === month - 1 &&
    date.getDate() === day &&
    date.getTime() <= Date.now()
  );
}

/** Hint only — used to warn honestly that the first gift lands next year. */
function daysUntilNextBirthday(iso: string): number | null {
  if (!ISO_DATE.test(iso)) return null;
  const [, month, day] = iso.split('-').map(Number);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  let next = new Date(today.getFullYear(), month - 1, day);
  if (next.getTime() < today.getTime()) {
    next = new Date(today.getFullYear() + 1, month - 1, day);
  }
  return Math.round((next.getTime() - today.getTime()) / 86400000);
}

function formatDate(iso: string): string {
  try {
    const [year, month, day] = iso.split('-').map(Number);
    return new Date(year, month - 1, day).toLocaleDateString();
  } catch {
    return iso;
  }
}

/**
 * The backend returns the real reason (invalid date, under 18, locked); show it
 * verbatim rather than replacing it with a generic failure message.
 */
function readableError(error: unknown): string {
  if (!(error instanceof Error)) return t('birthday.saveError');
  const message = error.message || '';
  if (message.includes('status 404')) return t('birthday.unavailable');
  // Strip the DRF field/key prefix the API client prepends ("birthdate: ...",
  // "error: ..." for the 403 lock) so the reason itself reads as written.
  const cleaned = message.replace(/^(?:birthdate|error|detail|non_field_errors):\s*/i, '').trim();
  return cleaned || t('birthday.saveError');
}

interface DateFieldProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

/**
 * `<input type="date">` on the web (this is a PWA — a native-only picker would
 * leave everyone without an input), a typed YYYY-MM-DD field elsewhere.
 */
function DateField({ value, onChange, disabled }: DateFieldProps) {
  if (Platform.OS === 'web') {
    return React.createElement('input', {
      type: 'date',
      value,
      max: new Date().toISOString().slice(0, 10),
      disabled,
      onChange: (event: { target: { value: string } }) => onChange(event.target.value),
      style: {
        backgroundColor: colors.background,
        color: colors.text,
        border: `1px solid ${colors.tertiary}50`,
        borderRadius: borderRadius.md,
        padding: spacing.md,
        fontSize: 16,
        width: '100%',
        boxSizing: 'border-box',
        colorScheme: 'dark',
      },
    });
  }

  return (
    <TextInput
      style={styles.textInput}
      value={value}
      onChangeText={onChange}
      placeholder={t('birthday.placeholder')}
      placeholderTextColor={colors.textMuted}
      keyboardType="numbers-and-punctuation"
      autoCorrect={false}
      editable={!disabled}
      maxLength={10}
    />
  );
}

/**
 * Birthday section for the profile screen. Doubles as the best moment to ask
 * for notification permission: right after a save, when the value is obvious.
 */
export default function BirthdaySettings() {
  useLanguage(); // re-render on language change
  const { user, refreshUser } = useAuth();
  const { permission, blocker, isBusy, feedback, enable } = usePushSubscription();

  const [isEditing, setIsEditing] = useState(false);
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);
  const [leadTimeNotice, setLeadTimeNotice] = useState<string | null>(null);
  const [showPushPrompt, setShowPushPrompt] = useState(false);

  const birthdate = user?.birthdate ?? null;
  const isLocked = user?.birthdate_locked === true;
  const canAskForPush = permission === 'default' && blocker === 'none';

  function startEditing() {
    setValue(birthdate || '');
    setError(null);
    setSavedNotice(null);
    setIsEditing(true);
  }

  async function handleSave() {
    const trimmed = value.trim();
    if (!isRealDate(trimmed)) {
      setError(t('birthday.invalidFormat'));
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      await updateBirthdate(trimmed);

      const days = daysUntilNextBirthday(trimmed);
      setLeadTimeNotice(
        days !== null && days < LEAD_TIME_DAYS ? t('birthday.leadTimeNotice') : null
      );
      setSavedNotice(t('birthday.saved'));
      setIsEditing(false);
      setShowPushPrompt(canAskForPush);

      try {
        await refreshUser();
      } catch (refreshError) {
        console.log('[Birthday] Refresh user failed:', refreshError);
      }
    } catch (saveError) {
      console.log('[Birthday] Save failed:', saveError);
      setError(readableError(saveError));
      // The lock may have been applied since this screen loaded.
      refreshUser().catch(() => undefined);
    } finally {
      setIsSaving(false);
    }
  }

  async function handleEnablePush() {
    const ok = await enable();
    if (ok) setShowPushPrompt(false);
  }

  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{t('birthday.title')}</Text>
      <View style={styles.card}>
        <View style={styles.headerRow}>
          <View style={styles.iconContainer}>
            <Ionicons name="gift" size={22} color={colors.primary} />
          </View>
          <View style={styles.headerContent}>
            <Text style={styles.headerLabel}>{t('birthday.label')}</Text>
            <Text style={styles.headerValue}>
              {birthdate ? formatDate(birthdate) : t('birthday.notSet')}
            </Text>
          </View>
          {isLocked && <Ionicons name="lock-closed" size={18} color={colors.textMuted} />}
        </View>

        {!birthdate && !isEditing && <Text style={styles.bodyText}>{t('birthday.prompt')}</Text>}

        {isLocked ? (
          <View style={styles.lockedBlock}>
            <Text style={styles.lockedTitle}>{t('birthday.lockedTitle')}</Text>
            <Text style={styles.bodyText}>{t('birthday.lockedText')}</Text>
          </View>
        ) : isEditing ? (
          <View style={styles.editBlock}>
            <DateField value={value} onChange={setValue} disabled={isSaving} />
            <Text style={styles.hintText}>{t('birthday.hint')}</Text>
            <Text style={styles.hintText}>{t('birthday.lockWarning')}</Text>
            {error && <Text style={styles.errorText}>{error}</Text>}
            <View style={styles.buttonRow}>
              <TouchableOpacity
                style={styles.cancelButton}
                onPress={() => setIsEditing(false)}
                disabled={isSaving}
                activeOpacity={0.7}
              >
                <Text style={styles.cancelButtonText}>{t('common.cancel')}</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.saveButton, isSaving && styles.buttonDisabled]}
                onPress={handleSave}
                disabled={isSaving}
                activeOpacity={0.7}
              >
                {isSaving ? (
                  <ActivityIndicator size="small" color={colors.background} />
                ) : (
                  <Text style={styles.saveButtonText}>{t('save')}</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        ) : (
          <TouchableOpacity style={styles.actionButton} onPress={startEditing} activeOpacity={0.7}>
            <Ionicons name="calendar-outline" size={18} color={colors.background} />
            <Text style={styles.actionButtonText}>
              {birthdate ? t('birthday.edit') : t('birthday.set')}
            </Text>
          </TouchableOpacity>
        )}

        {savedNotice && !isEditing && <Text style={styles.successText}>{savedNotice}</Text>}
        {leadTimeNotice && !isEditing && <Text style={styles.hintText}>{leadTimeNotice}</Text>}

        {/* The high-value moment to ask: a gift is now on its way. */}
        {showPushPrompt && (
          <View style={styles.pushPrompt}>
            <Text style={styles.pushPromptTitle}>{t('birthday.pushPromptTitle')}</Text>
            <Text style={styles.bodyText}>{t('birthday.pushPromptText')}</Text>
            <View style={styles.buttonRow}>
              <TouchableOpacity
                style={styles.cancelButton}
                onPress={() => setShowPushPrompt(false)}
                disabled={isBusy}
                activeOpacity={0.7}
              >
                <Text style={styles.cancelButtonText}>{t('birthday.pushPromptLater')}</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.saveButton, isBusy && styles.buttonDisabled]}
                onPress={handleEnablePush}
                disabled={isBusy}
                activeOpacity={0.7}
              >
                {isBusy ? (
                  <ActivityIndicator size="small" color={colors.background} />
                ) : (
                  <Text style={styles.saveButtonText}>{t('notifications.enable')}</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        )}

        {feedback && (
          <Text style={feedback.type === 'error' ? styles.errorText : styles.hintText}>
            {feedback.message}
          </Text>
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
    gap: spacing.sm,
  },

  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  iconContainer: {
    width: 36,
    height: 36,
    borderRadius: 8,
    backgroundColor: colors.primary + '15',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: spacing.md,
  },
  headerContent: {
    flex: 1,
  },
  headerLabel: {
    fontSize: 13,
    color: colors.textMuted,
  },
  headerValue: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text,
    marginTop: 2,
  },

  bodyText: {
    fontSize: 13,
    color: colors.textMuted,
    lineHeight: 19,
  },
  hintText: {
    fontSize: 12,
    color: colors.textMuted,
    lineHeight: 17,
  },
  errorText: {
    fontSize: 13,
    color: colors.error,
    lineHeight: 19,
  },
  successText: {
    fontSize: 13,
    color: colors.success,
    lineHeight: 19,
  },

  editBlock: {
    gap: spacing.sm,
  },
  textInput: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    fontSize: 16,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.tertiary + '50',
  },
  buttonRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  cancelButton: {
    flex: 1,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.textMuted,
  },
  cancelButtonText: {
    color: colors.textMuted,
    fontSize: 15,
    fontWeight: '600',
  },
  saveButton: {
    flex: 1,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    alignItems: 'center',
    backgroundColor: colors.primary,
  },
  saveButtonText: {
    color: colors.background,
    fontSize: 15,
    fontWeight: '600',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  actionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    backgroundColor: colors.primary,
    padding: spacing.md,
    borderRadius: borderRadius.md,
  },
  actionButtonText: {
    color: colors.background,
    fontSize: 15,
    fontWeight: '600',
  },

  lockedBlock: {
    borderLeftWidth: 2,
    borderLeftColor: colors.tertiary,
    paddingLeft: spacing.sm,
    gap: spacing.xs,
  },
  lockedTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
  },

  pushPrompt: {
    marginTop: spacing.sm,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.tertiary + '20',
    gap: spacing.xs,
  },
  pushPromptTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.text,
  },
});
