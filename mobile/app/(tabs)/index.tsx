import { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Linking,
  ImageBackground,
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
import { getOrders } from '../../src/api/orders';
import IOSInstallPrompt from '../../src/components/IOSInstallPrompt';
import { RaffleSection } from '../../src/components/RaffleCard';
import { WHATSAPP_COMMUNITY_URL } from '../../src/constants/community';

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
  // Bumped on pull-to-refresh so the raffle section refetches along with the rest.
  const [raffleRefresh, setRaffleRefresh] = useState(0);
  // Live numbers for the Bestellingen card. Fetched OUTSIDE fetchData: the
  // orders endpoint does several Shopify round-trips, so it must never delay
  // the rest of Home — the card renders as a plain link until this arrives,
  // and stays one on failure.
  const [orderStats, setOrderStats] = useState<{
    ready: number;
    incoming: number;
    due: number;
  } | null>(null);

  const fetchOrderStats = useCallback(() => {
    if (!user?.shopify_customer_id) return;
    getOrders()
      .then((data) => {
        let ready = 0;
        let incoming = 0;
        for (const order of data.orders) {
          for (const item of order.line_items) {
            if (item.state === 'in_warehouse') ready += 1;
            if (item.state === 'incoming') incoming += 1;
          }
        }
        for (const draft of data.drafts) {
          for (const item of draft.line_items) {
            if (item.state === 'in_warehouse') ready += 1;
            if (item.state === 'incoming') incoming += 1;
          }
        }
        const due = data.drafts.reduce(
          (sum, draft) => sum + (parseFloat(draft.total_price) || 0),
          0
        );
        setOrderStats({ ready, incoming, due });
      })
      .catch(() => {});
  }, [user?.shopify_customer_id]);

  useEffect(() => {
    fetchOrderStats();
  }, [fetchOrderStats]);

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
    setRaffleRefresh((k) => k + 1);
    fetchOrderStats();
    await fetchData();
    setRefreshing(false);
  }, [fetchData, fetchOrderStats]);

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
      {/* Brand hero: the shop interior from houseofbeers.nl with the
          greeting overlaid — the webshop's welcome, in app form. */}
      <ImageBackground
        source={require('../../assets/hero-shop.jpg')}
        style={styles.hero}
        imageStyle={styles.heroImage}
        resizeMode="cover"
      >
        <View style={styles.heroOverlay} />
        <View style={styles.heroContent}>
          <View style={styles.heroChip}>
            <Ionicons name="beer-outline" size={12} color={colors.primary} />
            <Text style={styles.heroChipText}>{t('home.tagline')}</Text>
          </View>
          <Text style={styles.greeting}>
            {t('home.welcome')}{user?.first_name ? `, ${user.first_name}` : ''}
          </Text>
        </View>
      </ImageBackground>

      {/* The webshop's brand stats strip */}
      <View style={styles.statsRow}>
        <View style={styles.statItem}>
          <Text style={styles.statValue}>2500+</Text>
          <Text style={styles.statLabel}>{t('home.statBeers')}</Text>
        </View>
        <View style={styles.statDivider} />
        <View style={styles.statItem}>
          <Text style={styles.statValue}>12°C</Text>
          <Text style={styles.statLabel}>{t('home.statStorage')}</Text>
        </View>
        <View style={styles.statDivider} />
        <View style={styles.statItem}>
          <Text style={styles.statValue}>4.6★</Text>
          <Text style={styles.statLabel}>Trustpilot</Text>
        </View>
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

          {/* Only the "your draw happened, watch the reveal" alert — Home
              stays calm; open raffles live on Loyalty, acties on Ontdek */}
          <RaffleSection language={language} refreshSignal={raffleRefresh} variant="alert" />

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

          {/* Always-visible navigation so the page never feels empty */}
          <SectionHeader title={t('home.forYou')} />

          {/* Bestellingen first: "what do you have of mine and what do I owe"
              is the #1 customer question — Home leads straight to the answer.
              The summary line and amount fill in when the (slow) orders
              fetch lands; until then the card is a plain link. */}
          <Card
            variant="accent"
            onPress={() => router.push('/(profile)/orders' as any)}
            style={styles.navCard}
          >
            <View style={styles.navIconWrap}>
              <Ionicons name="cube-outline" size={24} color={colors.primary} />
            </View>
            <View style={styles.navText}>
              <Text style={styles.navTitle}>{t('tabs.orders')}</Text>
              <Text style={styles.navSubtitle}>
                {orderStats && orderStats.ready + orderStats.incoming > 0
                  ? t('home.ordersSummary', {
                      ready: orderStats.ready,
                      incoming: orderStats.incoming,
                    })
                  : t('home.ordersHint')}
              </Text>
            </View>
            {orderStats && orderStats.due > 0 ? (
              <View style={styles.duePill}>
                <Text style={styles.duePillText}>
                  {new Intl.NumberFormat(language === 'nl' ? 'nl-NL' : 'en-US', {
                    style: 'currency',
                    currency: 'EUR',
                  }).format(orderStats.due)}
                </Text>
              </View>
            ) : null}
            <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
          </Card>

          {/* The remaining shortcuts as a compact 2×2 tile grid — they only
              echo the tab bar, so they earn less space than they used to. */}
          <View style={styles.tileGrid}>
            <Card onPress={() => router.push('/(tabs)/loyalty' as any)} style={styles.tile}>
              <View style={styles.tileTop}>
                <View style={styles.tileIconWrap}>
                  <Ionicons name="star" size={20} color={colors.primary} />
                </View>
                {loyalty ? (
                  <View style={styles.pointsPill}>
                    <Text style={styles.pointsPillText}>{loyalty.balance}</Text>
                  </View>
                ) : null}
              </View>
              <Text style={styles.tileTitle}>{t('home.yourPoints')}</Text>
            </Card>

            <Card onPress={() => router.push('/(tabs)/ontdek' as any)} style={styles.tile}>
              <View style={styles.tileTop}>
                <View style={styles.tileIconWrap}>
                  <Ionicons name="compass" size={20} color={colors.primary} />
                </View>
              </View>
              <Text style={styles.tileTitle}>{t('tabs.discover')}</Text>
            </Card>

            <Card onPress={() => router.push('/(tabs)/community' as any)} style={styles.tile}>
              <View style={styles.tileTop}>
                <View style={styles.tileIconWrap}>
                  <Ionicons name="people" size={20} color={colors.primary} />
                </View>
              </View>
              <Text style={styles.tileTitle}>{t('tabs.community')}</Text>
            </Card>

            <Card onPress={() => Linking.openURL(WHATSAPP_COMMUNITY_URL)} style={styles.tile}>
              <View style={styles.tileTop}>
                <View style={styles.tileIconWrap}>
                  <Ionicons name="logo-whatsapp" size={20} color={colors.primary} />
                </View>
                <Ionicons name="open-outline" size={14} color={colors.textMuted} />
              </View>
              <Text style={styles.tileTitle}>{t('home.whatsapp')}</Text>
            </Card>
          </View>
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  hero: {
    // Explicit width: on web an ImageBackground otherwise shrinks to the
    // image's intrinsic pixel width instead of filling the column.
    width: '100%',
    height: 180,
    marginTop: spacing.md,
    borderRadius: borderRadius.lg,
    overflow: 'hidden',
    justifyContent: 'flex-end',
  },
  heroImage: {
    borderRadius: borderRadius.lg,
  },
  heroOverlay: {
    ...StyleSheet.absoluteFillObject,
    // No gradient dependency: one warm scrim + text shadows carry legibility.
    backgroundColor: 'rgba(12, 10, 8, 0.42)',
  },
  heroContent: {
    padding: spacing.md,
    gap: spacing.sm,
  },
  heroChip: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: 'rgba(12, 10, 8, 0.55)',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderStrong,
    borderRadius: borderRadius.pill,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  heroChipText: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 1.4,
    textTransform: 'uppercase',
    color: colors.primary,
  },
  greeting: {
    ...type.display,
    textShadowColor: 'rgba(0, 0, 0, 0.6)',
    textShadowOffset: { width: 0, height: 1 },
    textShadowRadius: 6,
  },
  statsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.sm + spacing.xs,
    paddingHorizontal: spacing.sm,
    marginBottom: spacing.xs,
  },
  statItem: {
    flex: 1,
    alignItems: 'center',
  },
  statValue: {
    fontFamily: fonts.headingBold,
    fontSize: 17,
    letterSpacing: 0.4,
    color: colors.primary,
  },
  statLabel: {
    fontFamily: fonts.serif,
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 1,
  },
  statDivider: {
    width: StyleSheet.hairlineWidth,
    height: 26,
    backgroundColor: colors.borderStrong,
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
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  pointsPillText: {
    fontFamily: fonts.headingBold,
    fontSize: 14,
    color: colors.background,
  },
  duePill: {
    backgroundColor: colors.warning + '1f',
    borderRadius: borderRadius.pill,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  duePillText: {
    fontFamily: fonts.headingBold,
    fontSize: 13,
    letterSpacing: 0.3,
    color: colors.warning,
  },
  tileGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  tile: {
    flexBasis: '47%',
    flexGrow: 1,
    marginBottom: 0,
  },
  tileTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: spacing.sm + spacing.xs,
  },
  tileIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  tileTitle: {
    fontFamily: fonts.heading,
    fontSize: 15,
    letterSpacing: 0.4,
    color: colors.text,
  },
});
