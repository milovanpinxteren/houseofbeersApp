import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import {
  View, Text, StyleSheet, FlatList, KeyboardAvoidingView, Platform, Pressable,
  ActivityIndicator, NativeSyntheticEvent, NativeScrollEvent,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import * as Clipboard from 'expo-clipboard';
import { useAuth } from '../context/AuthContext';
import { useLanguage } from '../context/LanguageContext';
import { t } from '../i18n';
import { colors, spacing, borderRadius, fonts } from '../theme/colors';
import { ContentColumn, EmptyState, Skeleton, useToast } from './ui';
import { PaginatedResponse, ReactionMap, ReactionResponse } from '../api/community';
import {
  Avatar, DaySeparator, MessageBubble, MessageComposer, ReactionSheet,
  GroupedPosition,
} from './chat';

export interface ChatMessage {
  id: number;
  sender_id: number;
  sender_name?: string;
  content: string;
  beer_title?: string;
  created_at: string;
  reactions?: ReactionMap;
  mine?: string[];
  /** Client-only: optimistic message awaiting the server round-trip. */
  pending?: boolean;
}

interface ChatScreenProps {
  title: string;
  /** Fetch a page of messages. Page 1 = newest 30, higher pages = older. */
  fetchMessages: (page: number) => Promise<PaginatedResponse<ChatMessage>>;
  onSend: (content: string) => Promise<ChatMessage>;
  onDeleteMessage: (messageId: number) => Promise<void>;
  /** Toggle an emoji reaction. Omit to disable reactions entirely. */
  onReact?: (messageId: number, emoji: string) => Promise<ReactionResponse>;
  markRead?: () => Promise<void>;
  showSenderNames?: boolean;
  headerAction?: React.ReactNode;
}

const RUN_WINDOW_MS = 5 * 60 * 1000;

function sameDay(a: string, b: string): boolean {
  const da = new Date(a); const db = new Date(b);
  return da.getFullYear() === db.getFullYear()
    && da.getMonth() === db.getMonth()
    && da.getDate() === db.getDate();
}

function sameRun(a: ChatMessage, b: ChatMessage): boolean {
  return a.sender_id === b.sender_id
    && Math.abs(new Date(a.created_at).getTime() - new Date(b.created_at).getTime()) < RUN_WINDOW_MS
    && sameDay(a.created_at, b.created_at);
}

type Row =
  | {
      kind: 'msg';
      msg: ChatMessage;
      grouped: GroupedPosition;
      showTime: boolean;
      authorName?: string;
      avatarName?: string;
      avatarUserId?: number;
      showAvatar?: boolean;
    }
  | { kind: 'day'; date: string; key: string };

function LoadingBubbles() {
  // Shimmer bubbles alternating sides, echoing a real conversation shape.
  const rows = [
    { w: 62, own: false }, { w: 44, own: true }, { w: 74, own: false },
    { w: 38, own: false }, { w: 56, own: true }, { w: 68, own: false },
  ];
  return (
    <View style={styles.skeletonWrap}>
      {rows.map((r, i) => (
        <Skeleton
          key={i}
          width={`${r.w}%`}
          height={42}
          radius={16}
          style={{ alignSelf: r.own ? 'flex-end' : 'flex-start', marginBottom: spacing.sm }}
        />
      ))}
    </View>
  );
}

export default function ChatScreen({
  title, fetchMessages, onSend, onDeleteMessage, onReact, markRead,
  showSenderNames, headerAction,
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
  const [unreadCount, setUnreadCount] = useState(0);
  const [sheetMsg, setSheetMsg] = useState<ChatMessage | null>(null);
  const flatListRef = useRef<FlatList<Row>>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  const inFlightRef = useRef(false);
  const hasMoreRef = useRef(false);
  const nextPageRef = useRef(2);
  const atBottomRef = useRef(true);
  // Message ids with an in-flight reaction toggle: the poll merge must not
  // clobber their optimistic reactions with stale server state.
  const pendingReactionsRef = useRef<Set<number>>(new Set());

  useEffect(() => { messagesRef.current = messages; }, [messages]);

  const patchMessage = useCallback((id: number, patch: Partial<ChatMessage>) => {
    setMessages(prev => prev.map(m => (m.id === id ? { ...m, ...patch } : m)));
  }, []);

  const loadLatest = useCallback(async (isPolling = false) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const data = await fetchMessages(1);
      const prevIds = new Set(messagesRef.current.map(m => m.id));
      const newFromOthers = data.results.filter(
        m => !prevIds.has(m.id) && m.sender_id !== user?.id
      ).length;
      const hadNew = data.results.some(m => !prevIds.has(m.id));
      setMessages(prev => {
        let next: ChatMessage[];
        if (isPolling && prev.length > 0) {
          if (data.results.length === 0) return prev;
          // Merge: page 1 replaces the newest window (picks up new messages,
          // reaction changes, and drops messages deleted within it); keep
          // older messages — and negative-id optimistic temps — below it.
          const minId = Math.min(...data.results.map(m => m.id));
          const pageIds = new Set(data.results.map(m => m.id));
          next = [
            ...data.results,
            ...prev.filter(m => m.id < minId && !pageIds.has(m.id)),
          ];
        } else {
          next = data.results;
        }
        // In-flight reaction toggles win over the (possibly stale) poll data.
        if (pendingReactionsRef.current.size > 0) {
          next = next.map(m => {
            if (!pendingReactionsRef.current.has(m.id)) return m;
            const local = prev.find(p => p.id === m.id);
            return local ? { ...m, reactions: local.reactions, mine: local.mine } : m;
          });
        }
        return next;
      });
      if (isPolling && newFromOthers > 0 && !atBottomRef.current) {
        setUnreadCount(c => c + newFromOthers);
      }
      if (!isPolling) {
        hasMoreRef.current = !!data.next;
        nextPageRef.current = 2;
      }
      // Mark read once on open, then only when something new actually arrived.
      if (markRead && (!isPolling || hadNew)) markRead().catch(() => {});
    } catch {
      if (!isPolling) showToast(t('community.loadError'), 'error');
    } finally {
      inFlightRef.current = false;
      setIsLoading(false);
    }
  }, [fetchMessages, markRead, user?.id, showToast]);

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

  const scrollToBottom = useCallback(() => {
    atBottomRef.current = true;
    setUnreadCount(0);
    flatListRef.current?.scrollToOffset({ offset: 0, animated: true });
  }, []);

  const handleScroll = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    // Inverted list: offset 0 = newest message = visual bottom.
    const atBottom = e.nativeEvent.contentOffset.y <= 40;
    atBottomRef.current = atBottom;
    if (atBottom) setUnreadCount(0);
  }, []);

  const handleSend = async () => {
    const content = text.trim();
    if (!content || isSending) return;
    setIsSending(true);
    // Optimistic: show the message immediately with a pending glyph.
    const tempId = -Date.now();
    const temp: ChatMessage = {
      id: tempId,
      sender_id: user?.id ?? 0,
      content,
      created_at: new Date().toISOString(),
      pending: true,
    };
    setMessages(prev => [temp, ...prev]);
    setText('');
    scrollToBottom();
    try {
      const msg = await onSend(content);
      setMessages(prev => {
        const withoutTemp = prev.filter(m => m.id !== tempId);
        // The poll may have delivered the real message already.
        return withoutTemp.some(m => m.id === msg.id) ? withoutTemp : [msg, ...withoutTemp];
      });
    } catch {
      setMessages(prev => prev.filter(m => m.id !== tempId));
      setText(content);
      showToast(t('community.messageError'), 'error');
    } finally {
      setIsSending(false);
    }
  };

  const handleToggleReaction = useCallback(async (msg: ChatMessage, emoji: string) => {
    if (!onReact || msg.id < 0) return;
    const snapshot = { reactions: msg.reactions, mine: msg.mine };
    const mineSet = new Set(msg.mine ?? []);
    const reactions: ReactionMap = { ...(msg.reactions ?? {}) };
    if (mineSet.has(emoji)) {
      mineSet.delete(emoji);
      const next = (reactions[emoji] ?? 1) - 1;
      if (next > 0) reactions[emoji] = next; else delete reactions[emoji];
    } else {
      mineSet.add(emoji);
      reactions[emoji] = (reactions[emoji] ?? 0) + 1;
    }
    pendingReactionsRef.current.add(msg.id);
    patchMessage(msg.id, {
      reactions: Object.keys(reactions).length ? reactions : undefined,
      mine: mineSet.size ? [...mineSet] : undefined,
    });
    try {
      const res = await onReact(msg.id, emoji);
      patchMessage(msg.id, {
        reactions: Object.keys(res.reactions).length ? res.reactions : undefined,
        mine: res.mine.length ? res.mine : undefined,
      });
    } catch {
      patchMessage(msg.id, snapshot);
      showToast(t('community.reactError'), 'error');
    } finally {
      pendingReactionsRef.current.delete(msg.id);
    }
  }, [onReact, patchMessage, showToast]);

  const handleCopy = useCallback(async (msg: ChatMessage) => {
    try {
      await Clipboard.setStringAsync(msg.content);
      showToast(t('community.copied'), 'success');
    } catch {}
  }, [showToast]);

  const handleDelete = useCallback(async (msg: ChatMessage) => {
    try {
      await onDeleteMessage(msg.id);
      setMessages(prev => prev.filter(m => m.id !== msg.id));
      showToast(t('community.deleted'), 'success');
    } catch {
      showToast(t('community.deleteError'), 'error');
    }
  }, [onDeleteMessage, showToast]);

  // Derived rows: day separators + run grouping. Array is newest-first; a
  // row's chronological predecessor sits at index + 1.
  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      const chronoPrev = messages[i + 1];
      const chronoNext = i > 0 ? messages[i - 1] : undefined;
      const hasPrev = !!chronoPrev && sameRun(msg, chronoPrev);
      const hasNext = !!chronoNext && sameRun(msg, chronoNext);
      const grouped: GroupedPosition =
        hasPrev && hasNext ? 'middle' : hasPrev ? 'last' : hasNext ? 'first' : 'single';
      const isOwn = msg.sender_id === user?.id;
      const showAuthor = !!showSenderNames && !isOwn
        && (grouped === 'first' || grouped === 'single');
      out.push({
        kind: 'msg',
        msg,
        grouped,
        showTime: grouped === 'last' || grouped === 'single',
        authorName: showAuthor ? msg.sender_name : undefined,
        avatarName: showSenderNames && !isOwn ? (msg.sender_name ?? '') : undefined,
        avatarUserId: showSenderNames && !isOwn ? msg.sender_id : undefined,
        showAvatar: showSenderNames && !isOwn
          && (grouped === 'last' || grouped === 'single'),
      });
      // Day pill above the chronologically first message of each day. In an
      // inverted list "above" means a higher array index, i.e. right here.
      if (!chronoPrev || !sameDay(msg.created_at, chronoPrev.created_at)) {
        out.push({ kind: 'day', date: msg.created_at, key: `day-${msg.created_at.slice(0, 10)}-${msg.id}` });
      }
    }
    return out;
  }, [messages, user?.id, showSenderNames]);

  const sheetIsOwn = sheetMsg?.sender_id === user?.id;

  if (isLoading) {
    return (
      <View style={styles.container}>
        <ContentColumn maxWidth={CHAT_MAX_WIDTH}>
          <View style={styles.chatHeader}>
            <Avatar name={title} size="sm" style={styles.headerAvatar} />
            <Text style={styles.chatTitle} numberOfLines={1}>{title}</Text>
            {headerAction}
          </View>
          <LoadingBubbles />
        </ContentColumn>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
      <ContentColumn maxWidth={CHAT_MAX_WIDTH}>
      <View style={styles.chatHeader}>
        <Avatar name={title} size="sm" style={styles.headerAvatar} />
        <Text style={styles.chatTitle} numberOfLines={1}>{title}</Text>
        {headerAction}
      </View>

      <View style={styles.listWrap}>
        <FlatList
          ref={flatListRef}
          data={rows}
          inverted
          keyExtractor={(item) => (item.kind === 'msg' ? `m${item.msg.id}` : item.key)}
          onScroll={handleScroll}
          scrollEventThrottle={32}
          maintainVisibleContentPosition={{ minIndexForVisible: 0, autoscrollToTopThreshold: 80 }}
          renderItem={({ item }) => {
            if (item.kind === 'day') return <DaySeparator date={item.date} />;
            const { msg } = item;
            const isOwn = msg.sender_id === user?.id;
            return (
              <MessageBubble
                isOwn={isOwn}
                text={msg.content}
                createdAt={msg.created_at}
                authorName={item.authorName}
                avatarName={item.avatarName}
                avatarUserId={item.avatarUserId}
                showAvatar={item.showAvatar}
                beerTitle={msg.beer_title}
                pending={msg.pending}
                showStatus={isOwn}
                grouped={item.grouped}
                showTime={item.showTime}
                reactions={msg.reactions}
                mine={msg.mine}
                onToggleReaction={onReact ? (emoji) => handleToggleReaction(msg, emoji) : undefined}
                onLongPress={msg.pending ? undefined : () => setSheetMsg(msg)}
              />
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

        {unreadCount > 0 && (
          <Pressable
            style={({ pressed }) => [styles.unreadPill, pressed && { opacity: 0.85 }]}
            onPress={scrollToBottom}
          >
            <Ionicons name="arrow-down" size={13} color={colors.background} />
            <Text style={styles.unreadPillText}>
              {unreadCount === 1
                ? t('community.newMessage')
                : t('community.newMessages', { count: unreadCount })}
            </Text>
          </Pressable>
        )}
      </View>

      <MessageComposer
        value={text}
        onChangeText={setText}
        onSend={handleSend}
        sending={isSending}
        maxLength={1000}
        placeholder={t('community.messagePlaceholder')}
      />

      <ReactionSheet
        visible={sheetMsg !== null}
        onClose={() => setSheetMsg(null)}
        mine={sheetMsg?.mine}
        onReact={(emoji) => { if (sheetMsg) handleToggleReaction(sheetMsg, emoji); }}
        onCopy={() => { if (sheetMsg) handleCopy(sheetMsg); }}
        onDelete={sheetMsg && (sheetIsOwn || isStaff)
          ? () => handleDelete(sheetMsg)
          : undefined}
      />
      </ContentColumn>
    </KeyboardAvoidingView>
  );
}

// Wide-screen cap for the message column (desktop PWA); inert on phones.
const CHAT_MAX_WIDTH = 760;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { justifyContent: 'center', alignItems: 'center' },
  skeletonWrap: { flex: 1, justifyContent: 'flex-end', padding: spacing.md },
  listWrap: { flex: 1 },
  chatHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    minHeight: 48,
    gap: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  headerAvatar: { marginRight: 2 },
  chatTitle: {
    fontFamily: fonts.heading,
    fontSize: 17,
    letterSpacing: 0.4,
    color: colors.text,
    flex: 1,
  },
  unreadPill: {
    position: 'absolute',
    bottom: spacing.sm,
    alignSelf: 'center',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: borderRadius.pill,
  },
  unreadPillText: {
    fontFamily: fonts.heading,
    color: colors.background,
    fontSize: 12,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
  },
  emptyFlip: { transform: [{ scaleY: -1 }] },
});
