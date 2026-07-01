import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity, Image, TextInput,
  RefreshControl, ActivityIndicator, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import { useLanguage } from '../../src/context/LanguageContext';
import { useAuth } from '../../src/context/AuthContext';
import { t } from '../../src/i18n';
import { colors, spacing, borderRadius } from '../../src/theme/colors';
import {
  getFeed, toggleLike, deletePost, getGroups, getChats,
  getSuggestions, toggleSuggestionVote, deleteSuggestion,
  Post, Group, ChatItem, Suggestion,
} from '../../src/api/community';

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return '<1m';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

const STATUS_COLORS: Record<string, string> = {
  open: colors.primary,
  planned: colors.warning,
  done: colors.success,
  declined: colors.textMuted,
};

// --- Post Card ---

function PostCard({ post, userId, onLike, onDelete, onComment }: {
  post: Post;
  userId: number;
  onLike: (id: number) => void;
  onDelete: (id: number) => void;
  onComment: (id: number) => void;
}) {
  const { language } = useLanguage();
  const isOwn = post.author.user_id === userId;

  return (
    <View style={styles.postCard}>
      <View style={styles.postHeader}>
        <TouchableOpacity
          style={styles.authorRow}
          onPress={() => router.push(`/(tabs)/(community)/member-profile?userId=${post.author.user_id}`)}
        >
          <View style={styles.avatarSm}>
            <Ionicons name="person" size={18} color={colors.textMuted} />
          </View>
          <View>
            <Text style={styles.authorName}>{post.author.display_name}</Text>
            <Text style={styles.postTime}>{timeAgo(post.created_at)}</Text>
          </View>
        </TouchableOpacity>
        {isOwn && (
          <TouchableOpacity onPress={() => onDelete(post.id)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
            <Ionicons name="trash-outline" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        )}
      </View>

      {post.post_type !== 'text' && (
        <View style={styles.postTypeBadge}>
          <Ionicons
            name={post.post_type === 'review' ? 'star' : 'share-social'}
            size={12}
            color={colors.primary}
          />
          <Text style={styles.postTypeText}>
            {t(`community.${post.post_type === 'review' ? 'shareReview' : 'shareBeer'}`)}
          </Text>
        </View>
      )}

      <Text style={styles.postContent}>{post.content}</Text>

      {post.beer_title ? (
        <View style={styles.beerCard}>
          {post.beer_image_url ? (
            <Image source={{ uri: post.beer_image_url }} style={styles.beerImage} />
          ) : null}
          <View style={styles.beerInfo}>
            <Text style={styles.beerTitle} numberOfLines={2}>{post.beer_title}</Text>
            {post.beer_vendor ? <Text style={styles.beerVendor}>{post.beer_vendor}</Text> : null}
            <View style={styles.beerMeta}>
              {post.beer_rating != null && (
                <View style={styles.ratingBadge}>
                  <Ionicons name="star" size={10} color="#B8860B" />
                  <Text style={styles.ratingText}>{Number(post.beer_rating).toFixed(1)}</Text>
                </View>
              )}
              {post.beer_style ? <Text style={styles.beerStyle}>{post.beer_style}</Text> : null}
            </View>
          </View>
        </View>
      ) : null}

      <View style={styles.postActions}>
        <TouchableOpacity style={styles.actionBtn} onPress={() => onLike(post.id)}>
          <Ionicons name={post.is_liked ? 'heart' : 'heart-outline'} size={20} color={post.is_liked ? colors.error : colors.textMuted} />
          <Text style={[styles.actionText, post.is_liked && { color: colors.error }]}>{post.like_count}</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionBtn} onPress={() => onComment(post.id)}>
          <Ionicons name="chatbubble-outline" size={18} color={colors.textMuted} />
          <Text style={styles.actionText}>{post.comment_count}</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

// --- Feed Tab ---

function FeedTab({ userId }: { userId: number }) {
  const [posts, setPosts] = useState<Post[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const loadFeed = useCallback(async () => {
    try {
      const data = await getFeed();
      setPosts(data.results);
      setNextCursor(data.next);
    } catch {
      Alert.alert(t('error'), t('community.loadError'));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const data = await getFeed(nextCursor);
      setPosts(prev => [...prev, ...data.results]);
      setNextCursor(data.next);
    } catch {} finally { setLoadingMore(false); }
  }, [nextCursor, loadingMore]);

  useFocusEffect(
    useCallback(() => { loadFeed(); }, [loadFeed])
  );

  const handleLike = useCallback(async (postId: number) => {
    try {
      const result = await toggleLike(postId);
      setPosts(prev => prev.map(p => p.id === postId ? { ...p, is_liked: result.liked, like_count: result.like_count } : p));
    } catch {}
  }, []);

  const handleDelete = useCallback((postId: number) => {
    Alert.alert(t('community.deletePost'), t('community.deletePostConfirm'), [
      { text: t('cancel'), style: 'cancel' },
      { text: t('community.deletePost'), style: 'destructive', onPress: async () => {
        try { await deletePost(postId); setPosts(prev => prev.filter(p => p.id !== postId)); } catch {}
      }},
    ]);
  }, []);

  if (isLoading) return <View style={styles.center}><ActivityIndicator size="large" color={colors.primary} /></View>;

  return (
    <View style={{ flex: 1 }}>
      <FlatList
        data={posts}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => (
          <PostCard post={item} userId={userId} onLike={handleLike} onDelete={handleDelete}
            onComment={(id) => router.push(`/(tabs)/(community)/post-comments?postId=${id}`)} />
        )}
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <Ionicons name="chatbubbles-outline" size={48} color={colors.textMuted} />
            <Text style={styles.emptyText}>{t('community.emptyFeed')}</Text>
          </View>
        }
        refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={() => { setIsRefreshing(true); loadFeed(); }} tintColor={colors.primary} />}
        onEndReached={loadMore}
        onEndReachedThreshold={0.5}
        ListFooterComponent={loadingMore ? <ActivityIndicator color={colors.primary} style={{ padding: spacing.md }} /> : null}
        contentContainerStyle={posts.length === 0 ? { flex: 1 } : undefined}
      />
      <TouchableOpacity style={styles.fab} onPress={() => router.push('/(tabs)/(community)/new-post')} activeOpacity={0.8}>
        <Ionicons name="add" size={28} color={colors.background} />
      </TouchableOpacity>
    </View>
  );
}

