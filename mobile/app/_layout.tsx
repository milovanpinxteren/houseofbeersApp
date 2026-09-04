import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { View, ActivityIndicator } from 'react-native';
import { useFonts } from 'expo-font';
import {
  Oswald_400Regular,
  Oswald_500Medium,
  Oswald_600SemiBold,
} from '@expo-google-fonts/oswald';
import {
  CrimsonText_400Regular,
  CrimsonText_400Regular_Italic,
  CrimsonText_600SemiBold,
} from '@expo-google-fonts/crimson-text';
import { AuthProvider } from '../src/context/AuthContext';
import { LanguageProvider } from '../src/context/LanguageContext';
import { ToastProvider } from '../src/components/ui/Toast';
import { ScreenTracker } from '../src/components/ScreenTracker';
import { SignupCodeNotice } from '../src/components/SignupCodeNotice';
import { useSignupCodeCapture } from '../src/utils/signupCode';
import { colors } from '../src/theme/colors';

export default function RootLayout() {
  // Flyer QR: grab ?ref=CODE before anything else. The visitor has no account
  // yet, so this has to happen outside (and ahead of) the auth flow.
  useSignupCodeCapture();

  const [fontsLoaded] = useFonts({
    Oswald_400Regular,
    Oswald_500Medium,
    Oswald_600SemiBold,
    CrimsonText_400Regular,
    CrimsonText_400Regular_Italic,
    CrimsonText_600SemiBold,
  });

  if (!fontsLoaded) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  return (
    <LanguageProvider>
      <AuthProvider>
        <ToastProvider>
          <StatusBar style="light" />
          <ScreenTracker />
          <SignupCodeNotice />
          <Stack
            screenOptions={{
              headerStyle: { backgroundColor: colors.background },
              headerTintColor: colors.text,
              contentStyle: { backgroundColor: colors.background },
            }}
          >
            <Stack.Screen name="index" options={{ headerShown: false, title: 'House of Beers' }} />
            <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
            <Stack.Screen name="(auth)" options={{ headerShown: false }} />
            {/* Instant redirect into the (profile) sub-stack; no header flash */}
            <Stack.Screen name="raffle/[id]" options={{ headerShown: false }} />
            <Stack.Screen
              name="reset-password"
              options={{
                title: 'Reset Password',
                headerShown: true,
              }}
            />
          </Stack>
        </ToastProvider>
      </AuthProvider>
    </LanguageProvider>
  );
}
