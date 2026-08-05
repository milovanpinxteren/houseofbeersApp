import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity, Pressable, Image, TextInput,
  RefreshControl, ActivityIndicator, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import { useLanguage } from '../../src/context/LanguageContext';
import { useAuth } from '../../src/context/AuthContext';
import { t } from '../../src/i18n';
import { colors, spacing, borderRadius, fonts, type } from '../../src/theme/colors';
import { Card, EmptyState, SkeletonCard, Badge, Button, useToast } from '../../src/components/ui';
import {
  getFeed, toggleLike, deletePost, editPost, getGroups, getChats,
  getSuggestions, toggleSuggestionVote, deleteSuggestion,
  Post, Group, ChatItem, Suggestion,
} from '../../src/api/community';
import { timeAgo } from '../../src/utils/timeAgo';

const STATUS_COLORS: Record<string, string> = {
  open: colors.primary,
  planned: colors.warning,
  done: colors.success,
  declined: colors.textMuted,
};

function LoadingList() {
  return (
    <View style={styles.skeletonWrap}>
      <SkeletonCard />
      <SkeletonCard />
      <SkeletonCard />
    </View>
  );
}

// --- Post Card ---

function PostCard({ post, userId, isStaff, onLike, onDelete, onComment, onEdit }: {
  post: Post;
  userId: number;
  isStaff: boolean;
  onLike: (id: number) => void;
  onDelete: (id: number) => void;
  onComment: (id: number) => void;
  onEdit: (id: number, content: string) => Promise<boolean>;
}) {
  const { language } = useLanguage();
  const isOwn = post.author.user_id === userId;
  const canModerate = isOwn || isStaff;
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const startEdit = () => {
    setDraft(post.content);
    setIsEditing(true);
  };

  const saveEdit = async () => {
    if (!draft.trim() || isSaving) return;
    setIsSaving(true);
    const ok = await onEdit(post.id, draft.trim());
    setIsSaving(false);
    if (ok) setIsEditing(false);
  };

  return (
    <Card style={styles.postCard}>
      <View style={styles.postHeader}>
        <Pressable
          style={({ pressed }) => [styles.authorRow, pressed && { opacity: 0.7 }]}
          onPress={() => router.push(`/(tabs)/(community)/member-profile?userId=${post.author.user_id}`)}
        >
          <View style={styles.avatarSm}>
            <Ionicons name="person" size={18} color={colors.tertiary} />
          </View>
          <View>
            <Text style={styles.authorName}>{post.author.display_name}</Text>
            <Text style={styles.postTime}>
              {timeAgo(post.created_at)}
              {post.edited_at ? ` · ${t('community.edited')}` : ''}
            </Text>
          </View>
        </Pressable>
        {canModerate && !isEditing && (
          <View style={styles.moderateRow}>
            <Pressable
              onPress={startEdit}
              hitSlop={{ top: 12, bottom: 12, left: 8, right: 8 }}
              style={({ pressed }) => pressed && { opacity: 0.6 }}
            >
              <Ionicons name="pencil-outline" size={18} color={colors.textMuted} />
            </Pressable>
            <Pressable
              onPress={() => onDelete(post.id)}
              hitSlop={{ top: 12, bottom: 12, left: 8, right: 12 }}
              style={({ pressed }) => pressed && { opacity: 0.6 }}
            >
              <Ionicons name="trash-outline" size={18} color={colors.textMuted} />
            </Pressable>
          </View>
        )}
      </View>

      {post.post_type !== 'text' && (
        <View style={styles.postTypeBadge}>
          <Ionicons
            name={post.post_type === 'review' ? 'star' : 'share-social'}
            size={11}
            color={colors.primary}
          />
          <Text style={styles.postTypeText}>
            {t(`community.${post.post_type === 'review' ? 'shareReview' : 'shareBeer'}`)}
          </Text>
        </View>
      )}

      {isEditing ? (
        <View style={styles.editWrap}>
          <TextInput
            style={styles.editInput}
            value={draft}
            onChangeText={setDraft}
            multiline
            maxLength={1000}
            placeholderTextColor={colors.textMuted}
            autoFocus
          />
          <View style={styles.editActions}>
            <Button label={t('cancel')} variant="ghost" size="sm" onPress={() => setIsEditing(false)} />
            <Button label={t('save')} size="sm" onPress={saveEdit} loading={isSaving} disabled={!draft.trim()} />
          </View>
        </View>
      ) : (
        <Text style={styles.postContent}>{post.content}</Text>
      )}

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
                  <Ionicons name="star" size={10} color={colors.warning} />
                  <Text style={styles.ratingText}>{Number(post.beer_rating).toFixed(1)}</Text>
                </View>
              )}
              {post.beer_style ? <Text style={styles.beerStyle}>{post.beer_style}</Text> : null}
            </View>
          </View>
        </View>
      ) : null}

      <View style={styles.postActions}>
        <Pressable
          style={({ pressed }) => [styles.actionBtn, pressed && { opacity: 0.6 }]}
          onPress={() => onLike(post.id)}
          hitSlop={{ top: 8, bottom: 8 }}
        >
          <Ionicons name={post.is_liked ? 'heart' : 'heart-outline'} size={20} color={post.is_liked ? colors.error : colors.textMuted} />
          <Text style={[styles.actionText, post.is_liked && { color: colors.error }]}>{post.like_count}</Text>
        </Pressable>
        <Pressable
          style={({ pressed }) => [styles.actionBtn, pressed && { opacity: 0.6 }]}
          onPress={() => onComment(post.id)}
          hitSlop={{ top: 8, bottom: 8 }}
        >
          <Ionicons name="chatbubble-outline" size={18} color={colors.textMuted} />
          <Text style={styles.actionText}>{post.comment_count}</Text>
        </Pressable>
      </View>
    </Card>
  );
}