// --- Groups Tab ---

function GroupsTab() {
  const { language } = useLanguage();
  const [groups, setGroups] = useState<Group[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const load = useCallback(async () => {
    try { const data = await getGroups(); setGroups(data.groups); }
    catch { Alert.alert(t('error'), t('community.loadError')); }
    finally { setIsLoading(false); setIsRefreshing(false); }
  }, []);

  useFocusEffect(
    useCallback(() => { load(); }, [load])
  );

  if (isLoading) return <View style={styles.center}><ActivityIndicator size="large" color={colors.primary} /></View>;

  return (
    <FlatList
      data={groups}
      keyExtractor={(item) => item.id.toString()}
      ListHeaderComponent={
        <TouchableOpacity style={styles.browseBtn} onPress={() => router.push('/(tabs)/(community)/browse-groups')}>
          <Ionicons name="search" size={18} color={colors.primary} />
          <Text style={styles.browseBtnText}>{t('community.browseGroups')}</Text>
          <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
        </TouchableOpacity>
      }
      renderItem={({ item }) => (
        <TouchableOpacity
          style={styles.chatRow}
          onPress={() => router.push(`/(tabs)/(community)/group-chat?groupId=${item.id}&groupName=${encodeURIComponent(item.name)}`)}
          activeOpacity={0.7}
        >
          <View style={styles.avatarGroup}>
            <Ionicons name="people" size={22} color={colors.primary} />
          </View>
          <View style={styles.chatInfo}>
            <Text style={styles.chatName}>{item.name}</Text>
            {item.description ? <Text style={styles.chatPreview} numberOfLines={1}>{item.description}</Text> : null}
            <Text style={styles.chatMeta}>{item.member_count} {t('community.groupMembers').toLowerCase()}</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
        </TouchableOpacity>
      )}
      ListEmptyComponent={
        <View style={styles.emptyState}>
          <Ionicons name="people-outline" size={48} color={colors.textMuted} />
          <Text style={styles.emptyText}>{t('community.noGroups')}</Text>
          <Text style={styles.emptyHint}>{t('community.noGroupsHint')}</Text>
        </View>
      }
      refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={() => { setIsRefreshing(true); load(); }} tintColor={colors.primary} />}
      contentContainerStyle={groups.length === 0 ? { flex: 1 } : { paddingBottom: spacing.lg }}
    />
  );
}

