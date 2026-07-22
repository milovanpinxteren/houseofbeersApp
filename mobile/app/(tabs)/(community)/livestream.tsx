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
  Pressable,
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
  AuctionItem,
  getEvent,
  joinEvent,
  sendEventMessage,
  pollEvent,
} from '../../../src/api/events';

const POLL_INTERVAL = 3000;
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

  // Auction
  const [auctionItem, setAuctionItem] = useState<AuctionItem | null>(null);
  const [soldBanner, setSoldBanner] = useState<AuctionItem | null>(null);
  const soldBannerOpacity = useRef(new Animated.Value(0)).current;
  const prevAuctionItemId = useRef<number | null>(null);

  // Raffle animation
  const [raffleAnimation, setRaffleAnimation] = useState<{
    prizeName: string;
    winnerName: string;
    isCurrentUser: boolean;
    viewerNames: string[];
  } | null>(null);
  const [shuffleName, setShuffleName] = useState('');
  const [animationPhase, setAnimationPhase] = useState<'shuffling' | 'revealing' | 'done'>('shuffling');
  const raffleOverlayOpacity = useRef(new Animated.Value(0)).current;
  const winnerScale = useRef(new Animated.Value(0.5)).current;
  const youWonOpacity = useRef(new Animated.Value(0)).current;
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

  // Combined poll: chat, winners, auction — single request every 3s
  // Heartbeat (presence update) every 20th poll (~60s)
  const pollCount = useRef(0);
  const auctionItemRef = useRef<AuctionItem | null>(null);

  useEffect(() => {
    async function doPoll() {
      try {
        pollCount.current += 1;
        const isHeartbeat = pollCount.current % 20 === 1; // First poll + every 60s

        const data = await pollEvent(
          numericEventId,
          lastMessageTime.current,
          isHeartbeat,
          prevWinnerCount.current,
        );

        // Chat messages
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

        // Viewer count (only on heartbeat)
        if (data.active_viewer_count !== undefined) {
          setActiveViewerCount(data.active_viewer_count);
        }

        // Winner changes — full data + viewer names included by backend
        if (data.winners && data.winner_count > prevWinnerCount.current && !raffleAnimation) {
          setWinners(data.winners);
          const latestWinner = data.winners[0];
          const isCurrentUser = latestWinner.user.user_id === user?.id;

          const names = data.viewer_names?.map((v) => v.display_name) || [];
          const shuffleNames = names.length >= 3 ? names : [
            latestWinner.user.display_name,
            ...names,
            'Viewer', 'Guest', 'Beer Fan',
          ];

          startRaffleAnimation({
            prizeName: latestWinner.prize_name,
            winnerName: latestWinner.user.display_name,
            isCurrentUser,
            viewerNames: shuffleNames,
          });
        }
        prevWinnerCount.current = data.winner_count;

        // Auction item (included for auction events)
        if (data.auction_item !== undefined) {
          const newItem = data.auction_item;
          const prevItem = auctionItemRef.current;

          // Detect sold transition
          if (newItem && newItem.status === 'sold' && prevItem?.status === 'active' && newItem.id === prevItem.id) {
            setSoldBanner(newItem);
            Animated.sequence([
              Animated.timing(soldBannerOpacity, {
                toValue: 1,
                duration: 300,
                useNativeDriver: true,
              }),
              Animated.delay(5000),
              Animated.timing(soldBannerOpacity, {
                toValue: 0,
                duration: 300,
                useNativeDriver: true,
              }),
            ]).start(() => setSoldBanner(null));
          }

          setAuctionItem(newItem);
          auctionItemRef.current = newItem;
        }
      } catch (err) {
        console.error('Poll error:', err);
      }
    }

    doPoll();
    const interval = setInterval(doPoll, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [numericEventId, raffleAnimation, user?.id]);

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

  function startRaffleAnimation(data: {
    prizeName: string;
    winnerName: string;
    isCurrentUser: boolean;
    viewerNames: string[];
  }) {
    setRaffleAnimation(data);
    setAnimationPhase('shuffling');
    raffleOverlayOpacity.setValue(0);
    winnerScale.setValue(0.5);
    youWonOpacity.setValue(0);

    // Fade in overlay
    Animated.timing(raffleOverlayOpacity, {
      toValue: 1,
      duration: 300,
      useNativeDriver: true,
    }).start();

    // Shuffle through names with deceleration
    const { viewerNames, winnerName } = data;
    let elapsed = 0;
    let delay = 50;

    function getDelay() {
      if (elapsed < 1000) return 50;
      if (elapsed < 1800) return 100;
      if (elapsed < 2300) return 200;
      return 400;
    }

    function tick() {
      if (elapsed >= 2800) {
        // Reveal the winner
        setShuffleName(winnerName);
        setAnimationPhase('revealing');

        Animated.spring(winnerScale, {
          toValue: 1,
          friction: 4,
          tension: 80,
          useNativeDriver: true,
        }).start();

        if (data.isCurrentUser) {
          Animated.sequence([
            Animated.delay(500),
            Animated.timing(youWonOpacity, {
              toValue: 1,
              duration: 400,
              useNativeDriver: true,
            }),
          ]).start();
        }

        // Auto-dismiss after 5 seconds
        setTimeout(() => {
          setAnimationPhase('done');
          dismissRaffle();
        }, 5000);
        return;
      }

      // Pick a random name (avoid showing the winner too early)
      const pool = viewerNames.filter((n) => n !== winnerName);
      const randomName = pool.length > 0
        ? pool[Math.floor(Math.random() * pool.length)]
        : viewerNames[Math.floor(Math.random() * viewerNames.length)];
      setShuffleName(randomName);

      delay = getDelay();
      elapsed += delay;
      setTimeout(tick, delay);
    }

    tick();
  }

  function dismissRaffle() {
    Animated.timing(raffleOverlayOpacity, {
      toValue: 0,
      duration: 300,
      useNativeDriver: true,
    }).start(() => {
      setRaffleAnimation(null);
      setShuffleName('');
    });
  }

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

      {/* Auction Item Panel */}
      {event.event_type === 'auction' && auctionItem && auctionItem.status === 'active' && (
        <View style={styles.auctionPanel}>
          <View style={styles.auctionHeader}>
            <Ionicons name="hammer" size={16} color={colors.primary} />
            <Text style={styles.auctionLabel}>{t('events.currentItem')}</Text>
          </View>
          <Text style={styles.auctionTitle}>{auctionItem.title}</Text>
          <Text style={styles.auctionPrice}>
            {t('events.startingAt')} €{auctionItem.starting_price}
          </Text>
        </View>
      )}

      {/* Auction Sold Banner */}
      {soldBanner && (
        <Animated.View style={[styles.soldBanner, { opacity: soldBannerOpacity }]}>
          <Ionicons name="hammer" size={20} color={colors.success} />
          <Text style={styles.soldBannerText}>
            {soldBanner.title} — {t('events.soldFor')} €{soldBanner.final_price}{' '}
            {soldBanner.winner_name ? `${t('events.soldTo')} ${soldBanner.winner_name}` : ''}
          </Text>
        </Animated.View>
      )}

      {/* Raffle Animation Overlay */}
      {raffleAnimation && (
        <Modal visible transparent animationType="none">
          <Animated.View style={[styles.raffleOverlay, { opacity: raffleOverlayOpacity }]}>
            <Pressable style={styles.raffleOverlayPress} onPress={animationPhase === 'done' ? dismissRaffle : undefined}>
              <View style={styles.raffleContent}>
                {/* Prize name */}
                <View style={styles.rafflePrizeRow}>
                  <Ionicons name="gift" size={24} color={colors.primary} />
                  <Text style={styles.rafflePrizeText}>{t('events.drawingFor')}: {raffleAnimation.prizeName}</Text>
                </View>

                {/* Shuffling / Winner name */}
                <Animated.View style={[
                  styles.raffleNameContainer,
                  animationPhase !== 'shuffling' && { transform: [{ scale: winnerScale }] },
                ]}>
                  {animationPhase !== 'shuffling' && (
                    <Ionicons name="trophy" size={40} color={colors.warning} style={{ marginBottom: spacing.sm }} />
                  )}
                  <Text style={[
                    styles.raffleShuffleName,
                    animationPhase !== 'shuffling' && styles.raffleWinnerName,
                  ]}>
                    {shuffleName}
                  </Text>
                </Animated.View>

                {/* YOU WON! */}
                {raffleAnimation.isCurrentUser && animationPhase !== 'shuffling' && (
                  <Animated.View style={[styles.youWonContainer, { opacity: youWonOpacity }]}>
                    <Text style={styles.youWonText}>YOU WON!</Text>
                  </Animated.View>
                )}

                {/* Tap to dismiss hint */}
                {animationPhase === 'done' && (
                  <Text style={styles.raffleDismissHint}>{t('events.tapToDismiss') || 'Tap to dismiss'}</Text>
                )}
              </View>
            </Pressable>
          </Animated.View>
        </Modal>
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

  // Auction panel
  auctionPanel: {
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.primary + '30',
  },
  auctionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 4,
  },
  auctionLabel: {
    color: colors.primary,
    fontSize: 12,
    fontWeight: '600',
    textTransform: 'uppercase',
  },
  auctionTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '600',
  },
  auctionPrice: {
    color: colors.textMuted,
    fontSize: 13,
    marginTop: 2,
  },

  // Sold banner
  soldBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.success + '30',
  },
  soldBannerText: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '600',
    flex: 1,
  },

  // Raffle animation overlay
  raffleOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.92)',
  },
  raffleOverlayPress: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  raffleContent: {
    alignItems: 'center',
    paddingHorizontal: spacing.xl,
  },
  rafflePrizeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.xl,
  },
  rafflePrizeText: {
    color: colors.primary,
    fontSize: 18,
    fontWeight: '600',
  },
  raffleNameContainer: {
    alignItems: 'center',
    minHeight: 100,
    justifyContent: 'center',
  },
  raffleShuffleName: {
    color: colors.textMuted,
    fontSize: 28,
    fontWeight: '500',
    textAlign: 'center',
  },
  raffleWinnerName: {
    color: colors.text,
    fontSize: 36,
    fontWeight: '700',
  },
  youWonContainer: {
    marginTop: spacing.lg,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: borderRadius.lg,
    borderWidth: 2,
    borderColor: colors.warning,
  },
  youWonText: {
    color: colors.warning,
    fontSize: 28,
    fontWeight: '800',
    textAlign: 'center',
    letterSpacing: 4,
  },
  raffleDismissHint: {
    color: colors.textMuted,
    fontSize: 12,
    marginTop: spacing.xl,
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