// --- Feed Tab ---

function FeedTab({ userId, isStaff }: { userId: number; isStaff: boolean }) {
  const [posts, setPosts] = useState<Post[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const { showToast } = useToast();

  const loadFeed = useCallback(async () => {
    try {
      const data = await getFeed();
      setPosts(data.results);
      setNextCursor(data.next);
    } catch {
      showToast(t('community.loadError'), 'error');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [showToast]);

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
        try {
          await deletePost(postId);
          setPosts(prev => prev.filter(p => p.id !== postId));
          showToast(t('community.deleted'), 'success');
        } catch {
          showToast(t('community.deleteError'), 'error');
        }
      }},
    ]);
  }, [showToast]);

  const handleEdit = useCallback(async (postId: number, content: string) => {
    try {
      const updated = await editPost(postId, content);
      setPosts(prev => prev.map(p => (p.id === postId ? updated : p)));
      showToast(t('community.editSaved'), 'success');
      return true;
    } catch {
      showToast(t('community.editError'), 'error');
      return false;
    }
  }, [showToast]);

  if (isLoading) return <LoadingList />;

  return (
    <View style={{ flex: 1 }}>
      <FlatList
        data={posts}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => (
          <PostCard post={item} userId={userId} isStaff={isStaff} onLike={handleLike}
            onDelete={handleDelete} onEdit={handleEdit}
            onComment={(id) => router.push(`/(tabs)/(community)/post-comments?postId=${id}`)} />
        )}
        ListEmptyComponent={
          <EmptyState
            icon="chatbubbles-outline"
            title={t('community.emptyFeedTitle')}
            message={t('community.emptyFeedHint')}
            actionLabel={t('community.newPost')}
            onAction={() => router.push('/(tabs)/(community)/new-post')}
          />
        }
        refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={() => { setIsRefreshing(true); loadFeed(); }} tintColor={colors.primary} />}
        onEndReached={loadMore}
        onEndReachedThreshold={0.5}
        ListFooterComponent={loadingMore ? <ActivityIndicator color={colors.primary} style={{ padding: spacing.md }} /> : null}
        contentContainerStyle={posts.length === 0 ? styles.emptyListContent : styles.listContent}
      />
      <Pressable
        style={({ pressed }) => [styles.fab, pressed && { opacity: 0.85, transform: [{ scale: 0.96 }] }]}
        onPress={() => router.push('/(tabs)/(community)/new-post')}
      >
        <Ionicons name="add" size={28} color={colors.background} />
      </Pressable>
    </View>
  );
}

// --- Groups Tab ---