// --- Chats Tab ---

function ChatsTab({ userId }: { userId: number }) {
  const { language } = useLanguage();
  const [chats, setChats] = useState<ChatItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const load = useCallback(async () => {
    try { const data = await getChats(); setChats(data.chats); }
    catch { Alert.alert(t('error'), t('community.loadError')); }
    finally { setIsLoading(false); setIsRefreshing(false); }
  }, []);

  useFocusEffect(
    useCallback(() => { load(); }, [load])
  );

  const filteredChats = searchQuery
    ? chats.filter(c => c.name.toLowerCase().includes(searchQuery.toLowerCase()))
    : chats;

  const handleTap = (chat: ChatItem) => {
    if (chat.type === 'dm') {
      router.push(`/(tabs)/(community)/conversation?conversationId=${chat.id}&name=${encodeURIComponent(chat.name)}`);
    } else {
      router.push(`/(tabs)/(community)/group-chat?groupId=${chat.id}&groupName=${encodeURIComponent(chat.name)}`);
    }
  };

  if (isLoading) return <View style={styles.center}><ActivityIndicator size="large" color={colors.primary} /></View>;

  return (
    <View style={{ flex: 1 }}>
      <View style={styles.searchBar}>
        <Ionicons name="search" size={18} color={colors.textMuted} />
        <TextInput
          style={styles.searchInput}
          placeholder={t('community.searchPlaceholder')}
          placeholderTextColor={colors.textMuted}
          value={searchQuery}
          onChangeText={setSearchQuery}
        />
        {searchQuery ? (
          <TouchableOpacity onPress={() => setSearchQuery('')}>
            <Ionicons name="close-circle" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        ) : null}
      </View>
      <FlatList
        data={filteredChats}
        keyExtractor={(item) => `${item.type}-${item.id}`}
        renderItem={({ item }) => {
          const lastMsg = item.last_message;
          const isOwnLast = lastMsg?.sender_id === userId;
          const preview = lastMsg
            ? (lastMsg.has_beer ? '🍺 ' : '') +
              (item.type === 'dm' && isOwnLast ? `${t('community.you')}: ` : '') +
              lastMsg.content
            : '';
          return (
            <TouchableOpacity style={styles.chatRow} onPress={() => handleTap(item)} activeOpacity={0.7}>
              <View style={item.type === 'group' ? styles.avatarGroup : styles.avatarDm}>
                <Ionicons name={item.type === 'group' ? 'people' : 'person'} size={20} color={item.type === 'group' ? colors.primary : colors.textMuted} />
              </View>
              <View style={styles.chatInfo}>
                <View style={styles.chatHeader}>
                  <Text style={[styles.chatName, item.unread_count > 0 && styles.chatNameBold]} numberOfLines={1}>{item.name}</Text>
                  {lastMsg && <Text style={styles.chatTime}>{timeAgo(lastMsg.created_at)}</Text>}
                </View>
                {preview ? (
                  <Text style={[styles.chatPreview, item.unread_count > 0 && styles.chatPreviewUnread]} numberOfLines={1}>{preview}</Text>
                ) : (
                  item.type === 'group' && item.member_count ? (
                    <Text style={styles.chatMeta}>{item.member_count} {t('community.groupMembers').toLowerCase()}</Text>
                  ) : null
                )}
              </View>
              {item.unread_count > 0 && (
                <View style={styles.unreadBadge}>
                  <Text style={styles.unreadText}>{item.unread_count > 9 ? '9+' : item.unread_count}</Text>
                </View>
              )}
            </TouchableOpacity>
          );
        }}
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <Ionicons name="chatbubbles-outline" size={48} color={colors.textMuted} />
            <Text style={styles.emptyText}>{t('community.noChats')}</Text>
            <Text style={styles.emptyHint}>{t('community.noChatsHint')}</Text>
          </View>
        }
        refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={() => { setIsRefreshing(true); load(); }} tintColor={colors.primary} />}
        contentContainerStyle={filteredChats.length === 0 ? { flex: 1 } : { paddingBottom: spacing.lg }}
      />
      <TouchableOpacity style={styles.fab} onPress={() => router.push('/(tabs)/(community)/members')} activeOpacity={0.8}>
        <Ionicons name="person-add" size={22} color={colors.background} />
      </TouchableOpacity>
    </View>
  );
}

