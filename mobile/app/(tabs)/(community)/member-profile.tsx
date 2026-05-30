import React, { useState, useEffect, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Image,
  ActivityIndicator, RefreshControl,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, router } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { useAuth } from '../../../src/context/AuthContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
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
    try {
      const conv = await getOrCreateConversation(userIdNum);
      router.push(`/(tabs)/(community)/conversation?conversationId=${conv.id}&name=${data?.profile.display_name_resolved}`);
    } catch {
      // silent
    }
  };

  if (isLoading) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (!data) {
    return (
      <View style={[styles.container, styles.center]}>
        <Ionicons name="person-outline" size={48} color={colors.textMuted} />
        <Text style={styles.emptyText}>Member not found</Text>
      </View>
    );
  }

  const { profile, posts, checkins, favorites } = data;

  return (
    <ScrollView
      style={styles.container}
      refreshControl={
        <RefreshControl
          refreshing={isRefreshing}
          onRefresh={() => { setIsRefreshing(true); loadProfile(); }}
          tintColor={colors.primary}
        />
      }
    >
      {/* Profile header */}
      <View style={styles.profileHeader}>
        <View style={styles.avatarLarge}>
          <Ionicons name="person" size={36} color={colors.textMuted} />
        </View>
        <Text style={styles.displayName}>{profile.display_name_resolved}</Text>
        {profile.bio ? <Text style={styles.bio}>{profile.bio}</Text> : null}
        <View style={styles.statsRow}>
          {profile.has_untappd && (
            <View style={styles.statBadge}>
              <Ionicons name="beer" size={14} color={colors.primary} />
              <Text style={styles.statBadgeText}>
                {profile.untappd_username ? `@${profile.untappd_username}` : 'Untappd'}
              </Text>
            </View>
          )}
          {(profile.favorite_count ?? 0) > 0 && (
            <View style={styles.stat}>
              <Text style={styles.statNumber}>{profile.favorite_count}</Text>
              <Text style={styles.statLabel}>{t('community.favorites')}</Text>
            </View>
          )}
          {(profile.checkin_count ?? 0) > 0 && (
            <View style={styles.stat}>
              <Text style={styles.statNumber}>{profile.checkin_count}</Text>
              <Text style={styles.statLabel}>{t('community.beersTried')}</Text>
            </View>
          )}
        </View>
        {!isOwnProfile && (
          <TouchableOpacity style={styles.messageBtn} onPress={handleMessage}>
            <Ionicons name="chatbubble" size={16} color={colors.background} />
            <Text style={styles.messageBtnText}>{t('community.sendMessage')}</Text>
          </TouchableOpacity>
        )}
      </View>

      {/* Checkins */}
      {checkins.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{t('community.recentCheckins')}</Text>
          {checkins.map((c: CachedCheckin, i: number) => (
            <View key={i} style={styles.checkinRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.checkinBeer}>{c.beer_title}</Text>
                <Text style={styles.checkinMeta}>
                  {[c.beer_vendor, c.beer_style].filter(Boolean).join(' · ')}
                </Text>
              </View>
              {c.user_rating != null && (
                <View style={styles.ratingBadge}>
                  <Ionicons name="star" size={10} color="#B8860B" />
                  <Text style={styles.ratingText}>{Number(c.user_rating).toFixed(1)}</Text>
                </View>
              )}
            </View>
          ))}
        </View>
      )}

      {/* Favorites */}
      {favorites.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{t('community.favorites')} ({favorites.length})</Text>
          {favorites.map((fav: MemberFavorite) => (
            <View key={fav.id} style={styles.checkinRow}>
              {fav.image_url ? (
                <Image source={{ uri: fav.image_url }} style={styles.favImage} />
              ) : null}
              <View style={{ flex: 1 }}>
                <Text style={styles.checkinBeer} numberOfLines={1}>{fav.title}</Text>
                <Text style={styles.checkinMeta}>
                  {[fav.vendor, fav.style].filter(Boolean).join(' · ')}
                </Text>
              </View>
              {fav.untappd_rating != null && (
                <View style={styles.ratingBadge}>
                  <Ionicons name="star" size={10} color="#B8860B" />
                  <Text style={styles.ratingText}>{Number(fav.untappd_rating).toFixed(1)}</Text>
                </View>
              )}
            </View>
          ))}
        </View>
      )}

      {/* Recent posts */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>{t('community.recentPosts')}</Text>
        {posts.length === 0 ? (
          <Text style={styles.emptyText}>{t('community.noPosts')}</Text>
        ) : (
          posts.map((post: Post) => (
            <View key={post.id} style={styles.miniPost}>
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
            </View>
          ))
        )}
      </View>

      <View style={{ height: spacing.xl }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  profileHeader: {
    alignItems: 'center',
    padding: spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.tertiary + '20',
  },
  avatarLarge: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.tertiary + '30',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  displayName: { color: colors.text, fontSize: 22, fontWeight: '700' },
  bio: { color: colors.textMuted, fontSize: 14, textAlign: 'center', marginTop: spacing.xs, paddingHorizontal: spacing.lg },
  statsRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, marginTop: spacing.md },
  statBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: colors.primary + '20',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
  },
  statBadgeText: { fontSize: 12, color: colors.primary, fontWeight: '600' },
  stat: { alignItems: 'center' },
  statNumber: { color: colors.text, fontSize: 18, fontWeight: '700' },
  statLabel: { color: colors.textMuted, fontSize: 11 },
  messageBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.lg,
    marginTop: spacing.md,
  },
  messageBtnText: { color: colors.background, fontSize: 14, fontWeight: '700' },
  section: { padding: spacing.md },
  sectionTitle: {
    color: colors.primary,
    fontSize: 16,
    fontWeight: '700',
    marginBottom: spacing.md,
  },
  checkinRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.sm,
    padding: spacing.sm,
    marginBottom: spacing.xs,
  },
  favImage: { width: 44, height: 44, borderRadius: 6, marginRight: spacing.sm },
  checkinBeer: { color: colors.text, fontSize: 14, fontWeight: '600' },
  checkinMeta: { color: colors.textMuted, fontSize: 12, marginTop: 2 },
  ratingBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
    backgroundColor: 'rgba(255, 215, 0, 0.2)',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  ratingText: { fontSize: 11, fontWeight: '700', color: '#B8860B' },
  miniPost: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.sm,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  miniPostContent: { color: colors.text, fontSize: 14, lineHeight: 20 },
  miniPostBeer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    padding: spacing.xs,
    marginTop: spacing.sm,
  },
  miniPostBeerImg: { width: 32, height: 32, borderRadius: 4 },
  miniPostBeerTitle: { color: colors.text, fontSize: 12, flex: 1 },
  miniPostMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginTop: spacing.sm,
  },
  miniPostMetaText: { color: colors.textMuted, fontSize: 12, marginRight: spacing.sm },
  emptyText: { color: colors.textMuted, fontSize: 14 },
});
