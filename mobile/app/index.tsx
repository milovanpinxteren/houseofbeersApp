import { useEffect, useState } from 'react';
import { Redirect } from 'expo-router';
import { View, Image, ActivityIndicator, StyleSheet } from 'react-native';
import { useAuth } from '../src/context/AuthContext';
import { ensureSignupCodeCaptured, getStoredSignupCode } from '../src/utils/signupCode';
import { colors, spacing } from '../src/theme/colors';

// Branded boot screen: shown only during the auth check, styled like the
// native splash so app start feels like one continuous screen.
export default function Index() {
  const { isLoading, isAuthenticated } = useAuth();

  // null = not looked yet. A flyer QR (?ref=CODE) means this visitor came to
  // sign up, so send them to the register screen with the offer already on
  // it rather than to login, where they would have to find it themselves.
  // This is also the one path that behaves identically on iOS and Android:
  // register in the browser first, install the PWA afterwards.
  const [signupCode, setSignupCode] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    ensureSignupCodeCaptured()
      .then(getStoredSignupCode)
      .then((code) => {
        if (!cancelled) setSignupCode(code);
      })
      .catch(() => {
        // Storage unavailable: fall through to the normal launch.
        if (!cancelled) setSignupCode('');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (isLoading || signupCode === null) {
    return (
      <View style={styles.container}>
        <Image
          source={require('../assets/logo.png')}
          style={styles.logo}
          resizeMode="contain"
        />
        <ActivityIndicator size="small" color={colors.primary} style={styles.spinner} />
      </View>
    );
  }

  if (isAuthenticated) {
    return <Redirect href="/(tabs)" />;
  }

  // No code: exactly the launch this app has always had.
  return <Redirect href={signupCode ? '/(auth)/register' : '/(auth)/login'} />;
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  logo: {
    width: 140,
    height: 140,
  },
  spinner: {
    marginTop: spacing.lg,
  },
});
