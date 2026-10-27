import { useEffect, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ScrollView } from 'react-native';
import { Link, router } from 'expo-router';
import { useAuth } from '../../src/context/AuthContext';
import { useLanguage } from '../../src/context/LanguageContext';
import { lookupSignupCode } from '../../src/api/auth';
import {
  clearStoredSignupCode,
  ensureSignupCodeCaptured,
  getStoredSignupCode,
  normalizeSignupCode,
} from '../../src/utils/signupCode';
import { t } from '../../src/i18n';
import { colors, spacing, borderRadius } from '../../src/theme/colors';

// Mirrors the backend rule, so the message and the server agree.
const PASSWORD_MIN_LENGTH = 8;

export default function RegisterScreen() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [signupCode, setSignupCode] = useState('');
  const [showCodeField, setShowCodeField] = useState(false);
  const [bonusPoints, setBonusPoints] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const { register } = useAuth();
  const { language } = useLanguage();

  // Pre-fill from the QR capture. The field stays hidden for everyone else:
  // registration is the app's most important funnel and an input almost
  // nobody can fill in is pure friction. It is still reachable by hand
  // because on iOS, adding the PWA to the home screen creates a separate
  // storage partition - a code scanned in Safari is gone in the installed
  // app, and the flyer prints the code so it can be retyped.
  useEffect(() => {
    // Await the capture first: arriving straight from a QR link, the code may
    // still be on its way into storage.
    ensureSignupCodeCaptured()
      .then(getStoredSignupCode)
      .then((stored) => {
        if (stored) {
          setSignupCode(stored);
          setShowCodeField(true);
        }
      });
  }, []);

  // Ask the backend what this code is worth, so we only ever promise a number
  // we will actually pay out. Debounced because the field is hand-typed.
  useEffect(() => {
    const code = normalizeSignupCode(signupCode);
    if (!code) {
      setBonusPoints(0);
      return;
    }

    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const info = await lookupSignupCode(code);
        if (!cancelled) setBonusPoints(info.valid ? info.points : 0);
      } catch {
        // Offline or backend hiccup: promise nothing. The code still travels
        // with the registration, so a valid one is honoured regardless.
        if (!cancelled) setBonusPoints(0);
      }
    }, 400);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [signupCode]);

  async function handleRegister() {
    setErrorMessage('');

    if (!email || !password || !confirmPassword) {
      setErrorMessage(t('auth.fillRequired'));
      return;
    }

    if (password !== confirmPassword) {
      setErrorMessage(t('auth.passwordMismatch'));
      return;
    }

    if (password.length < PASSWORD_MIN_LENGTH) {
      setErrorMessage(t('auth.passwordTooShort', { count: PASSWORD_MIN_LENGTH }));
      return;
    }

    setIsLoading(true);
    try {
      const code = normalizeSignupCode(signupCode);
      // Dropped BEFORE the request, not after: logging in flips
      // isAuthenticated, which wakes SignupCodeNotice. If the code were still
      // in storage at that moment it would toast "this code is for new
      // members" at the person who just used it. The code is already in this
      // component's state, so a failed attempt can still be retried.
      await clearStoredSignupCode();
      const result = await register(email, password, firstName, lastName, code);
      // The welcome bonus is reported by the register response only, so it
      // travels to the next screen as a param.
      router.replace({
        pathname: '/welcome',
        params: { points: String(result.signupBonusPoints) },
      } as any);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Registration failed';
      // The one failure worth translating: someone who already has an account
      // arriving from a flyer. The raw backend string names the field, which
      // reads like a form bug rather than "you are already a member".
      setErrorMessage(
        message.toLowerCase().includes('already exists')
          ? t('auth.emailTaken')
          : message
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <ScrollView contentContainerStyle={styles.scrollContainer}>
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.title}>House of Beers</Text>
          <Text style={styles.subtitle}>{t('auth.register')}</Text>
        </View>

        <View style={styles.form}>
          {errorMessage ? (
            <View style={styles.errorContainer}>
              <Text style={styles.errorText}>{errorMessage}</Text>
            </View>
          ) : null}

          <View style={styles.row}>
            <TextInput
              style={[styles.input, styles.halfInput]}
              placeholder={t('auth.firstName')}
              placeholderTextColor={colors.textMuted}
              value={firstName}
              onChangeText={setFirstName}
              autoComplete="given-name"
              autoCapitalize="words"
              returnKeyType="next"
            />
            <TextInput
              style={[styles.input, styles.halfInput]}
              placeholder={t('auth.lastName')}
              placeholderTextColor={colors.textMuted}
              value={lastName}
              onChangeText={setLastName}
              autoComplete="family-name"
              autoCapitalize="words"
              returnKeyType="next"
            />
          </View>

          <TextInput
            style={styles.input}
            placeholder={t('auth.email') + ' *'}
            placeholderTextColor={colors.textMuted}
            value={email}
            onChangeText={setEmail}
            keyboardType="email-address"
            autoCapitalize="none"
            autoComplete="email"
            autoCorrect={false}
            returnKeyType="next"
          />
          <TextInput
            style={styles.input}
            placeholder={t('auth.password') + ' *'}
            placeholderTextColor={colors.textMuted}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            autoComplete="new-password"
            autoCapitalize="none"
            returnKeyType="next"
          />
          <TextInput
            style={styles.input}
            placeholder={t('auth.confirmPassword') + ' *'}
            placeholderTextColor={colors.textMuted}
            value={confirmPassword}
            onChangeText={setConfirmPassword}
            secureTextEntry
            autoComplete="new-password"
            autoCapitalize="none"
            returnKeyType="done"
            onSubmitEditing={handleRegister}
          />

          {showCodeField ? (
            <View style={styles.codeField}>
              <TextInput
                style={styles.input}
                placeholder={t('auth.signupCode')}
                placeholderTextColor={colors.textMuted}
                value={signupCode}
                onChangeText={setSignupCode}
                autoCapitalize="characters"
                autoCorrect={false}
                autoFocus={!signupCode}
              />
              {bonusPoints > 0 ? (
                <Text style={styles.codeBonus}>
                  {t('auth.signupCodeBonus', { points: bonusPoints })}
                </Text>
              ) : (
                <Text style={styles.codeHint}>{t('auth.signupCodeHint')}</Text>
              )}
            </View>
          ) : (
            <TouchableOpacity onPress={() => setShowCodeField(true)}>
              <Text style={styles.codeReveal}>{t('auth.haveSignupCode')}</Text>
            </TouchableOpacity>
          )}

          <TouchableOpacity
            style={[styles.button, isLoading && styles.buttonDisabled]}
            onPress={handleRegister}
            disabled={isLoading}
          >
            <Text style={styles.buttonText}>
              {isLoading ? '...' : t('auth.signUp')}
            </Text>
          </TouchableOpacity>

          <Link href="/(auth)/login" asChild>
            <TouchableOpacity style={styles.linkButton}>
              <Text style={styles.linkText}>
                {t('auth.haveAccount')} <Text style={styles.linkHighlight}>{t('auth.signIn')}</Text>
              </Text>
            </TouchableOpacity>
          </Link>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scrollContainer: {
    flexGrow: 1,
    backgroundColor: colors.background,
  },
  container: {
    flex: 1,
    padding: spacing.lg,
    justifyContent: 'center',
    backgroundColor: colors.background,
    // Without a ceiling the form stretches the full window on the PWA: the
    // fields were 1473px wide on a desktop browser.
    width: '100%',
    maxWidth: 480,
    alignSelf: 'center',
  },
  header: {
    marginBottom: spacing.xl,
    alignItems: 'center',
  },
  title: {
    fontFamily: 'Oswald_600SemiBold',
    fontSize: 32,
    letterSpacing: 1,
    textTransform: 'uppercase',
    color: colors.primary,
    marginBottom: spacing.sm,
  },
  subtitle: {
    fontFamily: 'CrimsonText_400Regular_Italic',
    fontSize: 19,
    color: colors.textMuted,
  },
  form: {
    gap: spacing.md,
  },
  errorContainer: {
    backgroundColor: colors.error + '20',
    borderWidth: 1,
    borderColor: colors.error,
    borderRadius: borderRadius.md,
    padding: spacing.md,
  },
  errorText: {
    color: colors.error,
    fontSize: 14,
    textAlign: 'center',
  },
  row: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  input: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    fontSize: 16,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
  },
  halfInput: {
    flex: 1,
    // On web a TextInput is a DOM <input>, which carries an intrinsic width of
    // roughly 214px. Flex items default to min-width:auto, so the pair refuses
    // to shrink below ~445px and the second field hangs off a phone screen.
    // Native is unaffected, which is why this only ever showed up in the PWA.
    minWidth: 0,
  },
  codeField: {
    gap: spacing.xs,
  },
  codeHint: {
    color: colors.textMuted,
    fontSize: 12,
    paddingHorizontal: spacing.xs,
  },
  codeReveal: {
    color: colors.textMuted,
    fontSize: 13,
    paddingHorizontal: spacing.xs,
    textDecorationLine: 'underline',
  },
  codeBonus: {
    color: colors.primary,
    fontFamily: 'Oswald_500Medium',
    fontSize: 14,
    letterSpacing: 0.5,
    paddingHorizontal: spacing.xs,
  },
  button: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    alignItems: 'center',
    marginTop: spacing.sm,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: colors.background,
    fontSize: 16,
    fontWeight: '600',
  },
  linkButton: {
    alignItems: 'center',
    marginTop: spacing.md,
  },
  linkText: {
    color: colors.textMuted,
    fontSize: 14,
  },
  linkHighlight: {
    color: colors.primary,
    fontWeight: '600',
  },
});
