import { Stack } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import {
  subStackScreenOptions,
  useSubStackScreenListeners,
} from '../../../src/navigation/subStack';

// Owning tab root, used only when there is no navigation history at all
// (e.g. a fresh deep link straight into a sub-screen).
const FALLBACK: Record<string, string> = {
  orders: '/(tabs)/profile',
  'connect-untappd': '/(tabs)/profile',
  recommendations: '/(tabs)/ontdek',
  'taste-profile': '/(tabs)/ontdek',
  favorites: '/(tabs)/ontdek',
  'random-beer': '/(tabs)/ontdek',
  sixpack: '/(tabs)/ontdek',
  'app-shop': '/(tabs)/ontdek',
  'raffle/[id]': '/(tabs)/loyalty',
};

export default function ProfileStackLayout() {
  const { language } = useLanguage();
  const screenListeners = useSubStackScreenListeners();

  return (
    <Stack
      screenOptions={subStackScreenOptions((name) => FALLBACK[name] || '/(tabs)')}
      screenListeners={screenListeners}
    >
      <Stack.Screen name="recommendations" options={{ title: t('profile.recommendations') }} />
      <Stack.Screen name="taste-profile" options={{ title: t('profile.tasteProfile') }} />
      <Stack.Screen name="favorites" options={{ title: t('profile.favorites') }} />
      <Stack.Screen name="random-beer" options={{ title: t('randomBeer.title') }} />
      <Stack.Screen name="sixpack" options={{ title: t('sixpack.title') }} />
      <Stack.Screen name="orders" options={{ title: t('profile.orders') }} />
      <Stack.Screen name="connect-untappd" options={{ title: t('screenTitles.connectUntappd') }} />
      <Stack.Screen name="raffle/[id]" options={{ title: t('raffle.screenTitle') }} />
    </Stack>
  );
}
