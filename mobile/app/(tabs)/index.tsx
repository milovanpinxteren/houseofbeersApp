import { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  TouchableOpacity,
  Linking,
  ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useAuth } from '../../src/context/AuthContext';
import { useLanguage } from '../../src/context/LanguageContext';
import { t } from '../../src/i18n';
import { colors, spacing, borderRadius } from '../../src/theme/colors';
import {
  Notification,
  getNotifications,
  dismissNotification,
} from '../../src/api/notifications';
import {
  getUntappdProfile,
  getFavorites,
  UntappdProfile,
} from '../../src/api/recommendations';

const notificationIcons: Record<string, keyof typeof Ionicons.glyphMap> = {
  announcement: 'megaphone',
  promotion: 'pricetag',
  event: 'calendar',
  news: 'newspaper',
};

const notificationColors: Record<string, string> = {
  announcement: colors.primary,
  promotion: '#e74c3c',
  event: '#9b59b6',
  news: '#3498db',
};

type IconName = React.ComponentProps<typeof Ionicons>['name'];

interface MenuItem {
  id: string;
  icon: IconName;
  label: string;
  subtitle?: string;
  route: string;
  badge?: number;
}

export default function HomeScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { language } = useLanguage();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [untappdProfile, setUntappdProfile] = useState<UntappdProfile | null>(null);
  const [favoritesCount, setFavoritesCount] = useState(0);

  const fetchData = useCallback(async () => {
    try {
      const [notifData, untappdData, favoritesData] = await Promise.all([
        getNotifications(),
        getUntappdProfile(),
        getFavorites(),
      ]);
      setNotifications(notifData.filter((n) => !n.is_read));
      setUntappdProfile(untappdData.untappd);
      setFavoritesCount(favoritesData.favorites.length);
    } catch (error) {
      console.error('Failed to fetch data:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchData();
    setRefreshing(false);
  }, [fetchData]);

  const menuItems: MenuItem[] = [
    {
      id: 'recommendations',
      icon: 'beer',
      label: t('profile.recommendations'),
      subtitle: untappdProfile
        ? `@${untappdProfile.username}`
        : t('profile.basedOnOrders'),
      route: '/(profile)/recommendations',
    },
    {
      id: 'taste-profile',
      icon: 'analytics',
      label: t('profile.tasteProfile'),
      subtitle: t('profile.tasteProfileSubtitle'),
      route: '/(profile)/taste-profile',
    },
    {
      id: 'favorites',
      icon: 'heart',
      label: t('profile.favorites'),
      subtitle: t('profile.favoritesSubtitle'),
      route: '/(profile)/favorites',
      badge: favoritesCount > 0 ? favoritesCount : undefined,
    },
    {
      id: 'orders',
      icon: 'receipt',
      label: t('profile.orders'),
      subtitle: user?.shopify_customer_id
        ? t('profile.viewOrderHistory')
        : t('profile.linkShopifyFirst'),
      route: '/(profile)/orders',
    },
  ];

  const handleDismiss = async (notificationId: number) => {
    try {
      await dismissNotification(notificationId);
      setNotifications((prev) => prev.filter((n) => n.id !== notificationId));
    } catch (error) {
      console.error('Failed to dismiss notification:', error);
    }
  };

  const handleLink = (url: string) => {
    if (url) {
      Linking.openURL(url);
    }
  };

  const renderNotification = (notification: Notification) => {
    const iconName = notificationIcons[notification.notification_type] || 'information-circle';
    const iconColor = notificationColors[notification.notification_type] || colors.primary;

    return (
      <View key={notification.id} style={styles.notificationCard}>
        <View style={styles.notificationHeader}>
          <View style={styles.notificationTitleRow}>
            <Ionicons name={iconName} size={20} color={iconColor} />
            <Text style={styles.notificationTitle}>{notification.title}</Text>
          </View>
          <TouchableOpacity
            onPress={() => handleDismiss(notification.id)}
            hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
          >
            <Ionicons name="close" size={20} color={colors.textMuted} />
          </TouchableOpacity>
        </View>
        <Text style={styles.notificationMessage}>{notification.message}</Text>
        {notification.link_url ? (
          <TouchableOpacity
            style={styles.notificationLink}
            onPress={() => handleLink(notification.link_url)}
          >
            <Text style={styles.notificationLinkText}>
              {notification.link_text || t('home.learnMore')}
            </Text>
            <Ionicons name="arrow-forward" size={14} color={colors.primary} />
          </TouchableOpacity>
        ) : null}
      </View>
    );
  };

  return (
    <ScrollView
      style={styles.scrollView}
      contentContainerStyle={styles.scrollContent}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.primary}
        />
      }
    >
      <View style={styles.header}>
        <Text style={styles.greeting}>
          {t('home.welcome')}{user?.first_name ? `, ${user.first_name}` : ''}!
        </Text>
        <Text style={styles.subtitle}>House of Beers</Text>
      </View>

      {loading ? (
        <ActivityIndicator size="large" color={colors.primary} style={styles.loader} />
      ) : (
        <>
          {notifications.length > 0 && (
            <View style={styles.notificationsSection}>
              <Text style={styles.sectionTitle}>{t('home.notifications')}</Text>
              {notifications.map(renderNotification)}
            </View>
          )}

          {/* Beer Journey Section */}
          <View style={styles.journeySection}>
            <Text style={styles.sectionTitle}>{t('profile.yourBeerJourney')}</Text>
            <View style={styles.menuCard}>
              {menuItems.map((item) => (
                <TouchableOpacity
                  key={item.id}
                  style={styles.menuItem}
                  onPress={() => router.push(item.route as any)}
                  activeOpacity={0.7}
                >
                  <View style={styles.menuIconContainer}>
                    <Ionicons name={item.icon} size={22} color={colors.primary} />
                  </View>
                  <View style={styles.menuContent}>
                    <Text style={styles.menuLabel}>{item.label}</Text>
                    {item.subtitle && (
                      <Text style={styles.menuSubtitle} numberOfLines={1}>
                        {item.subtitle}
                      </Text>
                    )}
                  </View>
                  {item.badge && (
                    <View style={styles.badge}>
                      <Text style={styles.badgeText}>{item.badge}</Text>
                    </View>
                  )}
                  <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
                </TouchableOpacity>
              ))}
            </View>
          </View>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scrollView: {
    flex: 1,
    backgroundColor: colors.background,
  },
  scrollContent: {
    flexGrow: 1,
    padding: spacing.lg,
  },
  header: {
    alignItems: 'center',
    paddingTop: spacing.xl,
    paddingBottom: spacing.md,
  },
  greeting: {
    fontSize: 28,
    fontWeight: '700',
    color: colors.text,
    marginBottom: spacing.sm,
  },
  subtitle: {
    fontSize: 20,
    color: colors.primary,
  },
  loader: {
    marginTop: spacing.xl,
  },
  notificationsSection: {
    marginTop: spacing.lg,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.md,
  },
  notificationCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
    borderLeftWidth: 3,
    borderLeftColor: colors.primary,
  },
  notificationHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  notificationTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  notificationTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text,
    marginLeft: spacing.sm,
    flex: 1,
  },
  notificationMessage: {
    fontSize: 14,
    color: colors.textMuted,
    lineHeight: 20,
  },
  notificationLink: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: spacing.sm,
  },
  notificationLinkText: {
    fontSize: 14,
    color: colors.primary,
    marginRight: spacing.xs,
  },
  // Beer Journey Section
  journeySection: {
    marginTop: spacing.lg,
  },
  menuCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.tertiary + '30',
    overflow: 'hidden',
  },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.tertiary + '20',
  },
  menuIconContainer: {
    width: 36,
    height: 36,
    borderRadius: 8,
    backgroundColor: colors.primary + '15',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: spacing.md,
  },
  menuContent: {
    flex: 1,
  },
  menuLabel: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text,
  },
  menuSubtitle: {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: 2,
  },
  badge: {
    backgroundColor: colors.primary,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
    marginRight: spacing.sm,
  },
  badgeText: {
    color: colors.background,
    fontSize: 12,
    fontWeight: '600',
  },
});
