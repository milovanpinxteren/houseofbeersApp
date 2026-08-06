import { Stack, router } from 'expo-router';
import { Platform, Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, fonts } from '../../../src/theme/colors';
import { safeOrigin } from '../../../src/navigation/origin';

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
    router.replace('/(tabs)/community' as any);
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

export default function CommunityStackLayout() {
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
      <Stack.Screen name="new-post" options={{ title: t('screenTitles.newPost') }} />
      <Stack.Screen name="browse-groups" options={{ title: t('screenTitles.browseGroups') }} />
      <Stack.Screen name="new-suggestion" options={{ title: t('screenTitles.newSuggestion') }} />
      <Stack.Screen name="conversation" options={{ title: t('screenTitles.conversation') }} />
      <Stack.Screen name="group-chat" options={{ title: t('screenTitles.groupChat') }} />
      <Stack.Screen name="suggestion-detail" options={{ title: t('screenTitles.suggestionDetail') }} />
      <Stack.Screen name="members" options={{ title: t('screenTitles.members') }} />
      <Stack.Screen name="member-profile" options={{ title: t('screenTitles.memberProfile') }} />
      <Stack.Screen name="group-info" options={{ title: t('screenTitles.groupInfo') }} />
      <Stack.Screen name="post-comments" options={{ title: t('screenTitles.postComments') }} />
      <Stack.Screen name="livestream" options={{ title: t('screenTitles.livestream') }} />
    </Stack>
  );
}
