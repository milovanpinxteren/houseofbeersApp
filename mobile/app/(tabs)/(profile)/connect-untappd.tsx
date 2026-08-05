import { useState, useEffect } from 'react';
import {
  View,
  Text,
  TextInput,
  Pressable,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  Linking,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import {
  linkUntappd,
  unlinkUntappd,
  getUntappdProfile,
  UntappdProfile,
} from '../../../src/api/recommendations';
import { colors, spacing, borderRadius, fonts, type } from '../../../src/theme/colors';
import { Button, Card, useToast } from '../../../src/components/ui';

export default function ConnectUntappdScreen() {
  const router = useRouter();
  const { language } = useLanguage();
  const { showToast } = useToast();
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [username, setUsername] = useState('');
  const [error, setError] = useState('');
  const [profile, setProfile] = useState<UntappdProfile | null>(null);

  useEffect(() => {
    loadProfile();
  }, []);

  async function loadProfile() {
    try {
      const data = await getUntappdProfile();
      setProfile(data.untappd);
      if (data.untappd) {
        setUsername(data.untappd.username);
      }
    } catch (err) {
      console.log('[ConnectUntappd] Load error:', err);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleConnect() {
    const trimmedUsername = username.trim();
    if (!trimmedUsername) {
      setError(t('recommendations.usernameRequired'));
      return;
    }

    setIsSubmitting(true);
    setError('');

    try {
      const result = await linkUntappd(trimmedUsername);
      setProfile(result.untappd);
      showToast(t('recommendations.untappdConnected'), 'success');
      router.back();
    } catch (err) {
      console.log('[ConnectUntappd] Connect error:', err);
      if (err instanceof Error) {
        // The backend returns a stable message for the not-found/private case
        // (the API client does not expose HTTP status codes on errors)
        if (err.message.includes('not found or is private')) {
          setError(t('recommendations.profilePrivateOrNotFound'));
        } else {
          setError(err.message);
        }
      } else {
        setError(t('recommendations.connectError'));
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleDisconnect() {
    Alert.alert(
      t('recommendations.disconnectUntappd'),
      t('recommendations.disconnectConfirm'),
      [
        { text: t('common.cancel'), style: 'cancel' },
        {
          text: t('common.disconnect'),
          style: 'destructive',
          onPress: async () => {
            setIsSubmitting(true);
            try {
              await unlinkUntappd();
              setProfile(null);
              setUsername('');
              showToast(t('recommendations.untappdDisconnected'), 'success');
            } catch (err) {
              console.log('[ConnectUntappd] Disconnect error:', err);
              showToast(t('recommendations.disconnectError'), 'error');
            } finally {
              setIsSubmitting(false);
            }
          },
        },
      ]
    );
  }

  function openUntappd() {
    Linking.openURL('https://untappd.com');
  }

  if (isLoading) {
    return (
      <View style={styles.centerContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  // Already connected
  if (profile) {
    return (
      <View style={styles.container}>
        <View style={styles.connectedWrap}>
          <View style={styles.connectedIconCircle}>
            <Ionicons name="checkmark" size={36} color={colors.success} />
          </View>
          <Text style={styles.connectedLabel}>{t('recommendations.connected')}</Text>
          <Text style={styles.connectedUsername}>@{profile.username}</Text>
          {profile.linked_at && (
            <Text style={styles.syncedText}>
              {t('recommendations.linkedOn')}: {new Date(profile.linked_at).toLocaleDateString()}
            </Text>
          )}
          <Button
            label={t('recommendations.disconnectUntappd')}
            icon="unlink"
            variant="danger"
            onPress={handleDisconnect}
            loading={isSubmitting}
            style={styles.disconnectButton}
          />
        </View>
      </View>
    );
  }

  // Connect form
  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        keyboardShouldPersistTaps="handled"
      >
        {/* Hero */}
        <View style={styles.hero}>
          <View style={styles.heroIconCircle}>
            <Ionicons name="beer" size={34} color={colors.primary} />
          </View>
          <Text style={styles.heroTitle}>{t('recommendations.connectUntappdTitle')}</Text>
          <Text style={styles.heroText}>{t('recommendations.connectUntappdDescription')}</Text>
        </View>

        {/* Benefits */}
        <Card style={styles.benefitsCard}>
          <Text style={styles.benefitsTitle}>{t('recommendations.benefits')}</Text>
          <View style={styles.benefit}>
            <Ionicons name="analytics" size={18} color={colors.primary} />
            <Text style={styles.benefitText}>{t('recommendations.benefit1')}</Text>
          </View>
          <View style={styles.benefit}>
            <Ionicons name="star" size={18} color={colors.primary} />
            <Text style={styles.benefitText}>{t('recommendations.benefit2')}</Text>
          </View>
          <View style={[styles.benefit, styles.benefitLast]}>
            <Ionicons name="thumbs-up" size={18} color={colors.primary} />
            <Text style={styles.benefitText}>{t('recommendations.benefit3')}</Text>
          </View>
        </Card>

        {/* Form */}
        <View style={styles.form}>
          <Text style={styles.formLabel}>{t('recommendations.untappdUsername')}</Text>
          <View style={styles.inputContainer}>
            <Text style={styles.inputPrefix}>@</Text>
            <TextInput
              style={styles.input}
              value={username}
              onChangeText={setUsername}
              placeholder={t('recommendations.usernamePlaceholder')}
              placeholderTextColor={colors.textMuted}
              autoCapitalize="none"
              autoCorrect={false}
              editable={!isSubmitting}
            />
          </View>
          {error ? <Text style={styles.errorText}>{error}</Text> : null}

          <Button
            label={t('recommendations.connect')}
            icon="link"
            onPress={handleConnect}
            loading={isSubmitting}
            style={styles.connectButton}
          />
        </View>

        {/* Note */}
        <Text style={styles.noteText}>{t('recommendations.publicProfileNote')}</Text>

        {/* Link to Untappd */}
        <Pressable
          style={({ pressed }) => [styles.untappdLink, pressed && { opacity: 0.7 }]}
          onPress={openUntappd}
        >
          <Text style={styles.untappdLinkText}>{t('recommendations.dontHaveUntappd')}</Text>
          <Ionicons name="open-outline" size={15} color={colors.primary} />
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  centerContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  scrollContent: {
    padding: spacing.lg,
    maxWidth: 480,
    width: '100%',
    alignSelf: 'center',
  },

  // Hero
  hero: {
    alignItems: 'center',
    paddingVertical: spacing.lg,
  },
  heroIconCircle: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  heroTitle: {
    ...type.title,
    textAlign: 'center',
  },
  heroText: {
    fontFamily: fonts.serif,
    fontSize: 16,
    lineHeight: 23,
    color: colors.textMuted,
    marginTop: spacing.sm,
    textAlign: 'center',
    maxWidth: 320,
  },

  // Benefits
  benefitsCard: {
    marginTop: spacing.md,
  },
  benefitsTitle: {
    ...type.label,
    marginBottom: spacing.md,
  },
  benefit: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm + spacing.xs,
    marginBottom: spacing.sm + spacing.xs,
  },
  benefitLast: {
    marginBottom: 0,
  },
  benefitText: {
    fontFamily: fonts.serif,
    fontSize: 16,
    lineHeight: 21,
    color: colors.text,
    flex: 1,
  },

  // Form
  form: {
    marginTop: spacing.lg,
  },
  formLabel: {
    ...type.label,
    fontSize: 12,
    letterSpacing: 1.4,
    marginBottom: spacing.sm,
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.md,
    minHeight: 50,
  },
  inputPrefix: {
    paddingLeft: spacing.md,
    fontSize: 16,
    color: colors.textMuted,
  },
  input: {
    flex: 1,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
    fontSize: 16,
    color: colors.text,
  },
  errorText: {
    color: colors.error,
    fontSize: 13,
    marginTop: spacing.sm,
  },
  connectButton: {
    marginTop: spacing.md,
  },

  // Note
  noteText: {
    fontFamily: fonts.serifItalic,
    fontSize: 15,
    lineHeight: 20,
    color: colors.textMuted,
    textAlign: 'center',
    marginTop: spacing.lg,
    paddingHorizontal: spacing.md,
  },

  // Untappd Link
  untappdLink: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    padding: spacing.md,
    marginTop: spacing.sm,
    minHeight: 44,
  },
  untappdLinkText: {
    fontSize: 14,
    color: colors.primary,
    fontWeight: '500',
  },

  // Connected State
  connectedWrap: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.lg,
  },
  connectedIconCircle: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: colors.success + '14',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  connectedLabel: {
    ...type.label,
    color: colors.success,
  },
  connectedUsername: {
    fontFamily: fonts.headingBold,
    fontSize: 28,
    letterSpacing: 0.5,
    color: colors.primary,
    marginTop: spacing.xs,
  },
  syncedText: {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
  disconnectButton: {
    marginTop: spacing.xl,
    width: '100%',
    maxWidth: 360,
  },
});