// --- Forum Tab ---

function ForumTab({ userId }: { userId: number }) {
  const { language } = useLanguage();
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [sortBy, setSortBy] = useState<'top' | 'new'>('top');

  const load = useCallback(async () => {
    try {
      const data = await getSuggestions(1, sortBy);
      setSuggestions(data.results);
    } catch {
      Alert.alert(t('error'), t('community.loadError'));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [sortBy]);

  useFocusEffect(
    useCallback(() => { load(); }, [load])
  );

  const handleVote = useCallback(async (id: number) => {
    try {
      const result = await toggleSuggestionVote(id);
      setSuggestions(prev => prev.map(s =>
        s.id === id ? { ...s, is_voted: result.voted, vote_count: result.vote_count } : s
      ));
    } catch {}
  }, []);

  const handleDelete = useCallback((id: number) => {
    Alert.alert(t('community.deleteSuggestion'), t('community.deleteSuggestionConfirm'), [
      { text: t('cancel'), style: 'cancel' },
      { text: t('community.deleteSuggestion'), style: 'destructive', onPress: async () => {
        try { await deleteSuggestion(id); setSuggestions(prev => prev.filter(s => s.id !== id)); } catch {}
      }},
    ]);
  }, []);

  const statusLabel = (s: string) => t(`community.status${s.charAt(0).toUpperCase() + s.slice(1)}`);

  if (isLoading) return <View style={styles.center}><ActivityIndicator size="large" color={colors.primary} /></View>;

  return (
    <View style={{ flex: 1 }}>
      {/* Sort toggle */}
      <View style={styles.sortBar}>
        {(['top', 'new'] as const).map(key => (
          <TouchableOpacity
            key={key}
            style={[styles.sortBtn, sortBy === key && styles.sortBtnActive]}
            onPress={() => { setSortBy(key); setIsLoading(true); }}
          >
            <Ionicons
              name={key === 'top' ? 'trending-up' : 'time-outline'}
              size={14}
              color={sortBy === key ? colors.background : colors.textMuted}
            />
            <Text style={[styles.sortBtnText, sortBy === key && styles.sortBtnTextActive]}>
              {t(`community.sort${key === 'top' ? 'Top' : 'New'}`)}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <FlatList
        data={suggestions}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => {
          const isOwn = item.author.user_id === userId;
          return (
            <TouchableOpacity
              style={styles.suggestionCard}
              onPress={() => router.push(`/(tabs)/(community)/suggestion-detail?suggestionId=${item.id}`)}
              activeOpacity={0.7}
            >
              {/* Vote column */}
              <TouchableOpacity style={styles.voteCol} onPress={() => handleVote(item.id)}>
                <Ionicons
                  name={item.is_voted ? 'arrow-up-circle' : 'arrow-up-circle-outline'}
                  size={28}
                  color={item.is_voted ? colors.primary : colors.textMuted}
                />
                <Text style={[styles.voteCount, item.is_voted && { color: colors.primary }]}>
                  {item.vote_count}
                </Text>
              </TouchableOpacity>

              {/* Content */}
              <View style={styles.suggestionContent}>
                <View style={styles.suggestionTopRow}>
                  {item.tag ? (
                    <View style={styles.tagBadge}>
                      <Text style={styles.tagText}>{item.tag}</Text>
                    </View>
                  ) : null}
                  {item.status !== 'open' && (
                    <View style={[styles.statusBadge, { backgroundColor: (STATUS_COLORS[item.status] || colors.textMuted) + '25' }]}>
                      <Text style={[styles.statusText, { color: STATUS_COLORS[item.status] || colors.textMuted }]}>
                        {statusLabel(item.status)}
                      </Text>
                    </View>
                  )}
                </View>
                <Text style={styles.suggestionTitle} numberOfLines={2}>{item.title}</Text>
                <Text style={styles.suggestionBody} numberOfLines={2}>{item.content}</Text>
                <View style={styles.suggestionFooter}>
                  <Text style={styles.suggestionMeta}>{item.author.display_name} · {timeAgo(item.created_at)}</Text>
                  <View style={styles.commentCountRow}>
                    <Ionicons name="chatbubble-outline" size={13} color={colors.textMuted} />
                    <Text style={styles.suggestionMeta}>{item.comment_count}</Text>
                  </View>
                  {isOwn && (
                    <TouchableOpacity onPress={() => handleDelete(item.id)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
                      <Ionicons name="trash-outline" size={14} color={colors.textMuted} />
                    </TouchableOpacity>
                  )}
                </View>
              </View>
            </TouchableOpacity>
          );
        }}
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <Ionicons name="bulb-outline" size={48} color={colors.textMuted} />
            <Text style={styles.emptyText}>{t('community.noSuggestions')}</Text>
            <Text style={styles.emptyHint}>{t('community.noSuggestionsHint')}</Text>
          </View>
        }
        refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={() => { setIsRefreshing(true); load(); }} tintColor={colors.primary} />}
        contentContainerStyle={suggestions.length === 0 ? { flex: 1 } : { paddingBottom: spacing.lg }}
      />
      <TouchableOpacity style={styles.fab} onPress={() => router.push('/(tabs)/(community)/new-suggestion')} activeOpacity={0.8}>
        <Ionicons name="add" size={28} color={colors.background} />
      </TouchableOpacity>
    </View>
  );
}

// --- Main Screen ---

export default function CommunityScreen() {
  const { language } = useLanguage();
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<'feed' | 'groups' | 'chats' | 'forum'>('feed');

  const tabs = [
    { key: 'feed' as const, label: t('community.feed') },
    { key: 'groups' as const, label: t('community.groups') },
    { key: 'chats' as const, label: t('community.chats') },
    { key: 'forum' as const, label: t('community.forum') },
  ];

  return (
    <View style={styles.container}>
      <View style={styles.topTabBar}>
        {tabs.map(tab => (
          <TouchableOpacity
            key={tab.key}
            style={[styles.topTab, activeTab === tab.key && styles.topTabActive]}
            onPress={() => setActiveTab(tab.key)}
          >
            <Text style={[styles.topTabText, activeTab === tab.key && styles.topTabTextActive]}>
              {tab.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {activeTab === 'feed' && <FeedTab userId={user?.id ?? 0} />}
      {activeTab === 'groups' && <GroupsTab />}
      {activeTab === 'chats' && <ChatsTab userId={user?.id ?? 0} />}
      {activeTab === 'forum' && <ForumTab userId={user?.id ?? 0} />}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center' },

  // Top tabs
  topTabBar: { flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: colors.tertiary + '30' },
  topTab: { flex: 1, alignItems: 'center', paddingVertical: spacing.md, borderBottomWidth: 2, borderBottomColor: 'transparent' },
  topTabActive: { borderBottomColor: colors.primary },
  topTabText: { fontSize: 14, fontWeight: '600', color: colors.textMuted },
  topTabTextActive: { color: colors.primary },

  // Post card
  postCard: { backgroundColor: colors.surface, marginHorizontal: spacing.md, marginTop: spacing.md, borderRadius: borderRadius.md, padding: spacing.md },
  postHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.sm },
  authorRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  avatarSm: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.tertiary + '30', justifyContent: 'center', alignItems: 'center' },
  authorName: { color: colors.text, fontSize: 14, fontWeight: '600' },
  postTime: { color: colors.textMuted, fontSize: 12 },
  postTypeBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: spacing.xs },
  postTypeText: { color: colors.primary, fontSize: 12, fontWeight: '600' },
  postContent: { color: colors.text, fontSize: 15, lineHeight: 22, marginBottom: spacing.sm },
  beerCard: { flexDirection: 'row', backgroundColor: colors.background, borderRadius: borderRadius.sm, overflow: 'hidden', marginBottom: spacing.sm },
  beerImage: { width: 60, height: 60 },
  beerInfo: { flex: 1, padding: spacing.sm, justifyContent: 'center' },
  beerTitle: { color: colors.text, fontSize: 13, fontWeight: '600' },
  beerVendor: { color: colors.textMuted, fontSize: 12, marginTop: 2 },
  beerMeta: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: 4 },
  ratingBadge: { flexDirection: 'row', alignItems: 'center', gap: 2, backgroundColor: 'rgba(255, 215, 0, 0.2)', paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  ratingText: { fontSize: 11, fontWeight: '700', color: '#B8860B' },
  beerStyle: { color: colors.textMuted, fontSize: 11 },
  postActions: { flexDirection: 'row', gap: spacing.lg, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.tertiary + '20' },
  actionBtn: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  actionText: { color: colors.textMuted, fontSize: 13 },

  // Chat / group rows
  chatRow: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.surface, marginHorizontal: spacing.md, marginTop: spacing.sm, borderRadius: borderRadius.md, padding: spacing.md },
  avatarDm: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.tertiary + '30', justifyContent: 'center', alignItems: 'center', marginRight: spacing.md },
  avatarGroup: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.primary + '20', justifyContent: 'center', alignItems: 'center', marginRight: spacing.md },
  chatInfo: { flex: 1 },
  chatHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  chatName: { color: colors.text, fontSize: 15, flex: 1 },
  chatNameBold: { fontWeight: '700' },
  chatTime: { color: colors.textMuted, fontSize: 12, marginLeft: spacing.sm },
  chatPreview: { color: colors.textMuted, fontSize: 13, marginTop: 2 },
  chatPreviewUnread: { color: colors.text },
  chatMeta: { color: colors.textMuted, fontSize: 12, marginTop: 2 },
  unreadBadge: { backgroundColor: colors.primary, borderRadius: 10, minWidth: 20, height: 20, justifyContent: 'center', alignItems: 'center', paddingHorizontal: 6, marginLeft: spacing.sm },
  unreadText: { color: colors.background, fontSize: 11, fontWeight: '700' },

  // Browse groups button
  browseBtn: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, backgroundColor: colors.surface, marginHorizontal: spacing.md, marginTop: spacing.md, borderRadius: borderRadius.md, padding: spacing.md },
  browseBtnText: { color: colors.primary, fontSize: 15, fontWeight: '600', flex: 1 },

  // Search
  searchBar: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.surface, marginHorizontal: spacing.md, marginTop: spacing.sm, borderRadius: borderRadius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, gap: spacing.sm },
  searchInput: { flex: 1, color: colors.text, fontSize: 15 },

  // Forum / Suggestions
  sortBar: { flexDirection: 'row', gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  sortBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: borderRadius.sm, backgroundColor: colors.surface },
  sortBtnActive: { backgroundColor: colors.primary },
  sortBtnText: { fontSize: 13, fontWeight: '600', color: colors.textMuted },
  sortBtnTextActive: { color: colors.background },
  suggestionCard: { flexDirection: 'row', backgroundColor: colors.surface, marginHorizontal: spacing.md, marginTop: spacing.sm, borderRadius: borderRadius.md, padding: spacing.md },
  voteCol: { alignItems: 'center', marginRight: spacing.md, minWidth: 36 },
  voteCount: { color: colors.textMuted, fontSize: 14, fontWeight: '700', marginTop: 2 },
  suggestionContent: { flex: 1 },
  suggestionTopRow: { flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.xs, flexWrap: 'wrap' },
  tagBadge: { backgroundColor: colors.primary + '20', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 4 },
  tagText: { color: colors.primary, fontSize: 11, fontWeight: '600' },
  statusBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 4 },
  statusText: { fontSize: 11, fontWeight: '600' },
  suggestionTitle: { color: colors.text, fontSize: 15, fontWeight: '600', marginBottom: 4 },
  suggestionBody: { color: colors.textMuted, fontSize: 13, lineHeight: 18, marginBottom: spacing.sm },
  suggestionFooter: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  suggestionMeta: { color: colors.textMuted, fontSize: 12 },
  commentCountRow: { flexDirection: 'row', alignItems: 'center', gap: 3 },

  // Empty & FAB
  emptyState: { flex: 1, justifyContent: 'center', alignItems: 'center', gap: spacing.md },
  emptyText: { color: colors.textMuted, fontSize: 15 },
  emptyHint: { color: colors.textMuted, fontSize: 13 },
  fab: { position: 'absolute', bottom: spacing.lg, right: spacing.lg, width: 56, height: 56, borderRadius: 28, backgroundColor: colors.primary, justifyContent: 'center', alignItems: 'center', elevation: 4, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.25, shadowRadius: 4 },
});