function GroupsTab() {
  const { language } = useLanguage();
  const [groups, setGroups] = useState<Group[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const { showToast } = useToast();

  const load = useCallback(async () => {
    try { const data = await getGroups(); setGroups(data.groups); }
    catch { showToast(t('community.loadError'), 'error'); }
    finally { setIsLoading(false); setIsRefreshing(false); }
  }, [showToast]);

  useFocusEffect(
    useCallback(() => { load(); }, [load])
  );

  if (isLoading) return <LoadingList />;

  return (
    <FlatList
      data={groups}
      keyExtractor={(item) => item.id.toString()}
      ListHeaderComponent={
        <Card
          style={styles.browseBtn}
          onPress={() => router.push('/(tabs)/(community)/browse-groups')}
        >
          <View style={styles.browseBtnInner}>
            <View style={styles.browseIconWrap}>
              <Ionicons name="compass-outline" size={20} color={colors.primary} />
            </View>
            <Text style={styles.browseBtnText}>{t('community.browseGroups')}</Text>
            <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
          </View>
        </Card>
      }
      renderItem={({ item }) => (
        <Card
          style={styles.chatRow}
          onPress={() => router.push(`/(tabs)/(community)/group-chat?groupId=${item.id}&groupName=${encodeURIComponent(item.name)}`)}
        >
          <View style={styles.chatRowInner}>
            <View style={styles.avatarGroup}>
              <Ionicons name="people" size={22} color={colors.primary} />
            </View>
            <View style={styles.chatInfo}>
              <Text style={styles.chatName}>{item.name}</Text>
              {item.description ? <Text style={styles.chatPreview} numberOfLines={1}>{item.description}</Text> : null}
              <Text style={styles.chatMeta}>{item.member_count} {t('community.groupMembers').toLowerCase()}</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
          </View>
        </Card>
      )}
      ListEmptyComponent={
        <EmptyState
          icon="people-outline"
          title={t('community.noGroups')}
          message={t('community.noGroupsHint')}
          actionLabel={t('community.browseGroups')}
          onAction={() => router.push('/(tabs)/(community)/browse-groups')}
        />
      }
      refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={() => { setIsRefreshing(true); load(); }} tintColor={colors.primary} />}
      contentContainerStyle={groups.length === 0 ? styles.emptyListWithHeader : styles.listContent}
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
  const { showToast } = useToast();

  const load = useCallback(async () => {
    try { const data = await getChats(); setChats(data.chats); }
    catch { showToast(t('community.loadError'), 'error'); }
    finally { setIsLoading(false); setIsRefreshing(false); }
  }, [showToast]);

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

  if (isLoading) return <LoadingList />;

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
          <TouchableOpacity onPress={() => setSearchQuery('')} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
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
            <Card style={styles.chatRow} onPress={() => handleTap(item)}>
              <View style={styles.chatRowInner}>
                <View style={item.type === 'group' ? styles.avatarGroup : styles.avatarDm}>
                  <Ionicons name={item.type === 'group' ? 'people' : 'person'} size={20} color={item.type === 'group' ? colors.primary : colors.tertiary} />
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
                  <Badge value={item.unread_count > 9 ? '9+' : item.unread_count} />
                )}
              </View>
            </Card>
          );
        }}
        ListEmptyComponent={
          <EmptyState
            icon="chatbubbles-outline"
            title={t('community.noChats')}
            message={t('community.noChatsHint')}
            actionLabel={t('community.members')}
            onAction={() => router.push('/(tabs)/(community)/members')}
          />
        }
        refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={() => { setIsRefreshing(true); load(); }} tintColor={colors.primary} />}
        contentContainerStyle={filteredChats.length === 0 ? styles.emptyListContent : styles.listContent}
      />
      <Pressable
        style={({ pressed }) => [styles.fab, pressed && { opacity: 0.85, transform: [{ scale: 0.96 }] }]}
        onPress={() => router.push('/(tabs)/(community)/members')}
      >
        <Ionicons name="person-add" size={22} color={colors.background} />
      </Pressable>
    </View>
  );
}

// --- Forum Tab ---

