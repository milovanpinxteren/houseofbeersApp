import { useEffect, useRef } from 'react';
import { Platform, Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { CommonActions } from '@react-navigation/native';
import { router, useNavigation } from 'expo-router';
import { colors, fonts } from '../theme/colors';

/**
 * One navigation model for the hidden sub-screen stacks ((profile) and
 * (community)) that live behind the tab bar:
 *
 * - Back is always ONE real step back: pop the stack when it has in-stack
 *   history, otherwise return to the previously focused tab. The Tabs
 *   navigator uses backBehavior="history", so a plain GO_BACK bubbles from
 *   the stack to the tab history and lands on the tab the user actually came
 *   from — never a hard-coded home.
 * - Android hardware back dispatches the same GO_BACK, so the arrow and the
 *   hardware button always agree.
 * - Only when there is no history at all (deep link / cold start) does the
 *   arrow jump to the screen's owning tab root.
 */

function BackButton({ navigation, fallback }: { navigation: any; fallback: string }) {
  function handlePress() {
    if (navigation.canGoBack()) {
      // Pops the stack if it has history; otherwise bubbles to the Tabs
      // navigator, whose history returns to the previously focused tab.
      navigation.goBack();
      return;
    }
    // No history anywhere (deep link, cold start): go to the owning tab root.
    router.replace(fallback as any);
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

/**
 * Shared header styling + back button for a sub-screen stack.
 * `fallbackFor` maps a route name to the tab root used when there is no
 * navigation history at all.
 */
export function subStackScreenOptions(fallbackFor: (routeName: string) => string) {
  return ({ navigation, route }: { navigation: any; route: any }) => ({
    headerStyle: { backgroundColor: colors.background },
    headerShadowVisible: false,
    headerTintColor: colors.text,
    headerTitleStyle: {
      fontFamily: fonts.heading,
      fontSize: 17,
    },
    headerTitleAlign: 'center' as const,
    // The native back button only renders when the stack itself has history;
    // sub-screens entered from a tab sit at stack index 0, so we always render
    // our own arrow.
    headerBackVisible: false,
    headerLeft: () => (
      <BackButton navigation={navigation} fallback={fallbackFor(route?.name)} />
    ),
  });
}

/**
 * Screen listeners that keep the shared stack honest across visits.
 *
 * The (profile)/(community) stacks are shared by several tabs, so without
 * cleanup a screen pushed from tab A lingers and becomes the screen "behind"
 * a later push from tab B — back would then land on a stale screen instead of
 * returning to tab B. When the stack is re-entered with a new push while it
 * still holds screens from an earlier visit, we collapse it to just the new
 * screen, so back exits to the previous tab.
 */
export function useSubStackScreenListeners() {
  // In a stack _layout this is the navigation of the stack's route inside the
  // Tabs navigator, so blur fires whenever the user leaves the stack.
  const tabNavigation = useNavigation();
  const stale = useRef(false);

  useEffect(() => {
    const unsubscribe = (tabNavigation as any).addListener('blur', () => {
      stale.current = true;
    });
    return unsubscribe;
  }, [tabNavigation]);

  return ({ navigation }: { navigation: any }) => ({
    focus: () => {
      if (!stale.current) return;
      stale.current = false;
      const state = navigation.getState();
      // A fresh push on top of residue from a previous visit: keep only the
      // newly focused screen. (Returning via back with no new push has a
      // single-route stack, which this leaves untouched.)
      if (state && state.routes.length > 1 && state.index === state.routes.length - 1) {
        navigation.dispatch(
          CommonActions.reset({ index: 0, routes: [state.routes[state.index]] })
        );
      }
    },
  });
}
