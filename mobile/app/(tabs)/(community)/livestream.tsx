import { useState, useEffect, useRef, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TextInput,
  TouchableOpacity,
  KeyboardAvoidingView,
  Platform,
  Dimensions,
  Modal,
  ActivityIndicator,
  Animated,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { useAuth } from '../../../src/context/AuthContext';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
import {
  Event,
  EventMessage,
  RaffleWinner,
  getEvent,
  joinEvent,
  getEventChat,
  sendEventMessage,
  getEventWinners,
} from '../../../src/api/events';

const POLL_INTERVAL = 3000;
const WINNER_POLL_INTERVAL = 5000;
const { width: SCREEN_WIDTH } = Dimensions.get('window');
const VIDEO_HEIGHT = (SCREEN_WIDTH * 9) / 16;

function getYouTubeEmbedUrl(url: string): string {
  const match = url.match(
    /(?:youtube\.com\/(?:watch\?v=|live\/|embed\/)|youtu\.be\/)([\w-]+)/
  );
  if (match) return `https://www.youtube.com/embed/${match[1]}?autoplay=1&playsinline=1`;
  return url;
}

function YouTubePlayer({ url }: { url: string }) {
  const embedUrl = getYouTubeEmbedUrl(url);

  if (Platform.OS === 'web') {
    return (
      <View style={styles.videoContainer}>
        <div style={{ position: 'relative', width: '100%', height: 0, paddingBottom: '56.25%' } as any}>
          <iframe
            src={embedUrl}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              height: '100%',
              border: 'none',
            } as any}
            allow="autoplay; encrypted-media; picture-in-picture"
            allowFullScreen
          />
        </div>
      </View>
    );
  }

  // Native: use WebView
  const WebView = require('react-native-webview').default;
  return (
    <View style={styles.videoContainer}>
      <WebView
        source={{ uri: embedUrl }}
        style={{ flex: 1 }}
        allowsInlineMediaPlayback
        mediaPlaybackRequiresUserAction={false}
        javaScriptEnabled
      />
    </View>
  );
}

