import { Tabs, router, useNavigation } from 'expo-router';
import { Image, StyleSheet, View, Text, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useLanguage } from '../../src/context/LanguageContext';
import { t } from '../../src/i18n';
import { colors, fonts } from '../../src/theme/colors';
import { useState, useCallback, useEffect } from 'react';
import { getFavorites } from '../../src/api/recommendations';
import { getUnreadCount } from '../../src/api/community';

function LogoTitle() {
  return (
    <TouchableOpacity onPress={() => router.replace('/(tabs)')} activeOpacity={0.7}>
      <Image
        source={require('../../assets/logo.png')}
        style={styles.logo}
        resizeMode="contain"
      />
    </TouchableOpacity>
  );
}

export default function TabsLayout() {
  const { language } = useLanguage();
  const navigation = useNavigation();
  const insets = useSafeAreaInsets();
  const [unreadCount, setUnreadCount] = useState(0);

  const refreshBadges = useCallback(() => {
    getUnreadCount()
      .then((data) => setUnreadCount(data.unread_count))
      .catch(() => {});
  }, []);

  useFocusEffect(refreshBadges);

  // Refresh badges on any navigation state change (e.g. returning from a chat),
  // so the unread count updates after conversations are read.
  useEffect(() => {
    const unsubscribe = navigation.addListener('state', refreshBadges);
    return unsubscribe;
  }, [navigation, refreshBadges]);

  return (
    <Tabs
      // Back (header arrow bubbling up, Android hardware back) returns to the
      // previously focused tab instead of the default "always first tab", so
      // sub-screens opened from e.g. Ontdek go back to Ontdek, not Home.
      backBehavior="history"
      screenOptions={{
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarStyle: {
          backgroundColor: colors.surfaceLow,
          borderTopColor: colors.border,
          // Grow by the device's bottom inset so the bar sits above the
          // system gesture/navigation area instead of underneath it.
          height: 60 + insets.bottom,
          paddingTop: 4,
          paddingBottom: 6 + insets.bottom,
        },
        // The bar is fixed-height, so labels must not follow the system font
        // scale: on phones with enlarged text the scaled label overflowed the
        // bar and its descenders (g, j, y) were clipped.
        tabBarAllowFontScaling: false,
        tabBarLabelStyle: {
          fontSize: 10,
          lineHeight: 13,
          fontWeight: '600',
        },
        headerStyle: { backgroundColor: colors.background },
        headerShadowVisible: false,
        headerTintColor: colors.text,
        headerTitleStyle: {
          fontFamily: fonts.heading,
          fontSize: 17,
          letterSpacing: 0.6,
        },
        headerTitleAlign: 'center',
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          headerTitle: () => <LogoTitle />,
          tabBarLabel: t('tabs.home'),
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="home" size={size} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="ontdek"
        options={{
          title: t('tabs.discover'),
          tabBarLabel: t('tabs.discover'),
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="compass" size={size} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="community"
        options={{
          title: t('tabs.community'),
          tabBarLabel: t('tabs.community'),
          tabBarIcon: ({ color, size }) => (
            <View>
              <Ionicons name="people" size={size} color={color} />
              {unreadCount > 0 && (
                <View style={styles.badge}>
                  <Text style={styles.badgeText}>
                    {unreadCount > 9 ? '9+' : unreadCount}
                  </Text>
                </View>
              )}
            </View>
          ),
        }}
      />
      <Tabs.Screen
        name="loyalty"
        options={{
          title: t('tabs.loyalty'),
          tabBarLabel: t('tabs.loyalty'),
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="star" size={size} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: t('tabs.profile'),
          tabBarLabel: t('tabs.profile'),
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="person" size={size} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="favorites"
        options={{
          href: null,
          headerShown: false,
        }}
      />
      <Tabs.Screen
        name="(profile)"
        options={{
          href: null,
          headerShown: false,
          // Trim the nested stack when leaving; together with the stale-stack
          // collapse in src/navigation/subStack.tsx this keeps back from ever
          // landing on a screen left over from an earlier visit.
          popToTopOnBlur: true,
        }}
      />
      <Tabs.Screen
        name="(community)"
        options={{
          href: null,
          headerShown: false,
          popToTopOnBlur: true,
        }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  logo: {
    height: 30,
    width: 124,
  },
  badge: {
    position: 'absolute',
    right: -6,
    top: -3,
    backgroundColor: colors.error,
    borderRadius: 8,
    minWidth: 16,
    height: 16,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 4,
  },
  badgeText: {
    color: '#fff',
    fontSize: 10,
    fontWeight: '700',
  },
});
