import React, { useState, useCallback, useEffect } from 'react';
import {
  View, Text, StyleSheet, FlatList, TextInput, TouchableOpacity, Pressable,
  ActivityIndicator, KeyboardAvoidingView, Platform, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, router } from 'expo-router';
import { useAuth } from '../../../src/context/AuthContext';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius, fonts } from '../../../src/theme/colors';
import { EmptyState, SkeletonCard, Button, useToast } from '../../../src/components/ui';
import { getComments, addComment, deleteComment, editComment, Comment } from '../../../src/api/community';

export default function PostCommentsScreen() {
  const { language } = useLanguage();
  const { user } = useAuth();
  const { showToast } = useToast();
  const isStaff = (user as { is_staff?: boolean } | null)?.is_staff === true;
  const { postId } = useLocalSearchParams<{ postId: string }>();
  const postIdNum = parseInt(postId || '0', 10);

  const [comments, setComments] = useState<Comment[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [text, setText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [replyingTo, setReplyingTo] = useState<Comment | null>(null);
  const [editing, setEditing] = useState<{ id: number; parentId: number | null } | null>(null);
  const [editText, setEditText] = useState('');
  const [isSavingEdit, setIsSavingEdit] = useState(false);

  const loadComments = useCallback(async () => {
    if (!postIdNum) return;
    try {
      const data = await getComments(postIdNum);
      setComments(data.comments);
    } catch {} finally { setIsLoading(false); }
  }, [postIdNum]);

  useEffect(() => { loadComments(); }, [loadComments]);

  const handleSend = async () => {
    if (!text.trim() || isSending) return;
    setIsSending(true);
    try {
      const parentId = replyingTo?.id;
      const comment = await addComment(postIdNum, text.trim(), parentId || undefined);
      if (parentId) {
        // Add reply to parent's replies array
        setComments(prev => prev.map(c =>
          c.id === parentId
            ? { ...c, replies: [...(c.replies || []), comment] }
            : c
        ));
      } else {
        // Add top-level comment
        setComments(prev => [...prev, { ...comment, replies: [] }]);
      }
      setText('');
      setReplyingTo(null);
    } catch {} finally { setIsSending(false); }
  };

  const handleDelete = (commentId: number, parentId?: number | null) => {
    Alert.alert(t('community.deleteComment'), '', [
      { text: t('cancel'), style: 'cancel' },
      { text: t('community.deleteComment'), style: 'destructive', onPress: async () => {
        try {
          await deleteComment(commentId);
          if (parentId) {
            setComments(prev => prev.map(c =>
              c.id === parentId
                ? { ...c, replies: (c.replies || []).filter(r => r.id !== commentId) }
                : c
            ));
          } else {
            setComments(prev => prev.filter(c => c.id !== commentId));
          }
          showToast(t('community.deleted'), 'success');
        } catch {
          showToast(t('community.deleteError'), 'error');
        }
      }},
    ]);
  };

  const startEdit = (comment: Comment, parentId?: number | null) => {
    setEditText(comment.content);
    setEditing({ id: comment.id, parentId: parentId || null });
  };

  const handleSaveEdit = async () => {
    if (!editing || !editText.trim() || isSavingEdit) return;
    setIsSavingEdit(true);
    try {
      const updated = await editComment(editing.id, editText.trim());
      const { id, parentId } = editing;
      const patch = { content: updated.content, edited_at: updated.edited_at };
      if (parentId) {
        setComments(prev => prev.map(c =>
          c.id === parentId
            ? { ...c, replies: (c.replies || []).map(r => (r.id === id ? { ...r, ...patch } : r)) }
            : c
        ));
      } else {
        setComments(prev => prev.map(c => (c.id === id ? { ...c, ...patch } : c)));
      }
      setEditing(null);
      showToast(t('community.editSaved'), 'success');
    } catch {
      showToast(t('community.editError'), 'error');
    } finally {
      setIsSavingEdit(false);
    }
  };

  const renderComment = (comment: Comment, isReply = false, parentId?: number) => {
    const isOwn = comment.author.user_id === user?.id;
    const canModerate = isOwn || isStaff;
    const isEditingThis = editing?.id === comment.id;
    return (
      <View key={comment.id} style={isReply ? styles.replyContainer : styles.commentCard}>
        {isReply && <View style={styles.replyLine} />}
        <View style={isReply ? styles.replyCard : styles.commentInner}>
          <View style={styles.commentHeader}>
            <Pressable
              style={({ pressed }) => [styles.commentAuthorRow, pressed && { opacity: 0.7 }]}
              onPress={() => router.push(`/(tabs)/(community)/member-profile?userId=${comment.author.user_id}`)}
            >
              <View style={isReply ? styles.avatarXs : styles.avatarSm}>
                <Ionicons name="person" size={isReply ? 11 : 14} color={colors.tertiary} />
              </View>
              <Text style={styles.commentAuthor}>{comment.author.display_name}</Text>
            </Pressable>
            <Text style={styles.commentTime}>
              {new Date(comment.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}
              {comment.edited_at ? ` · ${t('community.edited')}` : ''}
            </Text>
          </View>
          {isEditingThis ? (
            <View>
              <TextInput
                style={styles.editInput}
                value={editText}
                onChangeText={setEditText}
                multiline
                maxLength={500}
                placeholderTextColor={colors.textMuted}
                autoFocus
              />
              <View style={styles.editActions}>
                <Button label={t('cancel')} variant="ghost" size="sm" onPress={() => setEditing(null)} />
                <Button label={t('save')} size="sm" onPress={handleSaveEdit} loading={isSavingEdit} disabled={!editText.trim()} />
              </View>
            </View>
          ) : (
            <>
              <Text style={styles.commentText}>{comment.content}</Text>
              <View style={styles.commentActions}>
                <Pressable
                  onPress={() => setReplyingTo({ ...comment, id: parentId || comment.id })}
                  hitSlop={{ top: 10, bottom: 10, left: 6, right: 12 }}
                  style={({ pressed }) => pressed && { opacity: 0.6 }}
                >
                  <Text style={styles.replyBtn}>{t('community.reply')}</Text>
                </Pressable>
                {canModerate && (
                  <View style={styles.moderateRow}>
                    <Pressable
                      onPress={() => startEdit(comment, isReply ? parentId : null)}
                      hitSlop={{ top: 10, bottom: 10, left: 8, right: 8 }}
                      style={({ pressed }) => pressed && { opacity: 0.6 }}
                    >
                      <Ionicons name="pencil-outline" size={14} color={colors.textMuted} />
                    </Pressable>
                    <Pressable
                      onPress={() => handleDelete(comment.id, isReply ? parentId : null)}
                      hitSlop={{ top: 10, bottom: 10, left: 8, right: 6 }}
                      style={({ pressed }) => pressed && { opacity: 0.6 }}
                    >
                      <Ionicons name="trash-outline" size={14} color={colors.textMuted} />
                    </Pressable>
                  </View>
                )}
              </View>
            </>
          )}
        </View>
      </View>
    );
  };

  if (isLoading) {
    return (
      <View style={[styles.container, { padding: spacing.md }]}>
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
      <FlatList
        data={comments}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => (
          <View>
            {renderComment(item)}
            {item.replies?.map(reply => renderComment(reply, true, item.id))}
          </View>
        )}
        ListEmptyComponent={
          <EmptyState
            icon="chatbubbles-outline"
            title={t('community.noComments')}
            message={t('community.noCommentsHint')}
          />
        }
        contentContainerStyle={comments.length === 0 ? styles.emptyListContent : styles.listContent}
      />

      {replyingTo && (
        <View style={styles.replyBanner}>
          <View style={styles.replyBannerLeft}>
            <Ionicons name="return-down-forward" size={15} color={colors.primary} />
            <Text style={styles.replyBannerText}>{t('community.replyTo')} {replyingTo.author.display_name}</Text>
          </View>
          <TouchableOpacity onPress={() => setReplyingTo(null)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
            <Ionicons name="close" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        </View>
      )}

      <View style={styles.inputBar}>
        <TextInput style={styles.textInput} placeholder={replyingTo ? t('community.reply') + '...' : t('community.addComment')}
          placeholderTextColor={colors.textMuted} value={text} onChangeText={setText} maxLength={500} multiline />
        <Pressable
          style={({ pressed }) => [
            styles.sendBtn,
            (!text.trim() || isSending) && styles.sendBtnDisabled,
            pressed && { opacity: 0.85, transform: [{ scale: 0.96 }] },
          ]}
          onPress={handleSend}
          disabled={!text.trim() || isSending}
        >
          {isSending ? <ActivityIndicator size="small" color={colors.background} /> : <Ionicons name="send" size={17} color={colors.background} />}
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  listContent: { padding: spacing.md, flexGrow: 1 },
  emptyListContent: { padding: spacing.md, flexGrow: 1, justifyContent: 'center' },

  commentCard: { marginBottom: spacing.sm },
  commentInner: { backgroundColor: colors.surface, borderRadius: borderRadius.lg, padding: spacing.md },
  commentHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.sm },
  commentAuthorRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  avatarSm: { width: 28, height: 28, borderRadius: 14, backgroundColor: colors.surfaceHigh, justifyContent: 'center', alignItems: 'center' },
  avatarXs: { width: 22, height: 22, borderRadius: 11, backgroundColor: colors.surfaceHigh, justifyContent: 'center', alignItems: 'center' },
  commentAuthor: { fontFamily: fonts.heading, fontSize: 14, letterSpacing: 0.3, color: colors.text },
  commentTime: { color: colors.textMuted, fontSize: 11 },
  commentText: { fontFamily: fonts.serif, fontSize: 15, lineHeight: 21, color: colors.text },
  commentActions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: spacing.sm },
  moderateRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  editInput: {
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    color: colors.text,
    fontSize: 15,
    lineHeight: 21,
    minHeight: 60,
    textAlignVertical: 'top',
  },
  editActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm, marginTop: spacing.sm },
  replyBtn: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: colors.primary,
  },

  // Nested replies
  replyContainer: { flexDirection: 'row', marginLeft: spacing.lg, marginBottom: spacing.sm },
  replyLine: { width: 2, backgroundColor: colors.borderStrong, marginRight: spacing.sm, borderRadius: 1 },
  replyCard: { flex: 1, backgroundColor: colors.surfaceLow, borderRadius: borderRadius.md, padding: spacing.sm + 4 },

  // Reply banner
  replyBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.primary + '14',
  },
  replyBannerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flex: 1 },
  replyBannerText: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 0.5,
    color: colors.primary,
  },

  // Input
  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    padding: spacing.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
    gap: spacing.sm,
  },
  textInput: {
    flex: 1,
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    color: colors.text,
    fontSize: 15,
    maxHeight: 88,
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
