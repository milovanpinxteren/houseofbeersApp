import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing, borderRadius, fonts } from '../../theme/colors';
import { Avatar } from './Avatar';
import { ReactionBar } from './ReactionBar';
import { isJumbomoji } from './emoji';

export type GroupedPosition = 'first' | 'middle' | 'last' | 'single';

interface MessageBubbleProps {
  isOwn: boolean;
  text: string;
  createdAt: string;
  /** Shown above the bubble (group chats, first message of a run). */
  authorName?: string;
  /** When set, a left gutter is reserved; the avatar renders on showAvatar. */
  avatarName?: string;
  avatarUserId?: number;
  showAvatar?: boolean;
  isSystem?: boolean;
  beerTitle?: string;
  /** Own messages: true = sending (clock), false = sent (checkmark). */
  pending?: boolean;
  /** Render the pending/sent glyph (own messages in optimistic-send chats). */
  showStatus?: boolean;
  /** Position within a run of consecutive same-sender messages. */
  grouped?: GroupedPosition;
  /** Show the HH:MM line (typically on the last bubble of a run). */
  showTime?: boolean;
  reactions?: Record<string, number>;
  mine?: string[];
  onToggleReaction?: (emoji: string) => void;
  onLongPress?: () => void;
}

/**
 * Shared chat bubble for community DMs/groups and the livestream chat.
 * WhatsApp-style run grouping: inner corners square off between consecutive
 * messages of one sender, the tail sits on the last bubble of the run.
 */
export function MessageBubble({
  isOwn, text, createdAt, authorName, avatarName, avatarUserId, showAvatar,
  isSystem, beerTitle, pending, showStatus, grouped = 'single', showTime = true,
  reactions, mine, onToggleReaction, onLongPress,
}: MessageBubbleProps) {
  if (isSystem) {
    return (
      <View style={styles.systemWrap}>
        <Text style={styles.systemText}>{text}</Text>
      </View>
    );
  }

  const hasPrevInRun = grouped === 'middle' || grouped === 'last';
  const hasNextInRun = grouped === 'middle' || grouped === 'first';
  const jumbo = isJumbomoji(text);

  const cornerStyle = isOwn
    ? {
        borderTopRightRadius: hasPrevInRun ? 6 : 16,
        // The tail (4) sits on the last bubble of the run.
        borderBottomRightRadius: hasNextInRun ? 6 : 4,
      }
    : {
        borderTopLeftRadius: hasPrevInRun ? 6 : 16,
        borderBottomLeftRadius: hasNextInRun ? 6 : 4,
      };

  const time = new Date(createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const hasGutter = !isOwn && avatarName !== undefined;

  const bubble = (
    <Pressable
      onLongPress={onLongPress}
      delayLongPress={400}
      style={({ pressed }) => [
        styles.bubble,
        jumbo ? styles.jumboBubble : isOwn ? styles.ownBubble : styles.otherBubble,
        !jumbo && cornerStyle,
        isOwn ? styles.alignOwn : styles.alignOther,
        pressed && onLongPress && { opacity: 0.85 },
      ]}
    >
      {authorName ? <Text style={styles.senderName}>{authorName}</Text> : null}
      {beerTitle ? (
        <View style={styles.beerInMsg}>
          <Ionicons name="beer" size={14} color={colors.primary} />
          <Text style={styles.beerInMsgText}>{beerTitle}</Text>
        </View>
      ) : null}
      <Text
        style={[
          jumbo ? styles.jumboText : styles.messageText,
          !jumbo && isOwn && styles.ownMessageText,
        ]}
      >
        {text}
      </Text>
      {showTime && (
        <View style={styles.timeRow}>
          <Text style={[styles.messageTime, isOwn && !jumbo && styles.ownMessageTime]}>
            {time}
          </Text>
          {isOwn && showStatus && (
            <Ionicons
              name={pending ? 'time-outline' : 'checkmark'}
              size={11}
              color={jumbo ? colors.textMuted : colors.background + '99'}
            />
          )}
        </View>
      )}
    </Pressable>
  );

  return (
    <View style={[styles.wrap, { marginBottom: hasNextInRun ? 2 : spacing.sm }]}>
      {hasGutter ? (
        <View style={styles.gutterRow}>
          <View style={styles.gutter}>
            {showAvatar && (
              <Avatar name={avatarName} userId={avatarUserId} size="xs" />
            )}
          </View>
          <View style={styles.gutterContent}>
            {bubble}
            {reactions && (
              <ReactionBar
                reactions={reactions}
                mine={mine}
                onToggle={onToggleReaction}
                align="left"
              />
            )}
          </View>
        </View>
      ) : (
        <>
          {bubble}
          {reactions && (
            <ReactionBar
              reactions={reactions}
              mine={mine}
              onToggle={onToggleReaction}
              align={isOwn ? 'right' : 'left'}
            />
          )}
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {},
  gutterRow: { flexDirection: 'row', alignItems: 'flex-end' },
  gutter: { width: 22, marginRight: 6, alignItems: 'center' },
  gutterContent: { flex: 1 },
  bubble: {
    maxWidth: '80%',
    borderRadius: 16,
    paddingVertical: spacing.sm + 2,
    paddingHorizontal: spacing.md,
  },
  alignOwn: { alignSelf: 'flex-end' },
  alignOther: { alignSelf: 'flex-start' },
  ownBubble: { backgroundColor: colors.primary },
  otherBubble: { backgroundColor: colors.surfaceHigh },
  jumboBubble: {
    backgroundColor: 'transparent',
    paddingVertical: 2,
    paddingHorizontal: 2,
  },
  senderName: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 0.6,
    color: colors.primary,
    marginBottom: 2,
  },
  messageText: { color: colors.text, fontSize: 15, lineHeight: 21 },
  ownMessageText: { color: colors.background },
  jumboText: { fontSize: 34, lineHeight: 42 },
  timeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    alignSelf: 'flex-end',
    marginTop: 4,
  },
  messageTime: { color: colors.textMuted, fontSize: 10 },
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
  systemWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
  },
  systemText: {
    fontFamily: fonts.heading,
    fontSize: 12,
    letterSpacing: 0.6,
    color: colors.warning,
    textAlign: 'center',
  },
});
