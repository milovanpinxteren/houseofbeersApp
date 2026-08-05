import { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Linking,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useAuth } from '../../src/context/AuthContext';
import { useLanguage } from '../../src/context/LanguageContext';
import { t } from '../../src/i18n';
import { colors, spacing, borderRadius, fonts, type } from '../../src/theme/colors';
import { Card, Screen, SectionHeader, SkeletonCard, Button } from '../../src/components/ui';
import {
  Notification,
  getNotifications,
  dismissNotification,
} from '../../src/api/notifications';
import { getEvents, joinEvent, Event } from '../../src/api/events';
import { getLoyaltySummary, LoyaltySummary } from '../../src/api/loyalty';
import IOSInstallPrompt from '../../src/components/IOSInstallPrompt';

const notificationIcons: Record<string, keyof typeof Ionicons.glyphMap> = {
  announcement: 'megaphone',
  promotion: 'pricetag',
  event: 'calendar',
  news: 'newspaper',
};

export default function HomeScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { language } = useLanguage();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [events, setEvents] = useState<Event[]>([]);
  const [loyalty, setLoyalty] = useState<LoyaltySummary | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [notifData, eventsData, loyaltyData] = await Promise.all([
        getNotifications(),
        getEvents(),
        getLoyaltySummary().catch(() => null),
      ]);
      setLoyalty(loyaltyData);
      setNotifications(notifData.filter((n) => !n.is_read));
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

    return (
      <Card key={notification.id} style={styles.notificationCard}>
        <View style={styles.notificationHeader}>
          <View style={styles.notificationTitleRow}>
            <Ionicons name={iconName} size={18} color={colors.primary} />
            <Text style={styles.notificationTitle}>{notification.title}</Text>
          </View>
          <TouchableOpacity
            onPress={() => handleDismiss(notification.id)}
            hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
          >
            <Ionicons name="close" size={18} color={colors.textMuted} />
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
            <Ionicons name="arrow-forward" size={13} color={colors.primary} />
          </TouchableOpacity>
        ) : null}
      </Card>
    );
  };

  return (
    <Screen refreshing={refreshing} onRefresh={onRefresh}>
      {/* Editorial greeting */}
      <View style={styles.header}>
        <Text style={styles.greeting}>
          {t('home.welcome')}{user?.first_name ? `, ${user.first_name}` : ''}
        </Text>
        <Text style={styles.tagline}>{t('home.tagline')}</Text>
      </View>

      <IOSInstallPrompt />

      {loading ? (
        <View style={{ marginTop: spacing.lg }}>
          <SkeletonCard />
          <SkeletonCard />
        </View>
      ) : (
        <>
          {notifications.length > 0 && (
            <>
              <SectionHeader title={t('home.notifications')} />
              {notifications.map(renderNotification)}
            </>
          )}

          {/* Events */}
          {events.length > 0 && (
            <>
              <SectionHeader title={t('events.title')} />
              {events.map((evt) => (
                <Card key={evt.id} variant={evt.status === 'live' ? 'accent' : 'default'} style={styles.eventCard}>
                  <View style={styles.eventHeader}>
                    {evt.status === 'live' ? (
                      <View style={styles.liveBadge}>
                        <View style={styles.liveDot} />
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
                    <Button
                      label={t('events.joinLive')}
                      icon="play"
                      onPress={() =>
                        router.push({
                          pathname: '/(community)/livestream',
                          params: { eventId: evt.id },
                        } as any)
                      }
                      style={styles.eventButton}
                    />
                  ) : evt.is_joined ? (
                    <Button
                      label={t('events.rsvped')}
                      icon="checkmark"
                      variant="secondary"
                      onPress={() =>
                        router.push({
                          pathname: '/(community)/livestream',
                          params: { eventId: evt.id },
                        } as any)
                      }
                      style={styles.eventButton}
                    />
                  ) : (
                    <Button
                      label={t('events.rsvp')}
                      onPress={() => handleRSVP(evt.id)}
                      style={styles.eventButton}
                    />
                  )}
                </Card>
              ))}
            </>
          )}

          {/* Always-visible navigation cards so the page never feels empty */}
          <SectionHeader title={t('home.forYou')} />

          <Card variant="accent" onPress={() => router.push('/(tabs)/loyalty' as any)} style={styles.navCard}>
            <View style={styles.navIconWrap}>
              <Ionicons name="star" size={24} color={colors.primary} />
            </View>
            <View style={styles.navText}>
              <Text style={styles.navTitle}>{t('home.yourPoints')}</Text>
              <Text style={styles.navSubtitle}>{t('home.pointsHint')}</Text>
            </View>
            {loyalty ? (
              <View style={styles.pointsPill}>
                <Text style={styles.pointsPillText}>{loyalty.balance}</Text>
              </View>
            ) : null}
            <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
          </Card>

          <Card onPress={() => router.push('/(tabs)/ontdek' as any)} style={styles.navCard}>
            <View style={styles.navIconWrap}>
              <Ionicons name="compass" size={24} color={colors.primary} />
            </View>
            <View style={styles.navText}>
              <Text style={styles.navTitle}>{t('tabs.discover')}</Text>
              <Text style={styles.navSubtitle}>{t('discover.recommendationsSubtitle')}</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
          </Card>

          <Card onPress={() => router.push('/(tabs)/community' as any)} style={styles.navCard}>
            <View style={styles.navIconWrap}>
              <Ionicons name="people" size={24} color={colors.primary} />
            </View>
            <View style={styles.navText}>
              <Text style={styles.navTitle}>{t('tabs.community')}</Text>
              <Text style={styles.navSubtitle}>{t('home.communityHint')}</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
          </Card>
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {
    paddingTop: spacing.lg,
    paddingBottom: spacing.sm,
  },
  greeting: {
    ...type.display,
  },
  tagline: {
    fontFamily: fonts.serifItalic,
    fontSize: 17,
    color: colors.primary,
    marginTop: spacing.xs,
  },
  notificationCard: {
    marginBottom: spacing.sm,
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
    gap: spacing.sm,
  },
  notificationTitle: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.4,
    color: colors.text,
    flex: 1,
  },
  notificationMessage: {
    fontFamily: fonts.serif,
    fontSize: 15,
    color: colors.textMuted,
    lineHeight: 21,
  },
  notificationLink: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: spacing.sm,
    gap: spacing.xs,
  },
  notificationLinkText: {
    fontSize: 13,
    color: colors.primary,
    fontWeight: '600',
  },
  eventCard: {
    marginBottom: spacing.sm,
  },
  eventHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  liveBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: colors.live + '22',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: borderRadius.pill,
  },
  liveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.live,
  },
  liveBadgeText: {
    color: colors.live,
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.5,
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
    fontFamily: fonts.heading,
    fontSize: 17,
    letterSpacing: 0.4,
    color: colors.text,
    marginBottom: 4,
  },
  eventDescription: {
    fontFamily: fonts.serif,
    fontSize: 14,
    color: colors.textMuted,
    lineHeight: 20,
    marginBottom: spacing.sm,
  },
  eventButton: {
    marginTop: spacing.xs,
  },
  navCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.sm,
  },
  navIconWrap: {
    width: 46,
    height: 46,
    borderRadius: 14,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  navText: {
    flex: 1,
  },
  navTitle: {
    fontFamily: fonts.heading,
    fontSize: 16,
    letterSpacing: 0.4,
    color: colors.text,
  },
  navSubtitle: {
    fontFamily: fonts.serif,
    fontSize: 14,
    color: colors.textMuted,
    marginTop: 1,
  },
  pointsPill: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.pill,
    paddingHorizontal: 12,
    paddingVertical: 4,
  },
  pointsPillText: {
    fontFamily: fonts.headingBold,
    fontSize: 16,
    color: colors.background,
  },
});
