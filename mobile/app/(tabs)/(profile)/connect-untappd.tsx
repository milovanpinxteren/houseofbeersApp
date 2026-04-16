import { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
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
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
import { useEffect } from 'react';

export default function ConnectUntappdScreen() {
  const router = useRouter();
  const { language } = useLanguage();
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
      Alert.alert(
        t('common.success'),
        t('recommendations.untappdConnected'),
        [{ text: t('common.ok'), onPress: () => router.back() }]
      );
    } catch (err) {
      console.log('[ConnectUntappd] Connect error:', err);
      if (err instanceof Error) {
        if (err.message.includes('private') || err.message.includes('404')) {
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
              Alert.alert(
                t('common.success'),
                t('recommendations.untappdDisconnected')
              );
            } catch (err) {
              console.log('[ConnectUntappd] Disconnect error:', err);
              Alert.alert(t('common.error'), t('recommendations.disconnectError'));
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
          <View style={styles.connectedCard}>
            <View style={styles.connectedIcon}>
              <Ionicons name="checkmark-circle" size={48} color={colors.success} />
            </View>
            <Text style={styles.connectedTitle}>{t('recommendations.connected')}</Text>
            <Text style={styles.connectedUsername}>@{profile.username}</Text>
            {profile.last_synced && (
              <Text style={styles.syncedText}>
                {t('recommendations.lastSynced')}: {new Date(profile.last_synced).toLocaleDateString()}
              </Text>
            )}
          </View>

          <TouchableOpacity
            style={styles.disconnectButton}
            onPress={handleDisconnect}
            disabled={isSubmitting}
          >
            {isSubmitting ? (
              <ActivityIndicator size="small" color={colors.error} />
            ) : (
              <>
                <Ionicons name="unlink" size={20} color={colors.error} />
                <Text style={styles.disconnectButtonText}>
                  {t('recommendations.disconnectUntappd')}
                </Text>
              </>
            )}
          </TouchableOpacity>
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
          {/* Info Card */}
          <View style={styles.infoCard}>
            <Ionicons name="beer" size={48} color={colors.primary} />
            <Text style={styles.infoTitle}>{t('recommendations.connectUntappdTitle')}</Text>
            <Text style={styles.infoText}>{t('recommendations.connectUntappdDescription')}</Text>
          </View>

          {/* Benefits */}
          <View style={styles.benefitsCard}>
            <Text style={styles.benefitsTitle}>{t('recommendations.benefits')}</Text>
            <View style={styles.benefit}>
              <Ionicons name="analytics" size={20} color={colors.primary} />
              <Text style={styles.benefitText}>{t('recommendations.benefit1')}</Text>
            </View>
            <View style={styles.benefit}>
              <Ionicons name="star" size={20} color={colors.primary} />
              <Text style={styles.benefitText}>{t('recommendations.benefit2')}</Text>
            </View>
            <View style={styles.benefit}>
              <Ionicons name="thumbs-up" size={20} color={colors.primary} />
              <Text style={styles.benefitText}>{t('recommendations.benefit3')}</Text>
            </View>
          </View>

          {/* Form */}
          <View style={styles.formCard}>
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

            <TouchableOpacity
              style={[styles.connectButton, isSubmitting && styles.buttonDisabled]}
              onPress={handleConnect}
              disabled={isSubmitting}
            >
              {isSubmitting ? (
                <ActivityIndicator size="small" color={colors.background} />
              ) : (
                <>
                  <Ionicons name="link" size={20} color={colors.background} />
                  <Text style={styles.connectButtonText}>{t('recommendations.connect')}</Text>
                </>
              )}
            </TouchableOpacity>
          </View>

          {/* Note */}
          <View style={styles.noteCard}>
            <Ionicons name="information-circle" size={20} color={colors.textMuted} />
            <Text style={styles.noteText}>{t('recommendations.publicProfileNote')}</Text>
          </View>

          {/* Link to Untappd */}
          <TouchableOpacity style={styles.untappdLink} onPress={openUntappd}>
            <Text style={styles.untappdLinkText}>{t('recommendations.dontHaveUntappd')}</Text>
            <Ionicons name="open-outline" size={16} color={colors.primary} />
          </TouchableOpacity>
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
    padding: spacing.md,
  },

  // Info Card
  infoCard: {
    backgroundColor: colors.surface,
    padding: spacing.lg,
    borderRadius: borderRadius.lg,
    alignItems: 'center',
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.primary + '40',
  },
  infoTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
    marginTop: spacing.md,
    textAlign: 'center',
  },
  infoText: {
    fontSize: 14,
    color: colors.textMuted,
    marginTop: spacing.sm,
    textAlign: 'center',
    lineHeight: 20,
  },

  // Benefits
  benefitsCard: {
    backgroundColor: colors.surface,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  benefitsTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.md,
  },
  benefit: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  benefitText: {
    fontSize: 14,
    color: colors.text,
    flex: 1,
  },

  // Form
  formCard: {
    backgroundColor: colors.surface,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  formLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.sm,
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.tertiary + '50',
  },
  inputPrefix: {
    paddingLeft: spacing.md,
    fontSize: 16,
    color: colors.textMuted,
  },
  input: {
    flex: 1,
    padding: spacing.md,
    fontSize: 16,
    color: colors.text,
  },
  errorText: {
    color: colors.error,
    fontSize: 13,
    marginTop: spacing.sm,
  },
  connectButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primary,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    marginTop: spacing.md,
    gap: spacing.xs,
  },
  buttonDisabled: {
    opacity: 0.7,
  },
  connectButtonText: {
    color: colors.background,
    fontSize: 16,
    fontWeight: '600',
  },

  // Note
  noteCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    marginBottom: spacing.md,
    paddingHorizontal: spacing.sm,
  },
  noteText: {
    fontSize: 13,
    color: colors.textMuted,
    flex: 1,
    lineHeight: 18,
  },

  // Untappd Link
  untappdLink: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    padding: spacing.md,
  },
  untappdLinkText: {
    fontSize: 14,
    color: colors.primary,
  },

  // Connected State
  connectedCard: {
    backgroundColor: colors.surface,
    margin: spacing.md,
    padding: spacing.xl,
    borderRadius: borderRadius.lg,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.success + '40',
  },
  connectedIcon: {
    marginBottom: spacing.sm,
  },
  connectedTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
  },
  connectedUsername: {
    fontSize: 18,
    color: colors.primary,
    marginTop: spacing.xs,
    fontWeight: '600',
  },
  syncedText: {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
  disconnectButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.error + '40',
    gap: spacing.xs,
  },
  disconnectButtonText: {
    color: colors.error,
    fontSize: 16,
    fontWeight: '500',
  },
});
