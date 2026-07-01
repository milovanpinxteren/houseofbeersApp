import React, { useState, useCallback, useRef } from 'react';
import {
  View, Text, StyleSheet, FlatList, TextInput, TouchableOpacity,
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import { useAuth } from '../../../src/context/AuthContext';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
import {
  getSuggestions, getSuggestionComments, addSuggestionComment,
  deleteSuggestionComment, toggleSuggestionVote, toggleSuggestionCommentVote,
  Suggestion, SuggestionComment,
} from '../../../src/api/community';

const STATUS_COLORS: Record<string, string> = {
  open: colors.primary,
  planned: colors.warning,
  done: colors.success,
  declined: colors.textMuted,
};

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

export default function SuggestionDetailScreen() {
  const { language } = useLanguage();
  const { user } = useAuth();
  const { suggestionId } = useLocalSearchParams<{ suggestionId: string }>();
  const id = parseInt(suggestionId || '0', 10);

  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [comments, setComments] = useState<SuggestionComment[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [commentText, setCommentText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const flatListRef = useRef<FlatList>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      // Fetch the suggestion from the list (with annotations)
      const sugData = await getSuggestions(1, 'new');
      const found = sugData.results.find(s => s.id === id);
      if (found) setSuggestion(found);

      const commData = await getSuggestionComments(id);
      setComments(commData.comments);
    } catch {
      Alert.alert(t('error'), t('community.loadError'));
    } finally {
      setIsLoading(false);
    }
  }, [id]);

  useFocusEffect(
    useCallback(() => { load(); }, [load])
  );

  const handleVote = async () => {
    if (!suggestion) return;
    try {
      const result = await toggleSuggestionVote(id);
      setSuggestion(prev => prev ? { ...prev, is_voted: result.voted, vote_count: result.vote_count } : prev);
    } catch {}
  };

  const handleSendComment = async () => {
    if (!commentText.trim() || isSending) return;
    setIsSending(true);
    try {
      const comment = await addSuggestionComment(id, commentText.trim());
      setComments(prev => [...prev, comment]);
      setSuggestion(prev => prev ? { ...prev, comment_count: prev.comment_count + 1 } : prev);
      setCommentText('');
      setTimeout(() => flatListRef.current?.scrollToEnd({ animated: true }), 100);
    } catch {
      Alert.alert(t('error'), t('community.commentError'));
    } finally {
      setIsSending(false);
    }
  };

  const handleCommentVote = useCallback(async (commentId: number) => {
    try {
      const result = await toggleSuggestionCommentVote(commentId);
      setComments(prev => prev.map(c =>
        c.id === commentId ? { ...c, is_voted: result.voted, vote_count: result.vote_count } : c
      ));
    } catch {}
  }, []);

  const handleDeleteComment = (commentId: number) => {
    Alert.alert(t('community.deleteComment'), '', [
      { text: t('cancel'), style: 'cancel' },
      { text: t('community.deleteComment'), style: 'destructive', onPress: async () => {
        try {
          await deleteSuggestionComment(commentId);
          setComments(prev => prev.filter(c => c.id !== commentId));
          setSuggestion(prev => prev ? { ...prev, comment_count: Math.max(0, prev.comment_count - 1) } : prev);
        } catch {}
      }},
    ]);
  };

  if (isLoading) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (!suggestion) {
    return (
      <View style={[styles.container, styles.center]}>
        <Ionicons name="alert-circle-outline" size={48} color={colors.textMuted} />
        <Text style={styles.emptyText}>{t('community.loadError')}</Text>
      </View>
    );
  }

  const statusLabel = (s: string) => t(`community.status${s.charAt(0).toUpperCase() + s.slice(1)}`);

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={90}
    >
      <FlatList
        ref={flatListRef}
        data={comments}
        keyExtractor={(item) => item.id.toString()}
        ListHeaderComponent={
          <View style={styles.headerSection}>
            {/* Vote + Title */}
            <View style={styles.titleRow}>
              <TouchableOpacity style={styles.voteCol} onPress={handleVote}>
                <Ionicons
                  name={suggestion.is_voted ? 'arrow-up-circle' : 'arrow-up-circle-outline'}
                  size={32}
                  color={suggestion.is_voted ? colors.primary : colors.textMuted}
                />
                <Text style={[styles.voteCount, suggestion.is_voted && { color: colors.primary }]}>
                  {suggestion.vote_count}
                </Text>
              </TouchableOpacity>
              <View style={{ flex: 1 }}>
                <View style={styles.badgeRow}>
                  {suggestion.tag ? (
                    <View style={styles.tagBadge}>
                      <Text style={styles.tagText}>{suggestion.tag}</Text>
                    </View>
                  ) : null}
                  <View style={[styles.statusBadge, { backgroundColor: (STATUS_COLORS[suggestion.status] || colors.textMuted) + '25' }]}>
                    <Text style={[styles.statusText, { color: STATUS_COLORS[suggestion.status] || colors.textMuted }]}>
                      {statusLabel(suggestion.status)}
                    </Text>
                  </View>
                </View>
                <Text style={styles.title}>{suggestion.title}</Text>
              </View>
            </View>

            {/* Content */}
            <Text style={styles.content}>{suggestion.content}</Text>

            {/* Author */}
            <Text style={styles.meta}>
              {suggestion.author.display_name} · {timeAgo(suggestion.created_at)}
            </Text>

            {/* Comments header */}
            <View style={styles.commentsHeader}>
              <Ionicons name="chatbubble-outline" size={16} color={colors.text} />
              <Text style={styles.commentsTitle}>
                {suggestion.comment_count} {suggestion.comment_count === 1 ? t('community.comment') : t('community.comments')}
              </Text>
            </View>
          </View>
        }
        renderItem={({ item }) => {
          const isOwn = item.author.user_id === user?.id;
          return (
            <View style={styles.commentCard}>
              <View style={styles.commentHeader}>
                <View style={styles.commentAuthorRow}>
                  <View style={styles.commentAvatar}>
                    <Ionicons name="person" size={14} color={colors.textMuted} />
                  </View>
                  <Text style={styles.commentAuthor}>{item.author.display_name}</Text>
                  <Text style={styles.commentTime}>{timeAgo(item.created_at)}</Text>
                </View>
                {isOwn && (
                  <TouchableOpacity onPress={() => handleDeleteComment(item.id)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
                    <Ionicons name="trash-outline" size={14} color={colors.textMuted} />
                  </TouchableOpacity>
                )}
              </View>
              <Text style={styles.commentContent}>{item.content}</Text>
              <TouchableOpacity style={styles.commentVoteRow} onPress={() => handleCommentVote(item.id)}>
                <Ionicons
                  name={item.is_voted ? 'arrow-up-circle' : 'arrow-up-circle-outline'}
                  size={18}
                  color={item.is_voted ? colors.primary : colors.textMuted}
                />
                <Text style={[styles.commentVoteCount, item.is_voted && { color: colors.primary }]}>
                  {item.vote_count}
                </Text>
              </TouchableOpacity>
            </View>
          );
        }}
        ListEmptyComponent={
          <View style={styles.emptyComments}>
            <Text style={styles.emptyText}>{t('community.noPosts')}</Text>
          </View>
        }
        contentContainerStyle={{ padding: spacing.md, flexGrow: 1 }}
      />

      {/* Comment input */}
      <View style={styles.inputBar}>
        <TextInput
          style={styles.textInput}
          placeholder={t('community.addComment')}
          placeholderTextColor={colors.textMuted}
          value={commentText}
          onChangeText={setCommentText}
          maxLength={500}
          multiline
        />
        <TouchableOpacity
          style={[styles.sendBtn, (!commentText.trim() || isSending) && styles.sendBtnDisabled]}
          onPress={handleSendComment}
          disabled={!commentText.trim() || isSending}
        >
          {isSending ? (
            <ActivityIndicator size="small" color={colors.background} />
          ) : (
            <Ionicons name="send" size={18} color={colors.background} />
          )}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { justifyContent: 'center', alignItems: 'center' },

  // Header section
  headerSection: { marginBottom: spacing.md },
  titleRow: { flexDirection: 'row', marginBottom: spacing.md },
  voteCol: { alignItems: 'center', marginRight: spacing.md, minWidth: 40 },
  voteCount: { color: colors.textMuted, fontSize: 16, fontWeight: '700', marginTop: 2 },
  badgeRow: { flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.xs, flexWrap: 'wrap' },
  tagBadge: { backgroundColor: colors.primary + '20', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 4 },
  tagText: { color: colors.primary, fontSize: 11, fontWeight: '600' },
  statusBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 4 },
  statusText: { fontSize: 11, fontWeight: '600' },
  title: { color: colors.text, fontSize: 18, fontWeight: '700', lineHeight: 24 },
  content: { color: colors.text, fontSize: 15, lineHeight: 22, marginBottom: spacing.sm },
  meta: { color: colors.textMuted, fontSize: 13, marginBottom: spacing.lg },

  // Comments
  commentsHeader: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.xs,
    paddingTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.tertiary + '20',
    marginBottom: spacing.sm,
  },
  commentsTitle: { color: colors.text, fontSize: 15, fontWeight: '600' },

  commentCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  commentHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.xs },
  commentAuthorRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  commentAvatar: { width: 24, height: 24, borderRadius: 12, backgroundColor: colors.tertiary + '30', justifyContent: 'center', alignItems: 'center' },
  commentAuthor: { color: colors.text, fontSize: 13, fontWeight: '600' },
  commentTime: { color: colors.textMuted, fontSize: 11 },
  commentContent: { color: colors.text, fontSize: 14, lineHeight: 20, marginBottom: spacing.xs },
  commentVoteRow: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  commentVoteCount: { color: colors.textMuted, fontSize: 13, fontWeight: '600' },

  emptyComments: { paddingVertical: spacing.lg, alignItems: 'center' },
  emptyText: { color: colors.textMuted, fontSize: 14 },

  // Input bar
  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    padding: spacing.sm,
    paddingHorizontal: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.tertiary + '20',
    backgroundColor: colors.surface,
    gap: spacing.sm,
  },
  textInput: {
    flex: 1,
    backgroundColor: colors.background,
    borderRadius: borderRadius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    color: colors.text,
    fontSize: 15,
    maxHeight: 100,
  },
  sendBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
  },
  sendBtnDisabled: { opacity: 0.4 },
});
