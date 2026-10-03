import { useEffect, useState } from 'react';
import { Modal, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { t } from '../../i18n';
import { colors, spacing, borderRadius, fonts } from '../../theme/colors';
import { ALLOWED_REACTIONS } from './emoji';

interface ReactionSheetProps {
  visible: boolean;
  onClose: () => void;
  /** Emoji the current user already placed on this message. */
  mine?: string[];
  onReact: (emoji: string) => void;
  onCopy: () => void;
  /** Omit to hide the delete row (not own message / not staff). */
  onDelete?: () => void;
}

/**
 * Long-press bottom sheet: quick-reaction row + Copy + (optional) Delete
 * with an in-sheet confirm step. Hand-rolled transparent Modal, same idiom
 * as the app's other sheets — no bottom-sheet dependency.
 */
export function ReactionSheet({
  visible, onClose, mine = [], onReact, onCopy, onDelete,
}: ReactionSheetProps) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  useEffect(() => {
    if (visible) {
      setConfirmingDelete(false);
      if (Platform.OS !== 'web') {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
      }
    }
  }, [visible]);

  const pick = (emoji: string) => {
    if (Platform.OS !== 'web') {
      Haptics.selectionAsync().catch(() => {});
    }
    onReact(emoji);
    onClose();
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.overlay} onPress={onClose}>
        {/* Stop presses inside the sheet from bubbling to the overlay. */}
        <Pressable style={styles.sheet} onPress={() => {}}>
          <View style={styles.handle} />

          <View style={styles.emojiRow}>
            {ALLOWED_REACTIONS.map((emoji) => {
              const active = mine.includes(emoji);
              return (
                <Pressable
                  key={emoji}
                  onPress={() => pick(emoji)}
                  style={({ pressed }) => [
                    styles.emojiBtn,
                    active && styles.emojiBtnActive,
                    pressed && { opacity: 0.7, transform: [{ scale: 0.92 }] },
                  ]}
                >
                  <Text style={styles.emojiGlyph}>{emoji}</Text>
                </Pressable>
              );
            })}
          </View>

          <View style={styles.divider} />

          <Pressable
            onPress={() => { onCopy(); onClose(); }}
            style={({ pressed }) => [styles.actionRow, pressed && styles.actionRowPressed]}
          >
            <Ionicons name="copy-outline" size={19} color={colors.text} />
            <Text style={styles.actionLabel}>{t('community.copyMessage')}</Text>
          </Pressable>

          {onDelete && !confirmingDelete && (
            <Pressable
              onPress={() => setConfirmingDelete(true)}
              style={({ pressed }) => [styles.actionRow, pressed && styles.actionRowPressed]}
            >
              <Ionicons name="trash-outline" size={19} color={colors.error} />
              <Text style={[styles.actionLabel, { color: colors.error }]}>
                {t('community.deleteMessage')}
              </Text>
            </Pressable>
          )}

          {onDelete && confirmingDelete && (
            <View style={styles.confirmRow}>
              <Text style={styles.confirmText} numberOfLines={2}>
                {t('community.deleteMessageConfirm')}
              </Text>
              <View style={styles.confirmActions}>
                <Pressable
                  onPress={() => setConfirmingDelete(false)}
                  style={({ pressed }) => [styles.confirmBtn, pressed && { opacity: 0.7 }]}
                >
                  <Text style={styles.confirmCancelLabel}>{t('cancel')}</Text>
                </Pressable>
                <Pressable
                  onPress={() => { onDelete(); onClose(); }}
                  style={({ pressed }) => [styles.confirmBtn, styles.confirmDeleteBtn, pressed && { opacity: 0.85 }]}
                >
                  <Text style={styles.confirmDeleteLabel}>{t('community.deleteMessage')}</Text>
                </Pressable>
              </View>
            </View>
          )}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.55)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: colors.surfaceHigh,
    borderTopLeftRadius: borderRadius.xl,
    borderTopRightRadius: borderRadius.xl,
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.xl,
    paddingTop: spacing.sm,
  },
  handle: {
    alignSelf: 'center',
    width: 36,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.borderStrong,
    marginBottom: spacing.md,
  },
  emojiRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.xs,
    marginBottom: spacing.sm,
  },
  emojiBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.surface,
  },
  emojiBtnActive: {
    borderWidth: 1.5,
    borderColor: colors.primary,
    backgroundColor: colors.primary + '18',
  },
  emojiGlyph: { fontSize: 24 },
  divider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: colors.border,
    marginVertical: spacing.xs,
  },
  actionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingVertical: 13,
    paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.md,
  },
  actionRowPressed: { backgroundColor: colors.surface },
  actionLabel: { fontSize: 15, fontWeight: '500', color: colors.text },
  confirmRow: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    gap: spacing.sm,
  },
  confirmText: { fontSize: 14, color: colors.textMuted },
  confirmActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm },
  confirmBtn: {
    paddingVertical: 8,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.md,
  },
  confirmDeleteBtn: { backgroundColor: colors.error },
  confirmCancelLabel: {
    fontFamily: fonts.heading,
    fontSize: 13,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    color: colors.textMuted,
  },
  confirmDeleteLabel: {
    fontFamily: fonts.heading,
    fontSize: 13,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    color: colors.background,
  },
});
