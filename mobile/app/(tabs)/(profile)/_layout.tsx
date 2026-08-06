import { Stack, router } from 'expo-router';
import { Platform, Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, fonts } from '../../../src/theme/colors';
import { safeOrigin } from '../../../src/navigation/origin';

// Last-resort back target when there is no history and no recorded origin
// (e.g. a fresh deep link straight into this screen).
const FALLBACK: Record<string, string> = {
  orders: '/(tabs)/profile',
  'connect-untappd': '/(tabs)/profile',
  recommendations: '/(tabs)/ontdek',
  'taste-profile': '/(tabs)/ontdek',
  favorites: '/(tabs)/ontdek',
  'random-beer': '/(tabs)/ontdek',
  sixpack: '/(tabs)/ontdek',
};

function BackButton({ navigation, route }: { navigation: any; route: any }) {
  function handlePress() {
    // 1. Within-stack history: normal pop.
    const state = navigation.getState();
    if (state?.index > 0) {
      navigation.goBack();
      return;
    }
    // 2. Web: real browser history — keeps the arrow and the browser back
    //    button in agreement.
    if (Platform.OS === 'web' && router.canGoBack()) {
      router.back();
      return;
    }
    // 3. Recorded origin: return to the tab the user actually came from.
    const origin = safeOrigin(route?.params?.from);
    if (origin) {
      router.replace(origin as any);
      return;
    }
    // 4. Static fallback (deep links, cold starts).
    router.replace((FALLBACK[route?.name] || '/(tabs)') as any);
  }
  return (
    <Pressable
      onPress={handlePress}
      hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
      style={({ pressed }) => [
        { paddingHorizontal: Platform.OS === 'web' ? 12 : 4 },
        pressed && { opacity: 0.6 },
      ]}
    >
      <Ionicons name="chevron-back" size={26} color={colors.text} />
    </Pressable>
  );
}

export default function ProfileStackLayout() {
  const { language } = useLanguage();

  return (
    <Stack
      screenOptions={({ navigation, route }) => ({
        headerStyle: { backgroundColor: colors.background },
        headerShadowVisible: false,
        headerTintColor: colors.text,
        headerTitleStyle: {
          fontFamily: fonts.heading,
          fontSize: 17,
        },
        headerTitleAlign: 'center',
        headerBackVisible: false,
        headerLeft: () => <BackButton navigation={navigation} route={route} />,
      })}
    >
      <Stack.Screen name="recommendations" options={{ title: t('profile.recommendations') }} />
      <Stack.Screen name="taste-profile" options={{ title: t('profile.tasteProfile') }} />
      <Stack.Screen name="favorites" options={{ title: t('profile.favorites') }} />
      <Stack.Screen name="random-beer" options={{ title: t('randomBeer.title') }} />
      <Stack.Screen name="sixpack" options={{ title: t('sixpack.title') }} />
      <Stack.Screen name="orders" options={{ title: t('profile.orders') }} />
      <Stack.Screen name="connect-untappd" options={{ title: t('screenTitles.connectUntappd') }} />
    </Stack>
  );
}
