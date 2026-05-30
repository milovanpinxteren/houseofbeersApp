import React, { useState, useCallback, useEffect } from 'react';
import {
  View, Text, StyleSheet, FlatList, TextInput, TouchableOpacity,
  ActivityIndicator, KeyboardAvoidingView, Platform, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, router } from 'expo-router';
import { useAuth } from '../../../src/context/AuthContext';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
import { getComments, addComment, deleteComment, Comment } from '../../../src/api/community';

export default function PostCommentsScreen() {
  const { language } = useLanguage();
  const { user } = useAuth();
  const { postId } = useLocalSearchParams<{ postId: string }>();
  const postIdNum = parseInt(postId || '0', 10);

  const [comments, setComments] = useState<Comment[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [text, setText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [replyingTo, setReplyingTo] = useState<Comment | null>(null);

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
    Alert.alert(t('community.deletePost'), '', [
      { text: t('cancel'), style: 'cancel' },
      { text: t('community.deletePost'), style: 'destructive', onPress: async () => {
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
        } catch {}
      }},
    ]);
  };

  const renderComment = (comment: Comment, isReply = false, parentId?: number) => {
    const isOwn = comment.author.user_id === user?.id;
    return (
      <View key={comment.id} style={isReply ? styles.replyContainer : styles.commentCard}>
        {isReply && <View style={styles.replyLine} />}
        <View style={isReply ? styles.replyCard : styles.commentInner}>
          <View style={styles.commentHeader}>
            <TouchableOpacity
              style={styles.commentAuthorRow}
              onPress={() => router.push(`/(tabs)/(community)/member-profile?userId=${comment.author.user_id}`)}
            >
              <View style={isReply ? styles.avatarXs : styles.avatarSm}>
                <Ionicons name="person" size={isReply ? 10 : 14} color={colors.textMuted} />
              </View>
              <Text style={styles.commentAuthor}>{comment.author.display_name}</Text>
            </TouchableOpacity>
            <Text style={styles.commentTime}>
              {new Date(comment.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}
            </Text>
          </View>
          <Text style={styles.commentText}>{comment.content}</Text>
          <View style={styles.commentActions}>
            <TouchableOpacity onPress={() => setReplyingTo({ ...comment, id: parentId || comment.id })}>
              <Text style={styles.replyBtn}>{t('community.reply')}</Text>
            </TouchableOpacity>
            {isOwn && (
              <TouchableOpacity onPress={() => handleDelete(comment.id, isReply ? parentId : null)}>
                <Ionicons name="trash-outline" size={14} color={colors.textMuted} />
              </TouchableOpacity>
            )}
          </View>
        </View>
      </View>
    );
  };

  if (isLoading) {
    return <View style={[styles.container, styles.center]}><ActivityIndicator size="large" color={colors.primary} /></View>;
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
          <View style={[styles.center, { paddingTop: 40 }]}>
            <Ionicons name="chatbubble-outline" size={36} color={colors.textMuted} />
            <Text style={styles.emptyText}>{t('community.addComment')}</Text>
          </View>
        }
        contentContainerStyle={{ padding: spacing.md, flexGrow: 1 }}
      />

      {replyingTo && (
        <View style={styles.replyBanner}>
          <Text style={styles.replyBannerText}>{t('community.replyTo')} {replyingTo.author.display_name}</Text>
          <TouchableOpacity onPress={() => setReplyingTo(null)}>
            <Ionicons name="close" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        </View>
      )}

      <View style={styles.inputBar}>
        <TextInput style={styles.textInput} placeholder={replyingTo ? t('community.reply') + '...' : t('community.addComment')}
          placeholderTextColor={colors.textMuted} value={text} onChangeText={setText} maxLength={500} multiline />
        <TouchableOpacity style={[styles.sendBtn, (!text.trim() || isSending) && styles.sendBtnDisabled]}
          onPress={handleSend} disabled={!text.trim() || isSending}>
          {isSending ? <ActivityIndicator size="small" color={colors.background} /> : <Ionicons name="send" size={16} color={colors.background} />}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { justifyContent: 'center', alignItems: 'center' },
  commentCard: { marginBottom: spacing.sm },
  commentInner: { backgroundColor: colors.surface, borderRadius: borderRadius.sm, padding: spacing.md },
  commentHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.xs },
  commentAuthorRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  avatarSm: { width: 24, height: 24, borderRadius: 12, backgroundColor: colors.tertiary + '30', justifyContent: 'center', alignItems: 'center' },
  avatarXs: { width: 20, height: 20, borderRadius: 10, backgroundColor: colors.tertiary + '30', justifyContent: 'center', alignItems: 'center' },
  commentAuthor: { color: colors.text, fontSize: 13, fontWeight: '600' },
  commentTime: { color: colors.textMuted, fontSize: 11 },
  commentText: { color: colors.text, fontSize: 14, lineHeight: 20 },
  commentActions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: spacing.xs },
  replyBtn: { color: colors.primary, fontSize: 12, fontWeight: '600' },

  // Nested replies
  replyContainer: { flexDirection: 'row', marginLeft: 24, marginBottom: spacing.xs },
  replyLine: { width: 2, backgroundColor: colors.tertiary + '40', marginRight: spacing.sm, borderRadius: 1 },
  replyCard: { flex: 1, backgroundColor: colors.surface, borderRadius: borderRadius.sm, padding: spacing.sm },

  // Reply banner
  replyBanner: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.md, paddingVertical: spacing.sm, backgroundColor: colors.primary + '15', borderTopWidth: 1, borderTopColor: colors.tertiary + '20' },
  replyBannerText: { color: colors.primary, fontSize: 13, fontWeight: '600' },

  // Input
  inputBar: { flexDirection: 'row', alignItems: 'flex-end', padding: spacing.sm, paddingHorizontal: spacing.md, borderTopWidth: 1, borderTopColor: colors.tertiary + '20', backgroundColor: colors.surface, gap: spacing.sm },
  textInput: { flex: 1, backgroundColor: colors.background, borderRadius: borderRadius.lg, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, color: colors.text, fontSize: 15, maxHeight: 80 },
  sendBtn: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.primary, justifyContent: 'center', alignItems: 'center' },
  sendBtnDisabled: { opacity: 0.4 },
  emptyText: { color: colors.textMuted, fontSize: 14, marginTop: spacing.sm },
});
