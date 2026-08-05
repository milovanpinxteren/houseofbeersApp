import React, { useState, useCallback, useRef } from 'react';
import {
  View, Text, StyleSheet, FlatList, TextInput, TouchableOpacity, Pressable,
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';
import { useAuth } from '../../../src/context/AuthContext';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius, fonts, type } from '../../../src/theme/colors';
import { EmptyState, Skeleton, SkeletonCard, Button, useToast } from '../../../src/components/ui';
import {
  getSuggestionDetail, getSuggestionComments, addSuggestionComment,
  deleteSuggestionComment, toggleSuggestionVote, toggleSuggestionCommentVote,
  editSuggestion, editSuggestionComment,
  Suggestion, SuggestionComment,
} from '../../../src/api/community';
import { timeAgo } from '../../../src/utils/timeAgo';

const STATUS_COLORS: Record<string, string> = {
  open: colors.primary,
  planned: colors.warning,
  done: colors.success,
  declined: colors.textMuted,
};

export default function SuggestionDetailScreen() {
  const { language } = useLanguage();
  const { user } = useAuth();
  const { showToast } = useToast();
  const { suggestionId } = useLocalSearchParams<{ suggestionId: string }>();
  const id = parseInt(suggestionId || '0', 10);

  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [comments, setComments] = useState<SuggestionComment[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [commentText, setCommentText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isEditingSuggestion, setIsEditingSuggestion] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [isSavingSuggestion, setIsSavingSuggestion] = useState(false);
  const [editingCommentId, setEditingCommentId] = useState<number | null>(null);
  const [editCommentText, setEditCommentText] = useState('');
  const [isSavingComment, setIsSavingComment] = useState(false);
  const flatListRef = useRef<FlatList>(null);

  const isStaff = (user as { is_staff?: boolean } | null)?.is_staff === true;

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [sug, commData] = await Promise.all([
        getSuggestionDetail(id),
        getSuggestionComments(id),
      ]);
      setSuggestion(sug);
      setComments(commData.comments);
    } catch {
      showToast(t('community.loadError'), 'error');
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
      showToast(t('community.commentError'), 'error');
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
          showToast(t('community.deleted'), 'success');
        } catch {
          showToast(t('community.deleteError'), 'error');
        }
      }},
    ]);
  };

  const startEditSuggestion = () => {
    if (!suggestion) return;
    setEditTitle(suggestion.title);
    setEditContent(suggestion.content);
    setIsEditingSuggestion(true);
  };

  const handleSaveSuggestion = async () => {
    if (!editTitle.trim() || !editContent.trim() || isSavingSuggestion) return;
    setIsSavingSuggestion(true);
    try {
      const updated = await editSuggestion(id, {
        title: editTitle.trim(),
        content: editContent.trim(),
      });
      setSuggestion(updated);
      setIsEditingSuggestion(false);
      showToast(t('community.editSaved'), 'success');
    } catch {
      showToast(t('community.editError'), 'error');
    } finally {
      setIsSavingSuggestion(false);
    }
  };

  const startEditComment = (comment: SuggestionComment) => {
    setEditCommentText(comment.content);
    setEditingCommentId(comment.id);
  };

  const handleSaveComment = async () => {
    if (editingCommentId == null || !editCommentText.trim() || isSavingComment) return;
    setIsSavingComment(true);
    try {
      const updated = await editSuggestionComment(editingCommentId, editCommentText.trim());
      setComments(prev => prev.map(c =>
        c.id === editingCommentId ? { ...c, content: updated.content, edited_at: updated.edited_at } : c
      ));
      setEditingCommentId(null);
      showToast(t('community.editSaved'), 'success');
    } catch {
      showToast(t('community.editError'), 'error');
    } finally {
      setIsSavingComment(false);
    }
  };

  if (isLoading) {
    return (
      <View style={[styles.container, { padding: spacing.md }]}>
        <Skeleton width="70%" height={22} />
        <Skeleton width="100%" height={14} style={{ marginTop: spacing.md }} />
        <Skeleton width="85%" height={14} style={{ marginTop: spacing.xs }} />
        <View style={{ marginTop: spacing.lg }}>
          <SkeletonCard />
          <SkeletonCard />
        </View>
      </View>
    );
  }

  if (!suggestion) {
    return (
      <View style={[styles.container, styles.centerFill]}>
        <EmptyState icon="alert-circle-outline" title={t('community.loadError')} />
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
            {/* Badges */}
            <View style={styles.badgeRow}>
              {suggestion.tag ? (
                <View style={styles.tagBadge}>
                  <Text style={styles.tagText}>{suggestion.tag}</Text>
                </View>
              ) : null}
              <View style={[styles.statusBadge, { backgroundColor: (STATUS_COLORS[suggestion.status] || colors.textMuted) + '22' }]}>
                <Text style={[styles.statusText, { color: STATUS_COLORS[suggestion.status] || colors.textMuted }]}>
                  {statusLabel(suggestion.status)}
                </Text>
              </View>
            </View>

            {/* Title + content (inline edit for author/staff) */}
            {isEditingSuggestion ? (
              <View style={styles.editWrap}>
                <TextInput
                  style={styles.editTitleInput}
                  value={editTitle}
                  onChangeText={setEditTitle}
                  maxLength={200}
                  placeholder={t('community.suggestionTitlePlaceholder')}
                  placeholderTextColor={colors.textMuted}
                />
                <TextInput
                  style={styles.editContentInput}
                  value={editContent}
                  onChangeText={setEditContent}
                  multiline
                  maxLength={1000}
                  placeholder={t('community.suggestionContentPlaceholder')}
                  placeholderTextColor={colors.textMuted}
                />
                <View style={styles.editActions}>
                  <Button label={t('cancel')} variant="ghost" size="sm" onPress={() => setIsEditingSuggestion(false)} />
                  <Button
                    label={t('save')}
                    size="sm"
                    onPress={handleSaveSuggestion}
                    loading={isSavingSuggestion}
                    disabled={!editTitle.trim() || !editContent.trim()}
                  />
                </View>
              </View>
            ) : (
              <>
                <Text style={styles.title}>{suggestion.title}</Text>
                <Text style={styles.content}>{suggestion.content}</Text>
              </>
            )}

            {/* Author + vote pill */}
            <View style={styles.metaRow}>
              <Text style={styles.meta}>
                {suggestion.author.display_name} · {timeAgo(suggestion.created_at)}
                {suggestion.edited_at ? ` · ${t('community.edited')}` : ''}
              </Text>
              {(suggestion.author.user_id === user?.id || isStaff) && !isEditingSuggestion && (
                <Pressable
                  onPress={startEditSuggestion}
                  hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                  style={({ pressed }) => [styles.editPencil, pressed && { opacity: 0.6 }]}
                >
                  <Ionicons name="pencil-outline" size={16} color={colors.textMuted} />
                </Pressable>
              )}
              <Pressable
                onPress={handleVote}
                style={({ pressed }) => [
                  styles.votePill,
                  suggestion.is_voted && styles.votePillActive,
                  pressed && { opacity: 0.85 },
                ]}
              >
                <Ionicons
                  name={suggestion.is_voted ? 'arrow-up-circle' : 'arrow-up-circle-outline'}
                  size={18}
                  color={suggestion.is_voted ? colors.background : colors.primary}
                />
                <Text style={[styles.votePillText, suggestion.is_voted && { color: colors.background }]}>
                  {suggestion.vote_count}
                </Text>
              </Pressable>
            </View>

            {/* Comments header */}
            <View style={styles.commentsHeader}>
              <Text style={styles.commentsTitle}>
                {suggestion.comment_count} {suggestion.comment_count === 1 ? t('community.comment') : t('community.comments')}
              </Text>
            </View>
          </View>
        }
        renderItem={({ item }) => {
          const canModerate = item.author.user_id === user?.id || isStaff;
          const isEditingThis = editingCommentId === item.id;
          return (
            <View style={styles.commentCard}>
              <View style={styles.commentHeader}>
                <View style={styles.commentAuthorRow}>
                  <View style={styles.commentAvatar}>
                    <Ionicons name="person" size={13} color={colors.primary} />
                  </View>
                  <Text style={styles.commentAuthor}>{item.author.display_name}</Text>
                  <Text style={styles.commentTime}>
                    {timeAgo(item.created_at)}
                    {item.edited_at ? ` · ${t('community.edited')}` : ''}
                  </Text>
                </View>
                {canModerate && !isEditingThis && (
                  <View style={styles.moderateRow}>
                    <TouchableOpacity onPress={() => startEditComment(item)} hitSlop={{ top: 12, bottom: 12, left: 8, right: 8 }}>
                      <Ionicons name="pencil-outline" size={14} color={colors.textMuted} />
                    </TouchableOpacity>
                    <TouchableOpacity onPress={() => handleDeleteComment(item.id)} hitSlop={{ top: 12, bottom: 12, left: 8, right: 12 }}>
                      <Ionicons name="trash-outline" size={14} color={colors.textMuted} />
                    </TouchableOpacity>
                  </View>
                )}
              </View>
              {isEditingThis ? (
                <View>
                  <TextInput
                    style={styles.editContentInput}
                    value={editCommentText}
                    onChangeText={setEditCommentText}
                    multiline
                    maxLength={500}
                    placeholderTextColor={colors.textMuted}
                    autoFocus
                  />
                  <View style={styles.editActions}>
                    <Button label={t('cancel')} variant="ghost" size="sm" onPress={() => setEditingCommentId(null)} />
                    <Button label={t('save')} size="sm" onPress={handleSaveComment} loading={isSavingComment} disabled={!editCommentText.trim()} />
                  </View>
                </View>
              ) : (
                <>
                  <Text style={styles.commentContent}>{item.content}</Text>
                  <Pressable
                    style={({ pressed }) => [styles.commentVoteRow, pressed && { opacity: 0.7 }]}
                    onPress={() => handleCommentVote(item.id)}
                    hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                  >
                    <Ionicons
                      name={item.is_voted ? 'arrow-up-circle' : 'arrow-up-circle-outline'}
                      size={18}
                      color={item.is_voted ? colors.primary : colors.textMuted}
                    />
                    <Text style={[styles.commentVoteCount, item.is_voted && { color: colors.primary }]}>
                      {item.vote_count}
                    </Text>
                  </Pressable>
                </>
              )}
            </View>
          );
        }}
        ListEmptyComponent={
          <EmptyState icon="chatbubble-outline" title={t('community.noComments')} />
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
  centerFill: { justifyContent: 'center' },

  // Header section
  headerSection: { marginBottom: spacing.sm },
  badgeRow: { flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.sm, flexWrap: 'wrap' },
  tagBadge: {
    backgroundColor: colors.primary + '1f',
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: borderRadius.pill,
  },
  tagText: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 1,
    textTransform: 'uppercase',
    color: colors.primary,
  },
  statusBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: borderRadius.pill,
  },
  statusText: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  title: {
    fontFamily: fonts.heading,
    fontSize: 21,
    lineHeight: 27,
    letterSpacing: 0.4,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  content: {
    fontFamily: fonts.serif,
    fontSize: 16,
    lineHeight: 24,
    color: colors.text,
    marginBottom: spacing.md,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.lg,
  },
  meta: { color: colors.textMuted, fontSize: 12, flex: 1 },
  editPencil: { marginRight: spacing.md },
  moderateRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  editWrap: { marginBottom: spacing.md },
  editTitleInput: {
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    color: colors.text,
    fontFamily: fonts.heading,
    fontSize: 17,
    marginBottom: spacing.sm,
  },
  editContentInput: {
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
  votePill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: colors.surfaceHigh,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.pill,
    minHeight: 40,
  },
  votePillActive: { backgroundColor: colors.primary },
  votePillText: {
    fontFamily: fonts.heading,
    fontSize: 14,
    letterSpacing: 0.4,
    color: colors.primary,
  },

  // Comments
  commentsHeader: {
    paddingTop: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    marginBottom: spacing.sm,
  },
  commentsTitle: { ...type.label },

  commentCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  commentHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.xs },
  commentAuthorRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flex: 1 },
  commentAvatar: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  commentAuthor: {
    fontFamily: fonts.heading,
    fontSize: 13,
    letterSpacing: 0.4,
    color: colors.text,
  },
  commentTime: { color: colors.textMuted, fontSize: 11 },
  commentContent: {
    fontFamily: fonts.serif,
    fontSize: 15,
    lineHeight: 21,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  commentVoteRow: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start' },
  commentVoteCount: { color: colors.textMuted, fontSize: 13, fontWeight: '600' },

  // Input bar
  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    padding: spacing.sm,
    paddingHorizontal: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    backgroundColor: colors.background,
    gap: spacing.sm,
  },
  textInput: {
    flex: 1,
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 4,
    color: colors.text,
    fontSize: 15,
    maxHeight: 100,
  },
  sendBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
  },
  sendBtnDisabled: { opacity: 0.4 },
});
