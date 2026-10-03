import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  KeyboardAvoidingView,
  Platform,
  Dimensions,
  Modal,
  Animated,
  Pressable,
  NativeSyntheticEvent,
  NativeScrollEvent,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import * as Clipboard from 'expo-clipboard';
import { useAuth } from '../../../src/context/AuthContext';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius, fonts } from '../../../src/theme/colors';
import { Skeleton, useToast } from '../../../src/components/ui';
import {
  MessageBubble,
  MessageComposer,
  ReactionSheet,
  GroupedPosition,
} from '../../../src/components/chat';
import { ApiError } from '../../../src/api/client';
import AuctionPanel from '../../../src/components/AuctionPanel';
import {
  Event,
  EventMessage,
  RaffleWinner,
  AuctionItem,
  getEvent,
  joinEvent,
  sendEventMessage,
  pollEvent,
  reactEventMessage,
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

type MissedDraw = {
  prizeName: string;
  winnerNames: string[];
  isCurrentUser: boolean;
};

// Rejoin threshold: a poll delta spanning more than this many raffles is
// a catch-up (user was backgrounded), not a live draw — show one summary
// instead of replaying every animation back-to-back.
const MAX_REPLAYED_DRAWS = 2;

// Consecutive same-sender messages within this window render as one
// WhatsApp-style run (shared corner treatment, one author line).
const RUN_WINDOW_MS = 5 * 60 * 1000;

function sameRun(a: EventMessage, b: EventMessage): boolean {
  return (
    !a.is_system &&
    !b.is_system &&
    a.user.user_id === b.user.user_id &&
    Math.abs(
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    ) < RUN_WINDOW_MS
  );
}

// Change detection for reaction fields so steady-state polls (same digest
// re-sent, nothing changed) never produce a new messages array.
function reactionsEqual(
  a?: Record<string, number>,
  b?: Record<string, number>
): boolean {
  if (a === b) return true;
  if (!a || !b) return !a && !b;
  const ka = Object.keys(a);
  if (ka.length !== Object.keys(b).length) return false;
  return ka.every((k) => a[k] === b[k]);
}

function mineEqual(a?: string[], b?: string[]): boolean {
  if (a === b) return true;
  if (!a || !b) return !a && !b;
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

// Shuffle pool for the reveal reel: real member names only. If the
// viewer list is tiny, repeat it rather than padding with fake names.
function buildShufflePool(viewerNames: string[], winnerNames: string[]): string[] {
  let pool = viewerNames.length > 0 ? [...viewerNames] : [...winnerNames];
  while (pool.length > 0 && pool.length < 3) {
    pool = pool.concat(pool);
  }
  return pool;
}

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
  const { showToast } = useToast();

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
  // Multi-winner raffles reveal names one at a time, not all at once
  const [revealedWinners, setRevealedWinners] = useState(0);
  // Catch-up summary after missing several draws (backgrounded/rejoined)
  const [missedSummary, setMissedSummary] = useState<MissedDraw[] | null>(null);
  // Persistent "jij hebt gewonnen" banner — the overlay is ephemeral and
  // namesakes made winners doubt themselves; this stays until dismissed.
  const [myWins, setMyWins] = useState<string[]>([]);
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

  // Chat scroll: only auto-scroll while the user is (near) the bottom.
  // messagesRef mirrors the messages state so the poll can merge + count
  // unread synchronously without impure setState updaters.
  const [unreadCount, setUnreadCount] = useState(0);
  const atBottomRef = useRef(true);
  const messagesRef = useRef<EventMessage[]>([]);

  // Reactions: server revision we last saw, in-flight optimistic toggles
  // (the poll must not clobber them), and the long-pressed message whose
  // ReactionSheet is open.
  const reactionRevRef = useRef(0);
  const pendingReactionsRef = useRef<Set<number>>(new Set());
  const [sheetMessage, setSheetMessage] = useState<EventMessage | null>(null);

  const numericEventId = Number(eventId);

  // Load event and join; retryKey re-runs after a failed load.
  const [retryKey, setRetryKey] = useState(0);
  useEffect(() => {
    let stale = false;
    async function init() {
      try {
        const [eventData] = await Promise.all([
          getEvent(numericEventId),
          joinEvent(numericEventId),
        ]);
        if (stale) return;
        setEvent(eventData);
        setActiveViewerCount(eventData.active_viewer_count || 0);
      } catch (err) {
        console.error('Failed to load event:', err);
      } finally {
        if (!stale) setLoading(false);
      }
    }
    init();
    return () => {
      stale = true;
    };
  }, [numericEventId, retryKey]);

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

        // The digest window is "messages we hold right now" — capture the
        // oldest id BEFORE the request so snapshot clearing below matches
        // exactly what the server was asked to cover.
        const oldestHeldId = messagesRef.current[0]?.id;

        const data = await pollEvent(
          numericEventId,
          lastMessageTime.current,
          isHeartbeat,
          prevWinnerCount.current,
          reactionRevRef.current,
          oldestHeldId,
        );
        if (cancelled) return;

        // Chat messages: merge-if-known (a re-delivered row may carry
        // fresh reaction fields), append the genuinely new, cap at
        // MAX_MESSAGES. `changed` tracks whether a new array must render.
        let next = messagesRef.current;
        let changed = false;

        if (data.messages.length > 0) {
          const incoming = new Map(data.messages.map((m) => [m.id, m]));
          next = next.map((held) => {
            const upd = incoming.get(held.id);
            if (!upd) return held;
            incoming.delete(held.id);
            if (
              !pendingReactionsRef.current.has(held.id) &&
              (!reactionsEqual(held.reactions, upd.reactions) ||
                !mineEqual(held.mine, upd.mine))
            ) {
              changed = true;
              return { ...held, reactions: upd.reactions, mine: upd.mine };
            }
            return held;
          });
          // Whatever survived the merge pass is new, in server order
          const newMsgs = data.messages.filter((m) => incoming.has(m.id));
          if (newMsgs.length > 0) {
            next = [...next, ...newMsgs];
            if (next.length > MAX_MESSAGES) next = next.slice(-MAX_MESSAGES);
            changed = true;
            // Count messages from others as unread while scrolled up —
            // the list no longer force-scrolls, the pill shows instead.
            if (!atBottomRef.current) {
              const fromOthers = newMsgs.filter(
                (m) => m.user.user_id !== userIdRef.current
              ).length;
              if (fromOthers > 0) {
                setUnreadCount((c) => c + fromOthers);
              }
            }
          }
          lastMessageTime.current =
            data.messages[data.messages.length - 1].created_at;
        }

        // Reaction digest — a SNAPSHOT of every reacted message in the
        // window we requested: a held message in that window that is
        // absent from the digest has zero reactions (un-react propagation).
        // In-flight optimistic toggles are skipped; their POST response
        // reconciles them.
        if (data.reaction_updates) {
          const updates = new Map(
            data.reaction_updates.map((u) => [u.m, u])
          );
          next = next.map((held) => {
            if (pendingReactionsRef.current.has(held.id)) return held;
            if (oldestHeldId !== undefined && held.id < oldestHeldId) {
              return held; // outside the window we asked the server for
            }
            const u = updates.get(held.id);
            const reactions =
              u && Object.keys(u.r).length > 0 ? u.r : undefined;
            const mine = u && u.mine.length > 0 ? u.mine : undefined;
            if (
              !reactionsEqual(held.reactions, reactions) ||
              !mineEqual(held.mine, mine)
            ) {
              changed = true;
              return { ...held, reactions, mine };
            }
            return held;
          });
        }
        reactionRevRef.current = data.reaction_rev;

        if (changed) {
          messagesRef.current = next;
          setMessages(next);
        }

        // Viewer count (only on heartbeat)
        if (data.active_viewer_count !== undefined) {
          setActiveViewerCount(data.active_viewer_count);
        }

        // Live event fields: a youtube_url corrected mid-stream or a
        // status flip must reach viewers who already have the screen open
        // (the detail endpoint is only fetched on mount). Same-value polls
        // return the previous reference, so no re-render.
        if (data.event) {
          const info = data.event;
          setEvent((prev) => {
            if (
              !prev ||
              (prev.status === info.status && prev.youtube_url === info.youtube_url)
            ) {
              return prev;
            }
            return { ...prev, status: info.status, youtube_url: info.youtube_url };
          });
        }

        // Winner changes — full data + viewer names included by backend
        // whenever our known count differs (increase OR decrease).
        if (data.winners) {
          setWinners(data.winners);
          const newCount = data.winner_count;

          if (initialized && newCount > prevWinnerCount.current) {
            const delta = newCount - prevWinnerCount.current;
            const newWinners = data.winners.slice(0, delta); // newest-first

            // Persistent personal banner, regardless of which overlay
            // (live reveal or catch-up summary) ends up shown.
            const mine = newWinners
              .filter((w) => w.user.user_id === userIdRef.current)
              .map((w) => w.prize_name);
            if (mine.length > 0) {
              setMyWins((prev) => [
                ...prev,
                ...mine.filter((p) => !prev.includes(p)),
              ]);
            }

            // One reveal per raffle, replayed in draw order (oldest first)
            const groups: { raffleId: number; winners: RaffleWinner[] }[] = [];
            for (const w of [...newWinners].reverse()) {
              const g = groups.find((x) => x.raffleId === w.raffle_id);
              if (g) g.winners.push(w);
              else groups.push({ raffleId: w.raffle_id, winners: [w] });
            }

            const names = data.viewer_names?.map((v) => v.display_name) || [];

            if (groups.length > MAX_REPLAYED_DRAWS) {
              // Catch-up after a gap: one summary instead of a parade of
              // overlays.
              setMissedSummary(
                groups.map((g) => ({
                  prizeName: g.winners[0].prize_name,
                  winnerNames: g.winners.map((w) => w.user.display_name),
                  isCurrentUser: g.winners.some(
                    (w) => w.user.user_id === userIdRef.current
                  ),
                }))
              );
            } else {
              for (const g of groups) {
                const winnerNames = g.winners.map((w) => w.user.display_name);
                const animation: RaffleAnimationData = {
                  prizeName: g.winners[0].prize_name,
                  winnerNames,
                  isCurrentUser: g.winners.some(
                    (w) => w.user.user_id === userIdRef.current
                  ),
                  viewerNames: buildShufflePool(names, winnerNames),
                };
                if (raffleActive.current) {
                  // An animation is playing — queue for after it ends
                  pendingRaffles.current.push(animation);
                } else {
                  startRaffleAnimation(animation);
                }
              }
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
      if (!messagesRef.current.some((m) => m.id === msg.id)) {
        let next = [...messagesRef.current, msg];
        if (next.length > MAX_MESSAGES) next = next.slice(-MAX_MESSAGES);
        messagesRef.current = next;
        setMessages(next);
      }
      // Deliberately NOT advancing lastMessageTime here: the poll cursor
      // must only move via poll responses, otherwise messages other users
      // posted between the last poll and this send would be skipped.
      // Sending your own message always returns you to the bottom.
      atBottomRef.current = true;
      setUnreadCount(0);
      flatListRef.current?.scrollToEnd({ animated: true });
    } catch (err) {
      console.error('Send error:', err);
      setMessageText(text);
      if (err instanceof ApiError && err.status === 429) {
        showToast(t('events.chatThrottled'), 'error');
      } else if (
        err instanceof ApiError &&
        err.status === 400 &&
        err.message.includes('live')
      ) {
        showToast(t('events.chatClosed'), 'error');
      } else {
        showToast(t('events.sendError'), 'error');
      }
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }, [messageText, numericEventId, showToast]);

  const handleChatScroll = useCallback(
    (e: NativeSyntheticEvent<NativeScrollEvent>) => {
      const { layoutMeasurement, contentOffset, contentSize } = e.nativeEvent;
      const atBottom =
        contentOffset.y + layoutMeasurement.height >= contentSize.height - 40;
      atBottomRef.current = atBottom;
      if (atBottom) setUnreadCount(0);
    },
    []
  );

  const scrollChatToBottom = useCallback(() => {
    atBottomRef.current = true;
    setUnreadCount(0);
    flatListRef.current?.scrollToEnd({ animated: true });
  }, []);

  const patchMessage = useCallback(
    (id: number, patch: Partial<EventMessage>) => {
      const next = messagesRef.current.map((m) =>
        m.id === id ? { ...m, ...patch } : m
      );
      messagesRef.current = next;
      setMessages(next);
    },
    []
  );

  // Optimistic reaction toggle, reconciled from the POST response; the
  // pending set keeps the 3s poll from clobbering it mid-flight.
  const handleToggleReaction = useCallback(
    async (target: EventMessage, emoji: string) => {
      // Re-resolve by id: the row's captured object may predate a poll merge
      const msg =
        messagesRef.current.find((m) => m.id === target.id) ?? target;
      const snapshot = { reactions: msg.reactions, mine: msg.mine };
      const mineSet = new Set(msg.mine ?? []);
      const reactions: Record<string, number> = { ...(msg.reactions ?? {}) };
      if (mineSet.has(emoji)) {
        mineSet.delete(emoji);
        const n = (reactions[emoji] ?? 1) - 1;
        if (n > 0) reactions[emoji] = n;
        else delete reactions[emoji];
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
        const res = await reactEventMessage(numericEventId, msg.id, emoji);
        patchMessage(msg.id, {
          reactions: Object.keys(res.reactions).length
            ? res.reactions
            : undefined,
          mine: res.mine.length ? res.mine : undefined,
        });
      } catch (err) {
        patchMessage(msg.id, snapshot);
        if (err instanceof ApiError && err.status === 429) {
          showToast(t('events.reactionThrottled'), 'error');
        } else {
          showToast(t('community.reactError'), 'error');
        }
      } finally {
        pendingReactionsRef.current.delete(msg.id);
      }
    },
    [numericEventId, patchMessage, showToast]
  );

  const handleCopyMessage = useCallback(
    async (msg: EventMessage) => {
      try {
        await Clipboard.setStringAsync(msg.message);
        showToast(t('community.copied'), 'success');
      } catch {}
    },
    [showToast]
  );

  function clearRaffleTimeouts() {
    raffleTimeouts.current.forEach(clearTimeout);
    raffleTimeouts.current = [];
  }

  function startRaffleAnimation(data: RaffleAnimationData) {
    if (!mountedRef.current) return;

    raffleActive.current = true;
    setRaffleAnimation(data);
    setAnimationPhase('shuffling');
    setRevealedWinners(0);
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

    const REVEAL_STAGGER = 600;

    function revealNext(n: number) {
      setRevealedWinners(n);
      if (n < data.winnerNames.length) {
        // Multi-winner prize: names land one at a time, not all at once
        raffleTimeouts.current.push(
          setTimeout(() => revealNext(n + 1), REVEAL_STAGGER)
        );
      } else {
        // Auto-dismiss 5 seconds after the last name lands
        raffleTimeouts.current.push(
          setTimeout(() => {
            setAnimationPhase('done');
            dismissRaffle();
          }, 5000)
        );
      }
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

        revealNext(1);
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

  // Derived chat rows: WhatsApp-style run grouping over the ascending
  // array (a run = consecutive non-system messages of one sender within
  // 5 minutes; author once per run, timestamp on the run's last bubble).
  type ChatRow = {
    msg: EventMessage;
    grouped: GroupedPosition;
    showTime: boolean;
    authorName?: string;
  };
  const chatRows = useMemo<ChatRow[]>(
    () =>
      messages.map((msg, i) => {
        if (msg.is_system) {
          return { msg, grouped: 'single' as const, showTime: false };
        }
        const prev = messages[i - 1];
        const next = messages[i + 1];
        const hasPrev = !!prev && sameRun(msg, prev);
        const hasNext = !!next && sameRun(msg, next);
        const grouped: GroupedPosition =
          hasPrev && hasNext ? 'middle' : hasPrev ? 'last' : hasNext ? 'first' : 'single';
        const isOwn = msg.user.user_id === user?.id;
        return {
          msg,
          grouped,
          showTime: grouped === 'last' || grouped === 'single',
          authorName:
            !isOwn && (grouped === 'first' || grouped === 'single')
              ? msg.user.display_name
              : undefined,
        };
      }),
    [messages, user?.id]
  );

  const renderMessage = useCallback(
    ({ item }: { item: ChatRow }) => {
      const { msg } = item;
      const isOwn = msg.user.user_id === user?.id;
      return (
        <MessageBubble
          isOwn={isOwn}
          text={msg.message}
          createdAt={msg.created_at}
          authorName={item.authorName}
          isSystem={msg.is_system}
          grouped={item.grouped}
          showTime={item.showTime}
          reactions={msg.reactions}
          mine={msg.mine}
          onToggleReaction={(emoji) => handleToggleReaction(msg, emoji)}
          onLongPress={
            msg.is_system ? undefined : () => setSheetMessage(msg)
          }
        />
      );
    },
    [user?.id, handleToggleReaction]
  );

  if (loading) {
    // Shimmer placeholders echoing the real layout: video block, status
    // row, then a short conversation shape.
    return (
      <View style={styles.container}>
        <Skeleton width="100%" height={VIDEO_HEIGHT} radius={0} />
        <View style={styles.skeletonStatusRow}>
          <Skeleton width={90} height={22} radius={borderRadius.pill} />
          <Skeleton width={70} height={22} radius={borderRadius.pill} />
        </View>
        <View style={styles.skeletonChat}>
          {([
            { w: '62%', own: false },
            { w: '44%', own: true },
            { w: '74%', own: false },
            { w: '38%', own: false },
            { w: '56%', own: true },
          ] as const).map((r, i) => (
            <Skeleton
              key={i}
              width={r.w}
              height={42}
              radius={16}
              style={{
                alignSelf: r.own ? 'flex-end' : 'flex-start',
                marginBottom: spacing.sm,
              }}
            />
          ))}
        </View>
      </View>
    );
  }

  if (!event) {
    return (
      <View style={styles.loadingContainer}>
        <Ionicons name="cloud-offline-outline" size={36} color={colors.textMuted} />
        <Text style={styles.errorText}>{t('events.notFound')}</Text>
        <TouchableOpacity
          style={styles.retryButton}
          activeOpacity={0.85}
          onPress={() => {
            setLoading(true);
            setRetryKey((k) => k + 1);
          }}
        >
          <Text style={styles.retryButtonText}>{t('retry')}</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
    >
      {/* YouTube Player — keyed on the URL so a mid-stream correction
          (poll-delivered) swaps the embed cleanly */}
      {event.youtube_url ? (
        <YouTubePlayer key={event.youtube_url} url={event.youtube_url} />
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

      {/* Persistent personal win banner — the overlay is ephemeral and a
          first name alone left namesakes guessing; this one is theirs. */}
      {myWins.length > 0 && (
        <View style={styles.winBanner}>
          <Ionicons name="trophy" size={18} color={colors.warning} />
          <Text style={styles.winBannerText}>
            {t('events.youWonBanner', { prizes: myWins.join(', ') })}
          </Text>
          <TouchableOpacity
            onPress={() => setMyWins([])}
            hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
          >
            <Ionicons name="close" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        </View>
      )}

      {/* Auction Panel — shown whenever the poll carries an item, also on
          livestream-typed events (raffles + auction in one stream) */}
      {auctionItem && (
        <AuctionPanel
          item={auctionItem}
          eventId={numericEventId}
          isLive={event.status === 'live'}
        />
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
                    raffleAnimation.winnerNames
                      .slice(0, revealedWinners)
                      .map((name, index) => (
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

      {/* Missed-draws summary: rejoining after a gap shows one compact
          recap instead of replaying every draw animation back-to-back */}
      {missedSummary && (
        <Modal visible transparent animationType="fade">
          <View style={styles.missedOverlay}>
            <View style={styles.missedCard}>
              <View style={styles.missedHeader}>
                <Ionicons name="gift" size={20} color={colors.primary} />
                <Text style={styles.missedTitle}>
                  {t('events.missedDraws', { count: missedSummary.length })}
                </Text>
              </View>
              {missedSummary.some((d) => d.isCurrentUser) && (
                <View style={styles.missedYouWon}>
                  <Text style={styles.missedYouWonText}>{t('events.youWon')}</Text>
                </View>
              )}
              <FlatList
                data={missedSummary}
                keyExtractor={(_, i) => String(i)}
                style={styles.missedList}
                renderItem={({ item }) => (
                  <View style={styles.missedRow}>
                    <View style={styles.missedPrizeRow}>
                      {item.isCurrentUser && (
                        <Ionicons name="trophy" size={14} color={colors.warning} />
                      )}
                      <Text
                        style={[
                          styles.missedPrize,
                          item.isCurrentUser && styles.missedPrizeMine,
                        ]}
                      >
                        {item.prizeName}
                      </Text>
                    </View>
                    <Text style={styles.missedWinners}>
                      {item.winnerNames.join(', ')}
                    </Text>
                  </View>
                )}
              />
              <TouchableOpacity
                style={styles.missedDismiss}
                onPress={() => setMissedSummary(null)}
                activeOpacity={0.85}
              >
                <Text style={styles.missedDismissText}>
                  {t('events.tapToDismiss')}
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </Modal>
      )}

      {/* Chat — auto-scrolls only while the user is at the bottom; while
          scrolled up, new messages accumulate in the unread pill instead. */}
      <View style={styles.chatWrap}>
        <FlatList
          ref={flatListRef}
          data={chatRows}
          renderItem={renderMessage}
          keyExtractor={(item) => String(item.msg.id)}
          style={styles.chatList}
          contentContainerStyle={styles.chatContent}
          onScroll={handleChatScroll}
          scrollEventThrottle={32}
          onContentSizeChange={() => {
            if (atBottomRef.current) {
              flatListRef.current?.scrollToEnd({ animated: true });
            }
          }}
          onLayout={() => {
            if (atBottomRef.current) {
              flatListRef.current?.scrollToEnd({ animated: false });
            }
          }}
        />
        {unreadCount > 0 && (
          <TouchableOpacity
            style={styles.unreadPill}
            onPress={scrollChatToBottom}
            activeOpacity={0.85}
          >
            <Ionicons name="chevron-down" size={14} color={colors.background} />
            <Text style={styles.unreadPillText}>
              {unreadCount === 1
                ? t('events.newMessage')
                : t('events.newMessages', { count: unreadCount })}
            </Text>
          </TouchableOpacity>
        )}
      </View>

      {/* Message Input — shared composer (emoji strip + send) */}
      <MessageComposer
        value={messageText}
        onChangeText={setMessageText}
        onSend={handleSend}
        sending={sending}
        maxLength={500}
        placeholder={t('events.chatPlaceholder')}
      />

      {/* Long-press reaction sheet (reactions + copy; livestream has no
          message delete endpoint, so no delete row) */}
      <ReactionSheet
        visible={sheetMessage !== null}
        onClose={() => setSheetMessage(null)}
        mine={sheetMessage?.mine}
        onReact={(emoji) => {
          if (sheetMessage) handleToggleReaction(sheetMessage, emoji);
        }}
        onCopy={() => {
          if (sheetMessage) handleCopyMessage(sheetMessage);
        }}
      />

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
    gap: spacing.md,
  },
  errorText: {
    color: colors.textMuted,
    fontSize: 16,
  },
  retryButton: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.pill,
    backgroundColor: colors.primary,
  },
  retryButtonText: {
    fontFamily: fonts.heading,
    color: colors.background,
    fontSize: 13,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
  },
  skeletonStatusRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  skeletonChat: {
    flex: 1,
    justifyContent: 'flex-end',
    padding: spacing.md,
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

  // Persistent personal win banner
  winBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surfaceHigh,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    borderLeftWidth: 3,
    borderLeftColor: colors.warning,
  },
  winBannerText: {
    fontFamily: fonts.heading,
    color: colors.text,
    fontSize: 14,
    letterSpacing: 0.3,
    flex: 1,
  },

  // Missed-draws summary
  missedOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.85)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.lg,
  },
  missedCard: {
    backgroundColor: colors.surfaceHigh,
    borderRadius: borderRadius.xl,
    padding: spacing.lg,
    width: '100%',
    maxWidth: 420,
    maxHeight: '70%',
  },
  missedHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  missedTitle: {
    fontFamily: fonts.heading,
    color: colors.text,
    fontSize: 17,
    letterSpacing: 0.4,
    flex: 1,
  },
  missedYouWon: {
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: borderRadius.pill,
    borderWidth: 2,
    borderColor: colors.warning,
    marginBottom: spacing.md,
  },
  missedYouWonText: {
    fontFamily: fonts.headingBold,
    color: colors.warning,
    fontSize: 14,
    letterSpacing: 2,
    textTransform: 'uppercase',
  },
  missedList: {
    flexGrow: 0,
  },
  missedRow: {
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  missedPrizeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  missedPrize: {
    fontFamily: fonts.heading,
    color: colors.primary,
    fontSize: 14,
    letterSpacing: 0.3,
  },
  missedPrizeMine: {
    color: colors.warning,
  },
  missedWinners: {
    color: colors.text,
    fontSize: 13,
    marginTop: 2,
  },
  missedDismiss: {
    alignSelf: 'center',
    marginTop: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.pill,
    backgroundColor: colors.primary,
  },
  missedDismissText: {
    fontFamily: fonts.heading,
    color: colors.background,
    fontSize: 13,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
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
  chatWrap: {
    flex: 1,
  },
  chatList: {
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
  chatContent: {
    padding: spacing.sm,
    paddingBottom: spacing.md,
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
