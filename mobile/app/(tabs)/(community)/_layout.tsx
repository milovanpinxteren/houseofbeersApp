import { Stack } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import {
  subStackScreenOptions,
  useSubStackScreenListeners,
} from '../../../src/navigation/subStack';

export default function CommunityStackLayout() {
  const { language } = useLanguage();
  const screenListeners = useSubStackScreenListeners();

  return (
    <Stack
      screenOptions={subStackScreenOptions(() => '/(tabs)/community')}
      screenListeners={screenListeners}
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