function ForumTab({ userId, isStaff }: { userId: number; isStaff: boolean }) {
  const { language } = useLanguage();
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [sortBy, setSortBy] = useState<'top' | 'new'>('top');
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const { showToast } = useToast();

  const load = useCallback(async () => {
    try {
      const data = await getSuggestions(1, sortBy);
      setSuggestions(data.results);
      setNextPage(data.next ? 2 : null);
    } catch {
      showToast(t('community.loadError'), 'error');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [sortBy, showToast]);

  const loadMore = useCallback(async () => {
    if (!nextPage || loadingMore) return;
    setLoadingMore(true);
    try {
      const data = await getSuggestions(nextPage, sortBy);
      setSuggestions(prev => [...prev, ...data.results]);
      setNextPage(data.next ? nextPage + 1 : null);
    } catch {} finally { setLoadingMore(false); }
  }, [nextPage, loadingMore, sortBy]);

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
        try {
          await deleteSuggestion(id);
          setSuggestions(prev => prev.filter(s => s.id !== id));
          showToast(t('community.deleted'), 'success');
        } catch {
          showToast(t('community.deleteError'), 'error');
        }
      }},
    ]);
  }, [showToast]);

  const statusLabel = (s: string) => t(`community.status${s.charAt(0).toUpperCase() + s.slice(1)}`);

  if (isLoading) return <LoadingList />;

  return (
    <View style={{ flex: 1 }}>
      {/* Sort toggle */}
      <View style={styles.sortBar}>
        {(['top', 'new'] as const).map(key => (
          <Pressable
            key={key}
            style={({ pressed }) => [
              styles.sortBtn,
              sortBy === key && styles.sortBtnActive,
              pressed && { opacity: 0.85 },
            ]}
            onPress={() => {
              if (sortBy !== key) { setSortBy(key); setIsLoading(true); }
            }}
          >
            <Ionicons
              name={key === 'top' ? 'trending-up' : 'time-outline'}
              size={13}
              color={sortBy === key ? colors.background : colors.textMuted}
            />
            <Text style={[styles.sortBtnText, sortBy === key && styles.sortBtnTextActive]}>
              {t(`community.sort${key === 'top' ? 'Top' : 'New'}`)}
            </Text>
          </Pressable>
        ))}
      </View>

      <FlatList
        data={suggestions}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => {
          const canModerate = item.author.user_id === userId || isStaff;
          return (
            <Card
              style={styles.suggestionCard}
              onPress={() => router.push(`/(tabs)/(community)/suggestion-detail?suggestionId=${item.id}`)}
            >
              <View style={styles.suggestionInner}>
                {/* Vote column */}
                <Pressable
                  style={({ pressed }) => [styles.voteCol, pressed && { opacity: 0.7 }]}
                  onPress={() => handleVote(item.id)}
                  hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                >
                  <Ionicons
                    name={item.is_voted ? 'arrow-up-circle' : 'arrow-up-circle-outline'}
                    size={28}
                    color={item.is_voted ? colors.primary : colors.textMuted}
                  />
                  <Text style={[styles.voteCount, item.is_voted && { color: colors.primary }]}>
                    {item.vote_count}
                  </Text>
                </Pressable>

                {/* Content */}
                <View style={styles.suggestionContent}>
                  {(item.tag || item.status !== 'open') && (
                    <View style={styles.suggestionTopRow}>
                      {item.tag ? (
                        <View style={styles.tagBadge}>
                          <Text style={styles.tagText}>{item.tag}</Text>
                        </View>
                      ) : null}
                      {item.status !== 'open' && (
                        <View style={[styles.statusBadge, { backgroundColor: (STATUS_COLORS[item.status] || colors.textMuted) + '22' }]}>
                          <Text style={[styles.statusText, { color: STATUS_COLORS[item.status] || colors.textMuted }]}>
                            {statusLabel(item.status)}
                          </Text>
                        </View>
                      )}
                    </View>
                  )}
                  <Text style={styles.suggestionTitle} numberOfLines={2}>{item.title}</Text>
                  <Text style={styles.suggestionBody} numberOfLines={2}>{item.content}</Text>
                  <View style={styles.suggestionFooter}>
                    <Text style={styles.suggestionMeta}>
                      {item.author.display_name} · {timeAgo(item.created_at)}
                      {item.edited_at ? ` · ${t('community.edited')}` : ''}
                    </Text>
                    <View style={styles.commentCountRow}>
                      <Ionicons name="chatbubble-outline" size={13} color={colors.textMuted} />
                      <Text style={styles.suggestionMeta}>{item.comment_count}</Text>
                    </View>
                    {canModerate && (
                      <Pressable
                        onPress={() => handleDelete(item.id)}
                        hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
                        style={({ pressed }) => pressed && { opacity: 0.6 }}
                      >
                        <Ionicons name="trash-outline" size={14} color={colors.textMuted} />
                      </Pressable>
                    )}
                  </View>
                </View>
              </View>
            </Card>
          );
        }}
        ListEmptyComponent={
          <EmptyState
            icon="bulb-outline"
            title={t('community.noSuggestions')}
            message={t('community.noSuggestionsHint')}
            actionLabel={t('community.newSuggestion')}
            onAction={() => router.push('/(tabs)/(community)/new-suggestion')}
          />
        }
        refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={() => { setIsRefreshing(true); load(); }} tintColor={colors.primary} />}
        onEndReached={loadMore}
        onEndReachedThreshold={0.5}
        ListFooterComponent={loadingMore ? <ActivityIndicator color={colors.primary} style={{ padding: spacing.md }} /> : null}
        contentContainerStyle={suggestions.length === 0 ? styles.emptyListContent : styles.listContent}
      />
      <Pressable
        style={({ pressed }) => [styles.fab, pressed && { opacity: 0.85, transform: [{ scale: 0.96 }] }]}
        onPress={() => router.push('/(tabs)/(community)/new-suggestion')}
      >
        <Ionicons name="add" size={28} color={colors.background} />
      </Pressable>
    </View>
  );
}

