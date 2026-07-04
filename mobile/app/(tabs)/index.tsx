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
import { getEvents, joinEvent, Event } from '../../src/api/events';
import IOSInstallPrompt from '../../src/components/IOSInstallPrompt';

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
  const [events, setEvents] = useState<Event[]>([]);

  const fetchData = useCallback(async () => {
    try {
      const [notifData, untappdData, favoritesData, eventsData] = await Promise.all([
        getNotifications(),
        getUntappdProfile(),
        getFavorites(),
        getEvents(),
      ]);
      setNotifications(notifData.filter((n) => !n.is_read));
      setUntappdProfile(untappdData.untappd);
      setFavoritesCount(favoritesData.favorites.length);
      // Show live first, then scheduled, hide ended
      const sorted = eventsData.events
        .filter((e) => e.status !== 'ended')
        .sort((a, b) => {
          if (a.status === 'live' && b.status !== 'live') return -1;
          if (b.status === 'live' && a.status !== 'live') return 1;
          return new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime();
        });
      setEvents(sorted);
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

  const handleRSVP = async (eventId: number) => {
    try {
      await joinEvent(eventId);
      setEvents((prev) =>
        prev.map((e) =>
          e.id === eventId ? { ...e, is_joined: true, viewer_count: e.viewer_count + 1 } : e
        )
      );
    } catch (error) {
      console.error('Failed to RSVP:', error);
    }
  };

  const formatEventDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString(language === 'nl' ? 'nl-NL' : 'en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
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

      <IOSInstallPrompt />

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

          {/* Events Section */}
          {events.length > 0 && (
            <View style={styles.eventsSection}>
              <Text style={styles.sectionTitle}>{t('events.title')}</Text>
              {events.map((evt) => (
                <View key={evt.id} style={styles.eventCard}>
                  <View style={styles.eventHeader}>
                    {evt.status === 'live' ? (
                      <View style={styles.liveBadge}>
                        <Text style={styles.liveBadgeText}>{t('events.liveNow')}</Text>
                      </View>
                    ) : (
                      <View style={styles.scheduledBadge}>
                        <Ionicons name="calendar" size={12} color={colors.primary} />
                        <Text style={styles.scheduledBadgeText}>
                          {formatEventDate(evt.scheduled_at)}
                        </Text>
                      </View>
                    )}
                    <Text style={styles.eventViewers}>
                      {evt.viewer_count} {t('events.going')}
                    </Text>
                  </View>
                  <Text style={styles.eventTitle}>{evt.title}</Text>
                  {evt.description ? (
                    <Text style={styles.eventDescription} numberOfLines={2}>
                      {evt.description}
                    </Text>
                  ) : null}
                  {evt.status === 'live' ? (
                    <TouchableOpacity
                      style={styles.eventButton}
                      onPress={() =>
                        router.push({
                          pathname: '/(community)/livestream',
                          params: { eventId: evt.id },
                        } as any)
                      }
                    >
                      <Ionicons name="play" size={16} color={colors.background} />
                      <Text style={styles.eventButtonText}>{t('events.joinLive')}</Text>
                    </TouchableOpacity>
                  ) : evt.is_joined ? (
                    <TouchableOpacity
                      style={[styles.eventButton, styles.eventButtonJoined]}
                      onPress={() =>
                        router.push({
                          pathname: '/(community)/livestream',
                          params: { eventId: evt.id },
                        } as any)
                      }
                    >
                      <Ionicons name="checkmark" size={16} color={colors.primary} />
                      <Text style={[styles.eventButtonText, styles.eventButtonTextJoined]}>
                        {t('events.rsvped')}
                      </Text>
                    </TouchableOpacity>
                  ) : (
                    <TouchableOpacity
                      style={styles.eventButton}
                      onPress={() => handleRSVP(evt.id)}
                    >
                      <Text style={styles.eventButtonText}>{t('events.rsvp')}</Text>
                    </TouchableOpacity>
                  )}
                </View>
              ))}
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
  // Events Section
  eventsSection: {
    marginTop: spacing.lg,
  },
  eventCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
    borderLeftWidth: 3,
    borderLeftColor: colors.primary,
  },
  eventHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  liveBadge: {
    backgroundColor: '#e74c3c',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
  },
  liveBadgeText: {
    color: '#fff',
    fontSize: 11,
    fontWeight: '700',
  },
  scheduledBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  scheduledBadgeText: {
    color: colors.primary,
    fontSize: 12,
  },
  eventViewers: {
    color: colors.textMuted,
    fontSize: 12,
  },
  eventTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '600',
    marginBottom: 4,
  },
  eventDescription: {
    color: colors.textMuted,
    fontSize: 13,
    lineHeight: 18,
    marginBottom: spacing.sm,
  },
  eventButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primary,
    paddingVertical: 8,
    borderRadius: borderRadius.sm,
    gap: 6,
    marginTop: spacing.xs,
  },
  eventButtonText: {
    color: colors.background,
    fontSize: 14,
    fontWeight: '600',
  },
  eventButtonJoined: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: colors.primary,
  },
  eventButtonTextJoined: {
    color: colors.primary,
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