export default function LivestreamScreen() {
  const { eventId } = useLocalSearchParams<{ eventId: string }>();
  const { user } = useAuth();
  const { language } = useLanguage();

  const [event, setEvent] = useState<Event | null>(null);
  const [messages, setMessages] = useState<EventMessage[]>([]);
  const [winners, setWinners] = useState<RaffleWinner[]>([]);
  const [messageText, setMessageText] = useState('');
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [showWinnersModal, setShowWinnersModal] = useState(false);
  const [activeViewerCount, setActiveViewerCount] = useState(0);

  // Track latest winner for banner animation
  const [bannerWinner, setBannerWinner] = useState<RaffleWinner | null>(null);
  const bannerOpacity = useRef(new Animated.Value(0)).current;
  const prevWinnerCount = useRef(0);

  const lastMessageTime = useRef<string | undefined>(undefined);
  const flatListRef = useRef<FlatList>(null);

  const numericEventId = Number(eventId);

  // Load event and join
  useEffect(() => {
    async function init() {
      try {
        const [eventData] = await Promise.all([
          getEvent(numericEventId),
          joinEvent(numericEventId),
        ]);
        setEvent(eventData);
        setActiveViewerCount(eventData.active_viewer_count || 0);
      } catch (err) {
        console.error('Failed to load event:', err);
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [numericEventId]);

  // Poll chat messages
  useEffect(() => {
    async function pollChat() {
      try {
        const data = await getEventChat(numericEventId, lastMessageTime.current);
        if (data.messages.length > 0) {
          setMessages((prev) => {
            const existingIds = new Set(prev.map((m) => m.id));
            const newMsgs = data.messages.filter((m) => !existingIds.has(m.id));
            if (newMsgs.length === 0) return prev;
            return [...prev, ...newMsgs];
          });
          lastMessageTime.current =
            data.messages[data.messages.length - 1].created_at;
        }
        setActiveViewerCount(data.active_viewer_count);
      } catch (err) {
        console.error('Chat poll error:', err);
      }
    }

    pollChat();
    const interval = setInterval(pollChat, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [numericEventId]);

  // Poll raffle winners
  useEffect(() => {
    async function pollWinners() {
      try {
        const data = await getEventWinners(numericEventId);
        setWinners(data.winners);

        // Show banner for new winners
        if (data.winners.length > prevWinnerCount.current && prevWinnerCount.current > 0) {
          const latestWinner = data.winners[0];
          setBannerWinner(latestWinner);
          Animated.sequence([
            Animated.timing(bannerOpacity, {
              toValue: 1,
              duration: 300,
              useNativeDriver: true,
            }),
            Animated.delay(5000),
            Animated.timing(bannerOpacity, {
              toValue: 0,
              duration: 300,
              useNativeDriver: true,
            }),
          ]).start(() => setBannerWinner(null));
        }
        prevWinnerCount.current = data.winners.length;
      } catch (err) {
        console.error('Winners poll error:', err);
      }
    }

    pollWinners();
    const interval = setInterval(pollWinners, WINNER_POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [numericEventId]);

  const handleSend = useCallback(async () => {
    const text = messageText.trim();
    if (!text || sending) return;

    setSending(true);
    setMessageText('');
    try {
      const msg = await sendEventMessage(numericEventId, text);
      setMessages((prev) => {
        if (prev.some((m) => m.id === msg.id)) return prev;
        return [...prev, msg];
      });
      lastMessageTime.current = msg.created_at;
    } catch (err) {
      console.error('Send error:', err);
      setMessageText(text);
    } finally {
      setSending(false);
    }
  }, [messageText, sending, numericEventId]);

  const renderMessage = useCallback(
    ({ item }: { item: EventMessage }) => {
      const isMe = item.user.user_id === user?.id;
      const isSystem = item.is_system;

      if (isSystem) {
        return (
          <View style={styles.systemMessage}>
            <Text style={styles.systemMessageText}>{item.message}</Text>
          </View>
        );
      }

      return (
        <View style={[styles.chatBubble, isMe && styles.chatBubbleMe]}>
          {!isMe && (
            <Text style={styles.chatAuthor}>{item.user.display_name}</Text>
          )}
          <Text style={styles.chatText}>{item.message}</Text>
        </View>
      );
    },
    [user?.id]
  );

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (!event) {
    return (
      <View style={styles.loadingContainer}>
        <Text style={styles.errorText}>Event not found</Text>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
    >
      {/* YouTube Player */}
      {event.youtube_url ? (
        <YouTubePlayer url={event.youtube_url} />
      ) : (
        <View style={[styles.videoContainer, styles.noVideo]}>
          <Ionicons name="videocam-off" size={40} color={colors.textMuted} />
          <Text style={styles.noVideoText}>{event.title}</Text>
        </View>
      )}

      {/* Status bar */}
      <View style={styles.statusBar}>
        <View style={styles.statusLeft}>
          {event.status === 'live' && (
            <View style={styles.liveBadge}>
              <Text style={styles.liveBadgeText}>{t('events.liveNow')}</Text>
            </View>
          )}
          <View style={styles.viewerCount}>
            <Ionicons name="eye" size={14} color={colors.textMuted} />
            <Text style={styles.viewerCountText}>
              {activeViewerCount} {t('events.watching')}
            </Text>
          </View>
        </View>
        {winners.length > 0 && (
          <TouchableOpacity
            style={styles.winnersButton}
            onPress={() => setShowWinnersModal(true)}
          >
            <Ionicons name="trophy" size={16} color={colors.warning} />
            <Text style={styles.winnersButtonText}>
              {winners.length} {t('events.winners')}
            </Text>
          </TouchableOpacity>
        )}
      </View>

      {/* Winner Banner */}
      {bannerWinner && (
        <Animated.View style={[styles.winnerBanner, { opacity: bannerOpacity }]}>
          <Ionicons name="trophy" size={20} color={colors.warning} />
          <Text style={styles.winnerBannerText}>
            {bannerWinner.user.display_name} {t('events.won')} {bannerWinner.prize_name}!
          </Text>
        </Animated.View>
      )}

      {/* Chat */}
      <FlatList
        ref={flatListRef}
        data={messages}
        renderItem={renderMessage}
        keyExtractor={(item) => String(item.id)}
        style={styles.chatList}
        contentContainerStyle={styles.chatContent}
        onContentSizeChange={() =>
          flatListRef.current?.scrollToEnd({ animated: true })
        }
        onLayout={() =>
          flatListRef.current?.scrollToEnd({ animated: false })
        }
      />

      {/* Message Input */}
      <View style={styles.inputContainer}>
        <TextInput
          style={styles.input}
          value={messageText}
          onChangeText={setMessageText}
          placeholder={t('events.chatPlaceholder')}
          placeholderTextColor={colors.textMuted}
          maxLength={500}
          multiline
          onSubmitEditing={handleSend}
          blurOnSubmit
        />
        <TouchableOpacity
          style={[styles.sendButton, (!messageText.trim() || sending) && styles.sendButtonDisabled]}
          onPress={handleSend}
          disabled={!messageText.trim() || sending}
        >
          <Ionicons
            name="send"
            size={20}
            color={messageText.trim() && !sending ? colors.background : colors.textMuted}
          />
        </TouchableOpacity>
      </View>

      {/* Winners Modal */}
      <Modal
        visible={showWinnersModal}
        animationType="slide"
        transparent
        onRequestClose={() => setShowWinnersModal(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>
                <Ionicons name="trophy" size={20} color={colors.warning} />{' '}
                {t('events.winners')}
              </Text>
              <TouchableOpacity onPress={() => setShowWinnersModal(false)}>
                <Ionicons name="close" size={24} color={colors.text} />
              </TouchableOpacity>
            </View>
            {winners.length === 0 ? (
              <Text style={styles.noWinnersText}>{t('events.noWinners')}</Text>
            ) : (
              <FlatList
                data={winners}
                keyExtractor={(item) => String(item.id)}
                renderItem={({ item }) => (
                  <View style={styles.winnerRow}>
                    <View style={styles.winnerInfo}>
                      <Ionicons name="trophy" size={16} color={colors.warning} />
                      <Text style={styles.winnerName}>
                        {item.user.display_name}
                      </Text>
                    </View>
                    <Text style={styles.winnerPrize}>{item.prize_name}</Text>
                  </View>
                )}
              />
            )}
          </View>
        </View>
      </Modal>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  loadingContainer: {
    flex: 1,
    backgroundColor: colors.background,
    justifyContent: 'center',
    alignItems: 'center',
  },
  errorText: {
    color: colors.textMuted,
    fontSize: 16,
  },

  // Video
  videoContainer: {
    width: '100%',
    backgroundColor: '#111',
    flexShrink: 0,
    overflow: 'hidden',
    ...(Platform.OS === 'web'
      ? {}
      : { aspectRatio: 16 / 9, maxHeight: VIDEO_HEIGHT }),
  },
  noVideo: {
    justifyContent: 'center',
    alignItems: 'center',
  },
  noVideoText: {
    color: colors.textMuted,
    fontSize: 16,
    marginTop: spacing.sm,
  },

  // Status bar
  statusBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.surface,
  },
  statusLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  liveBadge: {
    backgroundColor: '#e74c3c',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
  },
  liveBadgeText: {
    color: '#fff',
    fontSize: 11,
    fontWeight: '700',
  },
  viewerCount: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  viewerCountText: {
    color: colors.textMuted,
    fontSize: 13,
  },
  winnersButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: colors.surface,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: borderRadius.sm,
  },
  winnersButtonText: {
    color: colors.warning,
    fontSize: 13,
    fontWeight: '600',
  },

  // Winner banner
  winnerBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.warning + '30',
  },
  winnerBannerText: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '600',
    flex: 1,
  },

  // Chat
  chatList: {
    flex: 1,
  },
  chatContent: {
    padding: spacing.sm,
    paddingBottom: spacing.md,
  },
  chatBubble: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.sm,
    padding: spacing.sm,
    marginBottom: spacing.xs,
    maxWidth: '85%',
    alignSelf: 'flex-start',
  },
  chatBubbleMe: {
    backgroundColor: colors.primary + '20',
    alignSelf: 'flex-end',
  },
  chatAuthor: {
    color: colors.primary,
    fontSize: 12,
    fontWeight: '600',
    marginBottom: 2,
  },
  chatText: {
    color: colors.text,
    fontSize: 14,
    lineHeight: 20,
  },
  systemMessage: {
    alignItems: 'center',
    paddingVertical: spacing.xs,
  },
  systemMessageText: {
    color: colors.warning,
    fontSize: 13,
    fontWeight: '600',
  },

  // Input
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.surface,
    backgroundColor: colors.background,
  },
  input: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: Platform.OS === 'ios' ? 10 : 8,
    color: colors.text,
    fontSize: 14,
    maxHeight: 100,
  },
  sendButton: {
    backgroundColor: colors.primary,
    width: 36,
    height: 36,
    borderRadius: 18,
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: spacing.sm,
  },
  sendButtonDisabled: {
    backgroundColor: colors.surface,
  },

  // Winners Modal
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'flex-end',
  },
  modalContent: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: borderRadius.lg,
    borderTopRightRadius: borderRadius.lg,
    maxHeight: '60%',
    paddingBottom: spacing.xl,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.tertiary + '20',
  },
  modalTitle: {
    color: colors.text,
    fontSize: 18,
    fontWeight: '600',
  },
  noWinnersText: {
    color: colors.textMuted,
    fontSize: 14,
    textAlign: 'center',
    padding: spacing.xl,
  },
  winnerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.tertiary + '10',
  },
  winnerInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  winnerName: {
    color: colors.text,
    fontSize: 15,
    fontWeight: '500',
  },
  winnerPrize: {
    color: colors.primary,
    fontSize: 13,
  },
});
