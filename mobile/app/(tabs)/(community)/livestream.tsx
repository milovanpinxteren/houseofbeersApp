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
import { colors, spacing, borderRadius, fonts } from '../../../src/theme/colors';
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
const MAX_MESSAGES = 300;
const { width: SCREEN_WIDTH } = Dimensions.get('window');
const VIDEO_HEIGHT = (SCREEN_WIDTH * 9) / 16;

type RaffleAnimationData = {
  prizeName: string;
  winnerNames: string[];
  isCurrentUser: boolean;
  viewerNames: string[];
};

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
  const announcedSoldIds = useRef<Set<number>>(new Set());

  // Raffle animation
  const [raffleAnimation, setRaffleAnimation] = useState<RaffleAnimationData | null>(null);
  const [shuffleName, setShuffleName] = useState('');
  const [animationPhase, setAnimationPhase] = useState<'shuffling' | 'revealing' | 'done'>('shuffling');
  const raffleOverlayOpacity = useRef(new Animated.Value(0)).current;
  const winnerScale = useRef(new Animated.Value(0.5)).current;
  const youWonOpacity = useRef(new Animated.Value(0)).current;
  const prevWinnerCount = useRef(0);
  const raffleActive = useRef(false);
  const raffleDismissing = useRef(false);
  const pendingRaffles = useRef<RaffleAnimationData[]>([]);
  const raffleTimeouts = useRef<ReturnType<typeof setTimeout>[]>([]);
  const mountedRef = useRef(true);

  const lastMessageTime = useRef<string | undefined>(undefined);
  const flatListRef = useRef<FlatList>(null);
  const sendingRef = useRef(false);
  const userIdRef = useRef(user?.id);
  userIdRef.current = user?.id;

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

  // Combined poll: chat, winners, auction — single request every 3s.
  // Heartbeat (presence update) every 20th poll (~60s).
  // Uses a setTimeout-after-completion loop so slow responses never
  // stack overlapping requests.
  useEffect(() => {
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    let pollCount = 0;
    let initialized = false; // first successful poll populates state silently

    async function doPoll() {
      try {
        pollCount += 1;
        const isHeartbeat = pollCount % 20 === 1; // First poll + every 60s

        const data = await pollEvent(
          numericEventId,
          lastMessageTime.current,
          isHeartbeat,
          prevWinnerCount.current,
        );
        if (cancelled) return;

        // Chat messages (capped to the most recent MAX_MESSAGES)
        if (data.messages.length > 0) {
          setMessages((prev) => {
            const existingIds = new Set(prev.map((m) => m.id));
            const newMsgs = data.messages.filter((m) => !existingIds.has(m.id));
            if (newMsgs.length === 0) return prev;
            const next = [...prev, ...newMsgs];
            return next.length > MAX_MESSAGES ? next.slice(-MAX_MESSAGES) : next;
          });
          lastMessageTime.current =
            data.messages[data.messages.length - 1].created_at;
        }

        // Viewer count (only on heartbeat)
        if (data.active_viewer_count !== undefined) {
          setActiveViewerCount(data.active_viewer_count);
        }

        // Winner changes — full data + viewer names included by backend
        // whenever our known count differs (increase OR decrease).
        if (data.winners) {
          setWinners(data.winners);
          const newCount = data.winner_count;

          if (initialized && newCount > prevWinnerCount.current) {
            // Animate the full batch of new winners (list is newest-first)
            const delta = newCount - prevWinnerCount.current;
            const newWinners = data.winners.slice(0, delta);
            const winnerNames = newWinners.map((w) => w.user.display_name);
            const prizeName = [
              ...new Set(newWinners.map((w) => w.prize_name)),
            ].join(', ');
            const isCurrentUser = newWinners.some(
              (w) => w.user.user_id === userIdRef.current
            );

            const names = data.viewer_names?.map((v) => v.display_name) || [];
            const shuffleNames = names.length >= 3 ? names : [
              ...winnerNames,
              ...names,
              'Viewer', 'Guest', 'Beer Fan',
            ];

            const animation: RaffleAnimationData = {
              prizeName,
              winnerNames,
              isCurrentUser,
              viewerNames: shuffleNames,
            };

            if (raffleActive.current) {
              // An animation is playing — queue this draw for after it ends
              pendingRaffles.current.push(animation);
            } else {
              startRaffleAnimation(animation);
            }
          }
          // Payload consumed (winners stored, animation played/queued)
          prevWinnerCount.current = newCount;
        } else {
          prevWinnerCount.current = data.winner_count;
        }

        // Auction item (included for auction events). Backend returns the
        // most recently sold item when nothing is active, so we can show
        // the sold banner — once per item id, and never on initial load.
        if (data.auction_item !== undefined) {
          const newItem = data.auction_item;

          if (
            newItem &&
            newItem.status === 'sold' &&
            !announcedSoldIds.current.has(newItem.id)
          ) {
            announcedSoldIds.current.add(newItem.id);
            if (initialized) {
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
          }

          setAuctionItem(newItem);
        }

        initialized = true;
      } catch (err) {
        console.error('Poll error:', err);
      } finally {
        if (!cancelled) {
          timeoutId = setTimeout(doPoll, POLL_INTERVAL);
        }
      }
    }

    doPoll();
    return () => {
      cancelled = true;
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [numericEventId]);

  // Clear raffle animation timers and queue on unmount
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      raffleTimeouts.current.forEach(clearTimeout);
      raffleTimeouts.current = [];
      pendingRaffles.current = [];
    };
  }, []);

  const handleSend = useCallback(async () => {
    const text = messageText.trim();
    // Ref guard: two calls in the same tick (button + submit) can't both pass
    if (!text || sendingRef.current) return;

    sendingRef.current = true;
    setSending(true);
    setMessageText('');
    try {
      const msg = await sendEventMessage(numericEventId, text);
      setMessages((prev) => {
        if (prev.some((m) => m.id === msg.id)) return prev;
        const next = [...prev, msg];
        return next.length > MAX_MESSAGES ? next.slice(-MAX_MESSAGES) : next;
      });
      // Deliberately NOT advancing lastMessageTime here: the poll cursor
      // must only move via poll responses, otherwise messages other users
      // posted between the last poll and this send would be skipped.
    } catch (err) {
      console.error('Send error:', err);
      setMessageText(text);
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }, [messageText, numericEventId]);

  function clearRaffleTimeouts() {
    raffleTimeouts.current.forEach(clearTimeout);
    raffleTimeouts.current = [];
  }

  function startRaffleAnimation(data: RaffleAnimationData) {
    if (!mountedRef.current) return;

    raffleActive.current = true;
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
    const { viewerNames, winnerNames } = data;
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
        // Reveal the winner(s)
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
        raffleTimeouts.current.push(
          setTimeout(() => {
            setAnimationPhase('done');
            dismissRaffle();
          }, 5000)
        );
        return;
      }

      // Pick a random name (avoid showing a winner too early)
      const pool = viewerNames.filter((n) => !winnerNames.includes(n));
      const randomName = pool.length > 0
        ? pool[Math.floor(Math.random() * pool.length)]
        : viewerNames[Math.floor(Math.random() * viewerNames.length)];
      setShuffleName(randomName);

      delay = getDelay();
      elapsed += delay;
      raffleTimeouts.current.push(setTimeout(tick, delay));
    }

    tick();
  }

  function dismissRaffle() {
    if (raffleDismissing.current) return;
    raffleDismissing.current = true;
    clearRaffleTimeouts();
    Animated.timing(raffleOverlayOpacity, {
      toValue: 0,
      duration: 300,
      useNativeDriver: true,
    }).start(() => {
      raffleDismissing.current = false;
      if (!mountedRef.current) return;
      setShuffleName('');
      // Play the next queued draw, if any arrived during this animation
      const next = pendingRaffles.current.shift();
      if (next) {
        startRaffleAnimation(next);
      } else {
        raffleActive.current = false;
        setRaffleAnimation(null);
      }
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
          <Text style={[styles.chatText, isMe && styles.chatTextMe]}>{item.message}</Text>
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
        <Text style={styles.errorText}>{t('events.notFound')}</Text>
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
              <View style={styles.liveDot} />
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

                {/* Shuffling / Winner name(s) */}
                <Animated.View style={[
                  styles.raffleNameContainer,
                  animationPhase !== 'shuffling' && { transform: [{ scale: winnerScale }] },
                ]}>
                  {animationPhase !== 'shuffling' && (
                    <Ionicons name="trophy" size={40} color={colors.warning} style={{ marginBottom: spacing.sm }} />
                  )}
                  {animationPhase === 'shuffling' ? (
                    <Text style={styles.raffleShuffleName}>{shuffleName}</Text>
                  ) : (
                    raffleAnimation.winnerNames.map((name, index) => (
                      <Text
                        key={`${name}-${index}`}
                        style={[styles.raffleShuffleName, styles.raffleWinnerName]}
                      >
                        {name}
                      </Text>
                    ))
                  )}
                </Animated.View>

                {/* YOU WON! */}
                {raffleAnimation.isCurrentUser && animationPhase !== 'shuffling' && (
                  <Animated.View style={[styles.youWonContainer, { opacity: youWonOpacity }]}>
                    <Text style={styles.youWonText}>{t('events.youWon')}</Text>
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
              <TouchableOpacity onPress={() => setShowWinnersModal(false)} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
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
    fontFamily: fonts.heading,
    color: colors.textMuted,
    fontSize: 16,
    letterSpacing: 0.4,
    marginTop: spacing.sm,
  },

  // Status bar
  statusBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  statusLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  liveBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: colors.live,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: borderRadius.pill,
  },
  liveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#fff',
  },
  liveBadgeText: {
    fontFamily: fonts.headingBold,
    color: '#fff',
    fontSize: 11,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
  },
  viewerCount: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.sm + 2,
    paddingVertical: 3,
    borderRadius: borderRadius.pill,
  },
  viewerCountText: {
    fontFamily: fonts.heading,
    color: colors.textMuted,
    fontSize: 12,
    letterSpacing: 0.4,
  },
  winnersButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: colors.surfaceHigh,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: borderRadius.pill,
    minHeight: 30,
  },
  winnersButtonText: {
    fontFamily: fonts.heading,
    color: colors.warning,
    fontSize: 12,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
  },

  // Auction panel
  auctionPanel: {
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    borderLeftWidth: 3,
    borderLeftColor: colors.primary,
  },
  auctionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 4,
  },
  auctionLabel: {
    fontFamily: fonts.heading,
    color: colors.primary,
    fontSize: 11,
    letterSpacing: 1.5,
    textTransform: 'uppercase',
  },
  auctionTitle: {
    fontFamily: fonts.heading,
    color: colors.text,
    fontSize: 17,
    letterSpacing: 0.4,
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
    backgroundColor: colors.surfaceHigh,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    gap: spacing.sm,
    borderLeftWidth: 3,
    borderLeftColor: colors.success,
  },
  soldBannerText: {
    fontFamily: fonts.heading,
    color: colors.text,
    fontSize: 14,
    letterSpacing: 0.3,
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
    fontFamily: fonts.heading,
    color: colors.primary,
    fontSize: 18,
    letterSpacing: 0.5,
  },
  raffleNameContainer: {
    alignItems: 'center',
    minHeight: 100,
    justifyContent: 'center',
  },
  raffleShuffleName: {
    fontFamily: fonts.headingRegular,
    color: colors.textMuted,
    fontSize: 28,
    letterSpacing: 0.6,
    textAlign: 'center',
  },
  raffleWinnerName: {
    fontFamily: fonts.headingBold,
    color: colors.text,
    fontSize: 36,
    letterSpacing: 0.6,
  },
  youWonContainer: {
    marginTop: spacing.lg,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: borderRadius.pill,
    borderWidth: 2,
    borderColor: colors.warning,
  },
  youWonText: {
    fontFamily: fonts.headingBold,
    color: colors.warning,
    fontSize: 26,
    textAlign: 'center',
    letterSpacing: 4,
    textTransform: 'uppercase',
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
    backgroundColor: colors.surfaceHigh,
    borderRadius: 16,
    borderBottomLeftRadius: 4,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm + 4,
    marginBottom: spacing.xs + 2,
    maxWidth: '85%',
    alignSelf: 'flex-start',
  },
  chatBubbleMe: {
    backgroundColor: colors.primary,
    alignSelf: 'flex-end',
    borderBottomLeftRadius: 16,
    borderBottomRightRadius: 4,
  },
  chatAuthor: {
    fontFamily: fonts.heading,
    color: colors.primary,
    fontSize: 11,
    letterSpacing: 0.6,
    marginBottom: 2,
  },
  chatText: {
    color: colors.text,
    fontSize: 14,
    lineHeight: 20,
  },
  chatTextMe: {
    color: colors.background,
  },
  systemMessage: {
    alignItems: 'center',
    paddingVertical: spacing.xs,
  },
  systemMessageText: {
    fontFamily: fonts.heading,
    color: colors.warning,
    fontSize: 12,
    letterSpacing: 0.6,
  },

  // Input
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    backgroundColor: colors.background,
  },
  input: {
    flex: 1,
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: Platform.OS === 'ios' ? 12 : 10,
    color: colors.text,
    fontSize: 14,
    maxHeight: 100,
  },
  sendButton: {
    backgroundColor: colors.primary,
    width: 44,
    height: 44,
    borderRadius: 22,
    justifyContent: 'center',
    alignItems: 'center',
  },
  sendButtonDisabled: {
    backgroundColor: colors.surfaceHigh,
  },

  // Winners Modal
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'flex-end',
  },
  modalContent: {
    backgroundColor: colors.surfaceHigh,
    borderTopLeftRadius: borderRadius.xl,
    borderTopRightRadius: borderRadius.xl,
    maxHeight: '60%',
    paddingBottom: spacing.xl,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  modalTitle: {
    fontFamily: fonts.heading,
    color: colors.text,
    fontSize: 18,
    letterSpacing: 0.5,
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
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  winnerInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  winnerName: {
    fontFamily: fonts.heading,
    color: colors.text,
    fontSize: 15,
    letterSpacing: 0.3,
  },
  winnerPrize: {
    color: colors.primary,
    fontSize: 13,
  },
});
