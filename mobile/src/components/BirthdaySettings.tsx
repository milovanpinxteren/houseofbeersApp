import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  Pressable,
  StyleSheet,
  Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../context/AuthContext';
import { useLanguage } from '../context/LanguageContext';
import { t } from '../i18n';
import { colors, spacing, borderRadius, fonts } from '../theme/colors';
import { updateBirthdate } from '../api/auth';
import { usePushSubscription } from '../hooks/usePushSubscription';
import { Button, useToast } from './ui';

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
 * iOS Safari renders an empty `<input type="date">` as a bare dark box: no
 * placeholder, no affordance — users reported "a black field". The fix needs
 * pseudo-elements (an ::before hint on empty inputs, WebKit value alignment),
 * which inline styles cannot express, so the web field is styled through an
 * injected stylesheet. Chromium ignores the ::before (it draws its own
 * dd-mm-yyyy hint), so the hint never doubles up.
 */
const WEB_DATE_CSS = `
.hob-date-input {
  background-color: ${colors.surface};
  color: ${colors.text};
  border: 1px solid ${colors.borderStrong};
  border-radius: ${borderRadius.md}px;
  padding: 12px 14px;
  font-size: 16px;
  width: 100%;
  min-height: 48px;
  box-sizing: border-box;
  color-scheme: dark;
  -webkit-appearance: none;
  appearance: none;
  text-align: left;
}
.hob-date-input:focus {
  outline: none;
  border-color: ${colors.primary};
}
.hob-date-input::-webkit-date-and-time-value {
  text-align: left;
}
.hob-date-input.is-empty::before {
  content: attr(data-placeholder);
  color: ${colors.textMuted};
}
`;

let webDateCssInjected = false;
function injectWebDateCss() {
  if (webDateCssInjected || typeof document === 'undefined') return;
  const style = document.createElement('style');
  style.textContent = WEB_DATE_CSS;
  document.head.appendChild(style);
  webDateCssInjected = true;
}

/**
 * `<input type="date">` on the web (this is a PWA — a native-only picker would
 * leave everyone without an input), a typed YYYY-MM-DD field elsewhere.
 */
