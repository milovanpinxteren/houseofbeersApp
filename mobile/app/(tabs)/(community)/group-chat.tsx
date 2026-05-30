import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, FlatList, TextInput, TouchableOpacity,
  ActivityIndicator, KeyboardAvoidingView, Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, router } from 'expo-router';
import { useAuth } from '../../../src/context/AuthContext';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
import { getGroupMessages, sendGroupMessage, GroupMessage } from '../../../src/api/community';

export default function GroupChatScreen() {
  const { language } = useLanguage();
  const { user } = useAuth();
  const { groupId, groupName } = useLocalSearchParams<{ groupId: string; groupName: string }>();
  const gId = parseInt(groupId || '0', 10);

  const [messages, setMessages] = useState<GroupMessage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [text, setText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const flatListRef = useRef<FlatList>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadMessages = useCallback(async () => {
    if (!gId) return;
    try {
      const data = await getGroupMessages(gId);
      setMessages(data.results);
    } catch {} finally { setIsLoading(false); }
  }, [gId]);

  useEffect(() => {
    loadMessages();
    pollRef.current = setInterval(loadMessages, 15000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [loadMessages]);

  const handleSend = async () => {
    if (!text.trim() || isSending) return;
    setIsSending(true);
    try {
      const msg = await sendGroupMessage(gId, { content: text.trim() });
      setMessages(prev => [...prev, msg]);
      setText('');
      setTimeout(() => flatListRef.current?.scrollToEnd({ animated: true }), 100);
    } catch {} finally { setIsSending(false); }
  };

  if (isLoading) {
    return <View style={[styles.container, styles.center]}><ActivityIndicator size="large" color={colors.primary} /></View>;
  }

  return (
    <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
      <View style={styles.groupHeader}>
        <Text style={styles.groupName} numberOfLines={1}>{decodeURIComponent(groupName || '')}</Text>
        <TouchableOpacity onPress={() => router.push(`/(tabs)/(community)/group-info?groupId=${gId}`)}>
          <Ionicons name="information-circle-outline" size={24} color={colors.primary} />
        </TouchableOpacity>
      </View>

      <FlatList
        ref={flatListRef}
        data={messages}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => {
          const isOwn = item.sender_id === user?.id;
          return (
            <View style={[styles.messageBubble, isOwn ? styles.ownBubble : styles.otherBubble]}>
              {!isOwn && <Text style={styles.senderName}>{item.sender_name}</Text>}
              {item.beer_title ? (
                <View style={styles.beerInMsg}>
                  <Ionicons name="beer" size={14} color={colors.primary} />
                  <Text style={styles.beerInMsgText}>{item.beer_title}</Text>
                </View>
              ) : null}
              <Text style={[styles.messageText, isOwn && styles.ownMessageText]}>{item.content}</Text>
              <Text style={[styles.messageTime, isOwn && styles.ownMessageTime]}>
                {new Date(item.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </Text>
            </View>
          );
        }}
        ListEmptyComponent={
          <View style={[styles.center, { paddingTop: 40 }]}>
            <Ionicons name="chatbubble-outline" size={36} color={colors.textMuted} />
            <Text style={styles.emptyText}>{t('community.noMessages')}</Text>
          </View>
        }
        contentContainerStyle={{ padding: spacing.md, flexGrow: 1, justifyContent: 'flex-end' }}
        onContentSizeChange={() => flatListRef.current?.scrollToEnd({ animated: false })}
      />

      <View style={styles.inputBar}>
        <TextInput style={styles.textInput} placeholder={t('community.messagePlaceholder')} placeholderTextColor={colors.textMuted}
          value={text} onChangeText={setText} maxLength={1000} multiline />
        <TouchableOpacity style={[styles.sendBtn, (!text.trim() || isSending) && styles.sendBtnDisabled]} onPress={handleSend} disabled={!text.trim() || isSending}>
          {isSending ? <ActivityIndicator size="small" color={colors.background} /> : <Ionicons name="send" size={18} color={colors.background} />}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { justifyContent: 'center', alignItems: 'center' },
  groupHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.tertiary + '20' },
  groupName: { color: colors.text, fontSize: 16, fontWeight: '700', flex: 1 },
  messageBubble: { maxWidth: '80%', borderRadius: borderRadius.md, padding: spacing.sm, paddingHorizontal: spacing.md, marginBottom: spacing.sm },
  ownBubble: { backgroundColor: colors.primary, alignSelf: 'flex-end', borderBottomRightRadius: 4 },
  otherBubble: { backgroundColor: colors.surface, alignSelf: 'flex-start', borderBottomLeftRadius: 4 },
  senderName: { color: colors.primary, fontSize: 12, fontWeight: '700', marginBottom: 2 },
  messageText: { color: colors.text, fontSize: 15, lineHeight: 20 },
  ownMessageText: { color: colors.background },
  messageTime: { color: colors.textMuted, fontSize: 10, marginTop: 4, alignSelf: 'flex-end' },
  ownMessageTime: { color: colors.background + 'aa' },
  beerInMsg: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: 4, backgroundColor: 'rgba(0,0,0,0.15)', borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2 },
  beerInMsgText: { fontSize: 12, color: colors.primary, fontWeight: '600', flex: 1 },
  inputBar: { flexDirection: 'row', alignItems: 'flex-end', padding: spacing.sm, paddingHorizontal: spacing.md, borderTopWidth: 1, borderTopColor: colors.tertiary + '20', backgroundColor: colors.surface, gap: spacing.sm },
  textInput: { flex: 1, backgroundColor: colors.background, borderRadius: borderRadius.lg, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, color: colors.text, fontSize: 15, maxHeight: 100 },
  sendBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.primary, justifyContent: 'center', alignItems: 'center' },
  sendBtnDisabled: { opacity: 0.4 },
  emptyText: { color: colors.textMuted, fontSize: 14, marginTop: spacing.sm },
});
