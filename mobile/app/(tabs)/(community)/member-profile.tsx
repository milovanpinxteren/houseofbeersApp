import React, { useState, useEffect, useCallback } from 'react';
import {
  View, Text, StyleSheet, Image,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, router } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { useAuth } from '../../../src/context/AuthContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius, fonts } from '../../../src/theme/colors';
import { Button, Card, EmptyState, Screen, SectionHeader, Skeleton, SkeletonCard, useToast } from '../../../src/components/ui';
import {
  getMemberProfile, getOrCreateConversation,
  MemberProfileResponse, Post, CachedCheckin, MemberFavorite,
} from '../../../src/api/community';

export default function MemberProfileScreen() {
  const { language } = useLanguage();
  const { user } = useAuth();
  const { userId } = useLocalSearchParams<{ userId: string }>();
  const [data, setData] = useState<MemberProfileResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isMessaging, setIsMessaging] = useState(false);
  const { showToast } = useToast();

  const userIdNum = parseInt(userId || '0', 10);
  const isOwnProfile = user?.id === userIdNum;

  const loadProfile = useCallback(async () => {
    if (!userIdNum) return;
    try {
      const result = await getMemberProfile(userIdNum);
      setData(result);
    } catch {
      // silent
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [userIdNum]);

  useEffect(() => { loadProfile(); }, [loadProfile]);

  const handleMessage = async () => {
    if (isMessaging) return;
    setIsMessaging(true);
    try {
      const conv = await getOrCreateConversation(userIdNum);
      router.push(`/(tabs)/(community)/conversation?conversationId=${conv.id}&name=${encodeURIComponent(data?.profile.display_name_resolved || '')}`);
    } catch {
      showToast(t('community.loadError'), 'error');
    } finally {
      setIsMessaging(false);
    }
  };

  if (isLoading) {
    return (
      <Screen scroll={false}>
        <View style={styles.skeletonHeader}>
          <Skeleton width={84} height={84} radius={42} />
          <Skeleton width={160} height={20} style={{ marginTop: spacing.md }} />
          <Skeleton width={220} height={13} style={{ marginTop: spacing.sm }} />
        </View>
        <SkeletonCard />
        <SkeletonCard />
      </Screen>
    );
  }

  if (!data) {
    return (
      <Screen scroll={false}>
        <View style={styles.centerFill}>
          <EmptyState
            icon="person-outline"
            title={t('community.memberNotFound')}
          />
        </View>
      </Screen>
    );
  }

  const { profile, posts, checkins, favorites } = data;

  return (
    <Screen
      refreshing={isRefreshing}
      onRefresh={() => { setIsRefreshing(true); loadProfile(); }}
    >
      {/* Profile header */}
      <View style={styles.profileHeader}>
        <View style={styles.avatarLarge}>
          <Ionicons name="person" size={38} color={colors.tertiary} />
        </View>
        <Text style={styles.displayName}>{profile.display_name_resolved}</Text>
        {profile.bio ? <Text style={styles.bio}>{profile.bio}</Text> : null}

        {profile.has_untappd && (
          <View style={styles.untappdBadge}>
            <Ionicons name="beer" size={13} color={colors.primary} />
            <Text style={styles.untappdBadgeText}>
              {profile.untappd_username ? `@${profile.untappd_username}` : 'Untappd'}
            </Text>
          </View>
        )}

        {((profile.favorite_count ?? 0) > 0 || (profile.checkin_count ?? 0) > 0) && (
          <View style={styles.statsRow}>
            {(profile.favorite_count ?? 0) > 0 && (
              <View style={styles.stat}>
                <Text style={styles.statNumber}>{profile.favorite_count}</Text>
                <Text style={styles.statLabel}>{t('community.favorites')}</Text>
              </View>
            )}
            {(profile.favorite_count ?? 0) > 0 && (profile.checkin_count ?? 0) > 0 && (
              <View style={styles.statDivider} />
            )}
            {(profile.checkin_count ?? 0) > 0 && (
              <View style={styles.stat}>
                <Text style={styles.statNumber}>{profile.checkin_count}</Text>
                <Text style={styles.statLabel}>{t('community.beersTried')}</Text>
              </View>
            )}
          </View>
        )}

        {!isOwnProfile && (
          <Button
            label={t('community.sendMessage')}
            onPress={handleMessage}
            loading={isMessaging}
            icon="chatbubble"
            style={styles.messageBtn}
          />
        )}
      </View>

      {/* Checkins */}
      {checkins.length > 0 && (
        <>
          <SectionHeader title={t('community.recentCheckins')} />
          <Card padded={false}>
            {checkins.map((c: CachedCheckin, i: number) => (
              <View key={i} style={[styles.beerRow, i > 0 && styles.beerRowDivider]}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.beerRowTitle}>{c.beer_title}</Text>
                  {[c.beer_vendor, c.beer_style].filter(Boolean).length > 0 && (
                    <Text style={styles.beerRowMeta}>
                      {[c.beer_vendor, c.beer_style].filter(Boolean).join(' · ')}
                    </Text>
                  )}
                </View>
                {c.user_rating != null && (
                  <View style={styles.ratingBadge}>
                    <Ionicons name="star" size={10} color={colors.warning} />
                    <Text style={styles.ratingText}>{Number(c.user_rating).toFixed(1)}</Text>
                  </View>
                )}
              </View>
            ))}
          </Card>
        </>
      )}

      {/* Favorites */}
      {favorites.length > 0 && (
        <>
          <SectionHeader title={`${t('community.favorites')} (${favorites.length})`} />
          <Card padded={false}>
            {favorites.map((fav: MemberFavorite, i: number) => (
              <View key={fav.id} style={[styles.beerRow, i > 0 && styles.beerRowDivider]}>
                {fav.image_url ? (
                  <Image source={{ uri: fav.image_url }} style={styles.favImage} />
                ) : (
                  <View style={styles.favImagePlaceholder}>
                    <Ionicons name="beer" size={18} color={colors.tertiary} />
                  </View>
                )}
                <View style={{ flex: 1 }}>
                  <Text style={styles.beerRowTitle} numberOfLines={1}>{fav.title}</Text>
                  {[fav.vendor, fav.style].filter(Boolean).length > 0 && (
                    <Text style={styles.beerRowMeta}>
                      {[fav.vendor, fav.style].filter(Boolean).join(' · ')}
                    </Text>
                  )}
                </View>
                {fav.untappd_rating != null && (
                  <View style={styles.ratingBadge}>
                    <Ionicons name="star" size={10} color={colors.warning} />
                    <Text style={styles.ratingText}>{Number(fav.untappd_rating).toFixed(1)}</Text>
                  </View>
                )}
              </View>
            ))}
          </Card>
        </>
      )}

      {/* Recent posts */}
      <SectionHeader title={t('community.recentPosts')} />
      {posts.length === 0 ? (
        <EmptyState icon="chatbubbles-outline" title={t('community.noPosts')} />
      ) : (
        posts.map((post: Post) => (
          <Card key={post.id} style={styles.miniPost}>
            <Text style={styles.miniPostContent} numberOfLines={3}>{post.content}</Text>
            {post.beer_title ? (
              <View style={styles.miniPostBeer}>
                {post.beer_image_url ? (
                  <Image source={{ uri: post.beer_image_url }} style={styles.miniPostBeerImg} />
                ) : null}
                <Text style={styles.miniPostBeerTitle} numberOfLines={1}>{post.beer_title}</Text>
              </View>
            ) : null}
            <View style={styles.miniPostMeta}>
              <Ionicons name="heart" size={12} color={colors.textMuted} />
              <Text style={styles.miniPostMetaText}>{post.like_count}</Text>
              <Ionicons name="chatbubble" size={12} color={colors.textMuted} />
              <Text style={styles.miniPostMetaText}>{post.comment_count}</Text>
            </View>
          </Card>
        ))
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  centerFill: { flex: 1, justifyContent: 'center' },
  skeletonHeader: { alignItems: 'center', paddingVertical: spacing.xl, marginBottom: spacing.md },

  profileHeader: {
    alignItems: 'center',
    paddingTop: spacing.lg,
    paddingBottom: spacing.sm,
  },
  avatarLarge: {
    width: 84,
    height: 84,
    borderRadius: 42,
    backgroundColor: colors.surfaceHigh,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  displayName: {
    fontFamily: fonts.headingBold,
    fontSize: 24,
    letterSpacing: 0.5,
    color: colors.text,
    textAlign: 'center',
  },
  bio: {
    fontFamily: fonts.serif,
    fontSize: 15,
    lineHeight: 21,
    color: colors.textMuted,
    textAlign: 'center',
    marginTop: spacing.xs,
    paddingHorizontal: spacing.lg,
    maxWidth: 320,
  },
  untappdBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: colors.primary + '16',
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: borderRadius.pill,
    marginTop: spacing.md,
  },
  untappdBadgeText: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 0.6,
    color: colors.primary,
  },
  statsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.lg,
    marginTop: spacing.md,
  },
  stat: { alignItems: 'center', minWidth: 64 },
  statNumber: { fontFamily: fonts.headingBold, fontSize: 22, letterSpacing: 0.5, color: colors.text },
  statLabel: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: colors.textMuted,
    marginTop: 2,
  },
  statDivider: { width: StyleSheet.hairlineWidth, height: 28, backgroundColor: colors.borderStrong },
  messageBtn: { marginTop: spacing.lg, alignSelf: 'stretch' },

  // Beer / check-in rows
  beerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
    minHeight: 52,
  },
  beerRowDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  beerRowTitle: { fontSize: 14, fontWeight: '500', color: colors.text },
  beerRowMeta: { color: colors.textMuted, fontSize: 12, marginTop: 2 },
  favImage: { width: 40, height: 40, borderRadius: borderRadius.sm },
  favImagePlaceholder: {
    width: 40,
    height: 40,
    borderRadius: borderRadius.sm,
    backgroundColor: colors.surfaceHigh,
    justifyContent: 'center',
    alignItems: 'center',
  },
  ratingBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: colors.warning + '20',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  ratingText: { fontFamily: fonts.headingBold, fontSize: 11, color: colors.warning },

  // Mini posts
  miniPost: { marginBottom: spacing.sm },
  miniPostContent: { fontFamily: fonts.serif, fontSize: 15, lineHeight: 21, color: colors.text },
  miniPostBeer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.md,
    padding: spacing.sm,
    marginTop: spacing.sm,
  },
  miniPostBeerImg: { width: 32, height: 32, borderRadius: borderRadius.sm },
  miniPostBeerTitle: { color: colors.text, fontSize: 12, flex: 1 },
  miniPostMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    marginTop: spacing.sm,
  },
  miniPostMetaText: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 0.4,
    color: colors.textMuted,
    marginRight: spacing.sm,
  },
});