function DateField({ value, onChange, disabled }: DateFieldProps) {
  if (Platform.OS === 'web') {
    injectWebDateCss();
    return React.createElement('input', {
      type: 'date',
      className: value ? 'hob-date-input' : 'hob-date-input is-empty',
      'data-placeholder': t('birthday.placeholder'),
      value,
      max: new Date().toISOString().slice(0, 10),
      disabled,
      onChange: (event: { target: { value: string } }) => onChange(event.target.value),
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
 * Birthday row for the profile screen's preferences card. Collapsed it is a
 * single ListItem-style row; expanding it reveals the editor. Doubles as the
 * best moment to ask for notification permission: right after a save, when
 * the value is obvious.
 */
export default function BirthdaySettings() {
  useLanguage(); // re-render on language change
  const { user, refreshUser } = useAuth();
  const { permission, blocker, isBusy, feedback, enable } = usePushSubscription();
  const { showToast } = useToast();

  const [expanded, setExpanded] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [showPushPrompt, setShowPushPrompt] = useState(false);

  const birthdate = user?.birthdate ?? null;
  const isLocked = user?.birthdate_locked === true;
  const canAskForPush = permission === 'default' && blocker === 'none';

  function toggleExpanded() {
    setExpanded((current) => !current);
  }

  function startEditing() {
    setValue('');
    setError(null);
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

      showToast(t('birthday.saved'), 'success');
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
    <View style={styles.wrap}>
      {/* Collapsed row — matches the ListItem look of the surrounding card */}
      <Pressable
        onPress={toggleExpanded}
        style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
      >
        <View style={styles.iconWrap}>
          <Ionicons name="gift-outline" size={20} color={colors.primary} />
        </View>
        <View style={styles.rowContent}>
          <Text style={styles.rowLabel}>{t('birthday.title')}</Text>
          <Text style={styles.rowSubtitle} numberOfLines={1}>
            {birthdate ? formatDate(birthdate) : t('birthday.notSet')}
          </Text>
        </View>
        {isLocked && (
          <Ionicons name="lock-closed" size={15} color={colors.textMuted} />
        )}
        <Ionicons
          name={expanded ? 'chevron-up' : 'chevron-down'}
          size={18}
          color={colors.textMuted}
        />
      </Pressable>

      {expanded && (
        <View style={styles.body}>
          {isLocked ? (
            <View style={styles.lockedBlock}>
              <Text style={styles.lockedTitle}>{t('birthday.lockedTitle')}</Text>
              <Text style={styles.bodyText}>{t('birthday.lockedText')}</Text>
            </View>
          ) : isEditing ? (
            <View style={styles.editBlock}>
              <Text style={styles.fieldLabel}>{t('birthday.label')}</Text>
              <DateField value={value} onChange={setValue} disabled={isSaving} />
              <Text style={styles.hintText}>{t('birthday.hint')}</Text>
              <Text style={styles.hintText}>{t('birthday.lockWarning')}</Text>
              {error && <Text style={styles.errorText}>{error}</Text>}
              <View style={styles.buttonRow}>
                <Button
                  label={t('common.cancel')}
                  variant="ghost"
                  onPress={() => setIsEditing(false)}
                  disabled={isSaving}
                  style={styles.flexButton}
                />
                <Button
                  label={t('save')}
                  onPress={handleSave}
                  loading={isSaving}
                  style={styles.flexButton}
                />
              </View>
            </View>
          ) : (
            <View style={styles.idleBlock}>
              <Text style={styles.bodyText}>{t('birthday.prompt')}</Text>
              <Button
                label={t('birthday.set')}
                size="sm"
                icon="calendar-outline"
                onPress={startEditing}
                style={styles.startButton}
              />
            </View>
          )}

          {/* The high-value moment to ask: a gift is now on its way. */}
          {showPushPrompt && (
            <View style={styles.pushPrompt}>
              <Text style={styles.pushPromptTitle}>{t('birthday.pushPromptTitle')}</Text>
              <Text style={styles.bodyText}>{t('birthday.pushPromptText')}</Text>
              <View style={styles.buttonRow}>
                <Button
                  label={t('birthday.pushPromptLater')}
                  variant="ghost"
                  onPress={() => setShowPushPrompt(false)}
                  disabled={isBusy}
                  style={styles.flexButton}
                />
                <Button
                  label={t('notifications.enable')}
                  onPress={handleEnablePush}
                  loading={isBusy}
                  style={styles.flexButton}
                />
              </View>
            </View>
          )}

          {feedback && (
            <Text style={feedback.type === 'error' ? styles.errorText : styles.hintText}>
              {feedback.message}
            </Text>
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

  // Expanded body
  body: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.md,
    gap: spacing.sm,
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

  idleBlock: {
    gap: spacing.sm,
  },
  startButton: {
    alignSelf: 'flex-start',
  },
  editBlock: {
    gap: spacing.sm,
  },
  fieldLabel: {
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 0.3,
    color: colors.textMuted,
  },
  textInput: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    fontSize: 16,
    color: colors.text,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  flexButton: {
    flex: 1,
  },

  lockedBlock: {
    borderLeftWidth: 2,
    borderLeftColor: colors.tertiary,
    paddingLeft: spacing.sm,
    gap: spacing.xs,
  },
  lockedTitle: {
    fontFamily: fonts.heading,
    fontSize: 14,
    letterSpacing: 0.4,
    color: colors.text,
  },

  pushPrompt: {
    marginTop: spacing.xs,
    paddingTop: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    gap: spacing.xs,
  },
  pushPromptTitle: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.4,
    color: colors.text,
  },
});
