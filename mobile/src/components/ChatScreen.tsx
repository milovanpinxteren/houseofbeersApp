import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, FlatList, TextInput, TouchableOpacity,
  ActivityIndicator, KeyboardAvoidingView, Platform, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import { useAuth } from '../context/AuthContext';
import { useLanguage } from '../context/LanguageContext';
import { t } from '../i18n';
import { colors, spacing, borderRadius, fonts } from '../theme/colors';
import { EmptyState, useToast } from './ui';
import { PaginatedResponse } from '../api/community';

export interface ChatMessage {
  id: number;
  sender_id: number;
  sender_name?: string;
  content: string;
  beer_title?: string;
  created_at: string;
}

interface ChatScreenProps {
  title: string;
  /** Fetch a page of messages. Page 1 = newest 30, higher pages = older. */
  fetchMessages: (page: number) => Promise<PaginatedResponse<ChatMessage>>;
  onSend: (content: string) => Promise<ChatMessage>;
  onDeleteMessage: (messageId: number) => Promise<void>;
  markRead?: () => Promise<void>;
  showSenderNames?: boolean;
  headerAction?: React.ReactNode;
}

export default function ChatScreen({
  title, fetchMessages, onSend, onDeleteMessage, markRead, showSenderNames, headerAction,
}: ChatScreenProps) {
  const { language } = useLanguage();
  const { user } = useAuth();
  const { showToast } = useToast();
  const isStaff = (user as { is_staff?: boolean } | null)?.is_staff === true;

  // Messages are kept newest-first (matches API order + inverted FlatList).
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [text, setText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const flatListRef = useRef<FlatList<ChatMessage>>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  const inFlightRef = useRef(false);
  const hasMoreRef = useRef(false);
  const nextPageRef = useRef(2);

  useEffect(() => { messagesRef.current = messages; }, [messages]);

  const loadLatest = useCallback(async (isPolling = false) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const data = await fetchMessages(1);
      const hadNew = data.results.some(m => !messagesRef.current.some(p => p.id === m.id));
      setMessages(prev => {
        if (isPolling && prev.length > 0) {
          if (data.results.length === 0) return prev;
          // Merge: page 1 replaces the newest window (picks up new messages and
          // drops messages deleted within it); keep older messages below it.
          const minId = Math.min(...data.results.map(m => m.id));
          return [...data.results, ...prev.filter(m => m.id < minId)];
        }
        return data.results;
      });
      if (!isPolling) {
        hasMoreRef.current = !!data.next;
        nextPageRef.current = 2;
      }
      // Mark read once on open, then only when something new actually arrived.
      if (markRead && (!isPolling || hadNew)) markRead().catch(() => {});
    } catch {
      if (!isPolling) Alert.alert(t('error'), t('community.loadError'));
    } finally {
      inFlightRef.current = false;
      setIsLoading(false);
    }
  }, [fetchMessages, markRead]);

  // Load on focus and poll every 10s while focused; stop on blur/unmount.
  useFocusEffect(
    useCallback(() => {
      loadLatest(false);
      const interval = setInterval(() => loadLatest(true), 10000);
      return () => clearInterval(interval);
    }, [loadLatest])
  );

  const loadOlder = useCallback(async () => {
    if (!hasMoreRef.current || inFlightRef.current) return;
    inFlightRef.current = true;
    setIsLoadingMore(true);
    try {
      const data = await fetchMessages(nextPageRef.current);
      setMessages(prev => {
        const existing = new Set(prev.map(m => m.id));
        return [...prev, ...data.results.filter(m => !existing.has(m.id))];
      });
      hasMoreRef.current = !!data.next;
      nextPageRef.current += 1;
    } catch {} finally {
      inFlightRef.current = false;
      setIsLoadingMore(false);
    }
  }, [fetchMessages]);

  const handleSend = async () => {
    if (!text.trim() || isSending) return;
    setIsSending(true);
    try {
      const msg = await onSend(text.trim());
      setMessages(prev => [msg, ...prev]);
      setText('');
      setTimeout(() => flatListRef.current?.scrollToOffset({ offset: 0, animated: true }), 100);
    } catch {
      Alert.alert(t('error'), t('community.messageError'));
    } finally {
      setIsSending(false);
    }
  };

  const handleLongPress = (message: ChatMessage) => {
    // Own messages, or any message when the user is staff (moderation)
    if (message.sender_id !== user?.id && !isStaff) return;
    Alert.alert(t('community.deleteMessage'), t('community.deleteMessageConfirm'), [
      { text: t('cancel'), style: 'cancel' },
      { text: t('community.deleteMessage'), style: 'destructive', onPress: async () => {
        try {
          await onDeleteMessage(message.id);
          setMessages(prev => prev.filter(m => m.id !== message.id));
          showToast(t('community.deleted'), 'success');
        } catch {
          showToast(t('community.deleteError'), 'error');
        }
      }},
    ]);
  };

  if (isLoading) {
    return <View style={[styles.container, styles.center]}><ActivityIndicator size="large" color={colors.primary} /></View>;
  }

  return (
    <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
      <View style={styles.chatHeader}>
        <Text style={styles.chatTitle} numberOfLines={1}>{title}</Text>
        {headerAction}
      </View>

      <FlatList
        ref={flatListRef}
        data={messages}
        inverted
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => {
          const isOwn = item.sender_id === user?.id;
          return (
            <TouchableOpacity
              activeOpacity={isOwn || isStaff ? 0.7 : 1}
              onLongPress={() => handleLongPress(item)}
              delayLongPress={400}
              style={[styles.messageBubble, isOwn ? styles.ownBubble : styles.otherBubble]}
            >
              {showSenderNames && !isOwn && item.sender_name ? (
                <Text style={styles.senderName}>{item.sender_name}</Text>
              ) : null}
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
            </TouchableOpacity>
          );
        }}
        ListEmptyComponent={
          // Inverted lists render children flipped — flip the empty state back.
          <View style={[styles.center, styles.emptyFlip, { paddingTop: 40 }]}>
            <EmptyState icon="chatbubble-outline" title={t('community.noMessages')} />
          </View>
        }
        onEndReached={loadOlder}
        onEndReachedThreshold={0.3}
        ListFooterComponent={isLoadingMore ? <ActivityIndicator color={colors.primary} style={{ padding: spacing.md }} /> : null}
        contentContainerStyle={{ padding: spacing.md, flexGrow: 1 }}
      />

      <View style={styles.inputBar}>
        <TextInput
          style={styles.textInput}
          placeholder={t('community.messagePlaceholder')}
          placeholderTextColor={colors.textMuted}
          value={text}
          onChangeText={setText}
          maxLength={1000}
          multiline
        />
        <TouchableOpacity
          style={[styles.sendBtn, (!text.trim() || isSending) && styles.sendBtnDisabled]}
          onPress={handleSend}
          disabled={!text.trim() || isSending}
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
  chatHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    minHeight: 48,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  chatTitle: {
    fontFamily: fonts.heading,
    fontSize: 17,
    letterSpacing: 0.4,
    color: colors.text,
    flex: 1,
  },
  messageBubble: {
    maxWidth: '80%',
    borderRadius: 16,
    paddingVertical: spacing.sm + 2,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  ownBubble: { backgroundColor: colors.primary, alignSelf: 'flex-end', borderBottomRightRadius: 4 },
  otherBubble: { backgroundColor: colors.surfaceHigh, alignSelf: 'flex-start', borderBottomLeftRadius: 4 },
  senderName: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 0.6,
    color: colors.primary,
    marginBottom: 2,
  },
  messageText: { color: colors.text, fontSize: 15, lineHeight: 21 },
  ownMessageText: { color: colors.background },
  messageTime: { color: colors.textMuted, fontSize: 10, marginTop: 4, alignSelf: 'flex-end' },
  ownMessageTime: { color: colors.background + '99' },
  beerInMsg: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginBottom: 4,
    backgroundColor: 'rgba(0,0,0,0.18)',
    borderRadius: borderRadius.sm,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  beerInMsgText: { fontSize: 12, color: colors.primary, fontWeight: '600', flex: 1 },
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
  emptyFlip: { transform: [{ scaleY: -1 }] },
});