// --- Main Screen ---

export default function CommunityScreen() {
  const { language } = useLanguage();
  const { user } = useAuth();
  const isStaff = (user as { is_staff?: boolean } | null)?.is_staff === true;
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
          <Pressable
            key={tab.key}
            style={({ pressed }) => [
              styles.topTab,
              activeTab === tab.key && styles.topTabActive,
              pressed && activeTab !== tab.key && { opacity: 0.7 },
            ]}
            onPress={() => setActiveTab(tab.key)}
          >
            <Text style={[styles.topTabText, activeTab === tab.key && styles.topTabTextActive]}>
              {tab.label}
            </Text>
          </Pressable>
        ))}
      </View>

      {activeTab === 'feed' && <FeedTab userId={user?.id ?? 0} isStaff={isStaff} />}
      {activeTab === 'groups' && <GroupsTab />}
      {activeTab === 'chats' && <ChatsTab userId={user?.id ?? 0} />}
      {activeTab === 'forum' && <ForumTab userId={user?.id ?? 0} isStaff={isStaff} />}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },

  skeletonWrap: { padding: spacing.md },
  listContent: { paddingBottom: spacing.xl * 2 },
  emptyListContent: { flexGrow: 1, justifyContent: 'center' },
  emptyListWithHeader: { flexGrow: 1, paddingTop: spacing.md, justifyContent: 'flex-start' },

  // Top tabs — segmented control
  topTabBar: {
    flexDirection: 'row',
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.pill,
    marginHorizontal: spacing.md,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
    padding: 4,
  },
  topTab: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 10,
    borderRadius: borderRadius.pill,
  },
  topTabActive: { backgroundColor: colors.primary },
  topTabText: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: colors.textMuted,
  },
  topTabTextActive: { color: colors.background },

  // Post card
  postCard: { marginHorizontal: spacing.md, marginTop: spacing.md },
  postHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.sm },
  authorRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  avatarSm: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surfaceHigh, justifyContent: 'center', alignItems: 'center' },
  authorName: { fontFamily: fonts.heading, fontSize: 15, letterSpacing: 0.4, color: colors.text },
  postTime: { color: colors.textMuted, fontSize: 12, marginTop: 1 },
  postTypeBadge: { flexDirection: 'row', alignItems: 'center', gap: 5, marginBottom: spacing.xs },
  postTypeText: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 1.4,
    textTransform: 'uppercase',
    color: colors.primary,
  },
  postContent: { ...type.serifBody, marginBottom: spacing.md },
  moderateRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  editWrap: { marginBottom: spacing.md },
  editInput: {
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    color: colors.text,
    fontSize: 15,
    lineHeight: 21,
    minHeight: 72,
    textAlignVertical: 'top',
  },
  editActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm, marginTop: spacing.sm },
  beerCard: {
    flexDirection: 'row',
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.md,
    overflow: 'hidden',
    marginBottom: spacing.md,
  },
  beerImage: { width: 60, height: 60 },
  beerInfo: { flex: 1, padding: spacing.sm, justifyContent: 'center' },
  beerTitle: { fontFamily: fonts.heading, fontSize: 13, letterSpacing: 0.3, color: colors.text },
  beerVendor: { color: colors.textMuted, fontSize: 12, marginTop: 2 },
  beerMeta: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: 4 },
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
  beerStyle: { color: colors.textMuted, fontSize: 11 },
  postActions: {
    flexDirection: 'row',
    gap: spacing.xl,
    paddingTop: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  actionBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: spacing.xs, minHeight: 32 },
  actionText: { fontFamily: fonts.heading, fontSize: 13, letterSpacing: 0.4, color: colors.textMuted },

  // Chat / group rows
  chatRow: { marginHorizontal: spacing.md, marginTop: spacing.sm },
  chatRowInner: { flexDirection: 'row', alignItems: 'center' },
  avatarDm: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.surfaceHigh, justifyContent: 'center', alignItems: 'center', marginRight: spacing.md },
  avatarGroup: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.primary + '18', justifyContent: 'center', alignItems: 'center', marginRight: spacing.md },
  chatInfo: { flex: 1 },
  chatHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  chatName: { fontFamily: fonts.heading, fontSize: 15, letterSpacing: 0.3, color: colors.text, flex: 1 },
  chatNameBold: { fontFamily: fonts.headingBold },
  chatTime: { color: colors.textMuted, fontSize: 12, marginLeft: spacing.sm },
  chatPreview: { color: colors.textMuted, fontSize: 13, marginTop: 3 },
  chatPreviewUnread: { color: colors.text },
  chatMeta: { color: colors.textMuted, fontSize: 12, marginTop: 3 },

  // Browse groups button
  browseBtn: { marginHorizontal: spacing.md, marginTop: spacing.md },
  browseBtnInner: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  browseIconWrap: {
    width: 38,
    height: 38,
    borderRadius: borderRadius.md,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  browseBtnText: { fontFamily: fonts.heading, fontSize: 15, letterSpacing: 0.4, color: colors.text, flex: 1 },

  // Search
  searchBar: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surfaceLow,
    marginHorizontal: spacing.md,
    marginTop: spacing.sm,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
    minHeight: 44,
  },
  searchInput: { flex: 1, color: colors.text, fontSize: 15, paddingVertical: spacing.sm },

  // Forum / Suggestions
  sortBar: { flexDirection: 'row', gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  sortBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: spacing.md,
    paddingVertical: 7,
    borderRadius: borderRadius.pill,
    backgroundColor: colors.surface,
    minHeight: 34,
  },
  sortBtnActive: { backgroundColor: colors.primary },
  sortBtnText: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 1,
    textTransform: 'uppercase',
    color: colors.textMuted,
  },
  sortBtnTextActive: { color: colors.background },
  suggestionCard: { marginHorizontal: spacing.md, marginTop: spacing.sm },
  suggestionInner: { flexDirection: 'row' },
  voteCol: { alignItems: 'center', marginRight: spacing.md, minWidth: 40 },
  voteCount: { fontFamily: fonts.headingBold, fontSize: 14, letterSpacing: 0.3, color: colors.textMuted, marginTop: 2 },
  suggestionContent: { flex: 1 },
  suggestionTopRow: { flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.sm, flexWrap: 'wrap' },
  tagBadge: { backgroundColor: colors.primary + '18', paddingHorizontal: 8, paddingVertical: 3, borderRadius: borderRadius.pill },
  tagText: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 1,
    textTransform: 'uppercase',
    color: colors.primary,
  },
  statusBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: borderRadius.pill },
  statusText: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  suggestionTitle: { fontFamily: fonts.heading, fontSize: 16, letterSpacing: 0.3, color: colors.text, marginBottom: 4 },
  suggestionBody: { color: colors.textMuted, fontSize: 13, lineHeight: 19, marginBottom: spacing.sm },
  suggestionFooter: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  suggestionMeta: { color: colors.textMuted, fontSize: 12 },
  commentCountRow: { flexDirection: 'row', alignItems: 'center', gap: 3 },

  // FAB
  fab: {
    position: 'absolute',
    bottom: spacing.lg,
    right: spacing.lg,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    elevation: 5,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.35,
    shadowRadius: 6,
  },
});
