import { useState } from 'react';
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { t } from '../../i18n';
import { colors, spacing, borderRadius, fonts } from '../../theme/colors';
import { COMPOSER_EMOJI } from './emoji';

interface MessageComposerProps {
  value: string;
  onChangeText: (text: string) => void;
  onSend: () => void;
  sending?: boolean;
  maxLength?: number;
  placeholder?: string;
}

/**
 * Shared chat input bar: emoji toggle + multiline input + send button.
 * The emoji strip is a curated in-house grid (system emoji render natively),
 * deliberately not an external picker dependency. Emoji append at the end of
 * the draft — RN cursor tracking isn't worth the complexity here.
 */
export function MessageComposer({
  value, onChangeText, onSend, sending, maxLength = 500, placeholder,
}: MessageComposerProps) {
  const [showEmoji, setShowEmoji] = useState(false);
  const canSend = !!value.trim() && !sending;

  return (
    <View style={styles.wrap}>
      {showEmoji && (
        <ScrollView style={styles.emojiStrip} keyboardShouldPersistTaps="always">
          {COMPOSER_EMOJI.map((section) => (
            <View key={section.labelKey}>
              <Text style={styles.sectionLabel}>{t(section.labelKey)}</Text>
              <View style={styles.emojiGrid}>
                {section.emoji.map((emoji) => (
                  <Pressable
                    key={emoji}
                    onPress={() => onChangeText((value + emoji).slice(0, maxLength))}
                    style={({ pressed }) => [styles.emojiCell, pressed && { opacity: 0.6 }]}
                  >
                    <Text style={styles.emojiGlyph}>{emoji}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
          ))}
        </ScrollView>
      )}

      <View style={styles.inputBar}>
        <Pressable
          onPress={() => setShowEmoji((v) => !v)}
          hitSlop={6}
          style={({ pressed }) => [styles.emojiToggle, pressed && { opacity: 0.6 }]}
        >
          <Ionicons
            name={showEmoji ? 'close-outline' : 'happy-outline'}
            size={24}
            color={showEmoji ? colors.primary : colors.textMuted}
          />
        </Pressable>
        <TextInput
          style={styles.textInput}
          placeholder={placeholder ?? t('community.messagePlaceholder')}
          placeholderTextColor={colors.textMuted}
          value={value}
          onChangeText={onChangeText}
          maxLength={maxLength}
          multiline
        />
        <Pressable
          style={({ pressed }) => [
            styles.sendBtn,
            !canSend && styles.sendBtnDisabled,
            pressed && canSend && { opacity: 0.85, transform: [{ scale: 0.96 }] },
          ]}
          onPress={onSend}
          disabled={!canSend}
        >
          {sending ? (
            <ActivityIndicator size="small" color={colors.background} />
          ) : (
            <Ionicons name="send" size={18} color={colors.background} />
          )}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    backgroundColor: colors.background,
  },
  emojiStrip: {
    height: 200,
    backgroundColor: colors.surfaceLow,
    paddingHorizontal: spacing.sm,
  },
  sectionLabel: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: colors.textMuted,
    marginTop: spacing.sm,
    marginBottom: 2,
    marginLeft: spacing.xs,
  },
  emojiGrid: { flexDirection: 'row', flexWrap: 'wrap' },
  emojiCell: {
    width: '16.66%',
    paddingVertical: 7,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emojiGlyph: { fontSize: 26 },
  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    padding: spacing.sm,
    paddingHorizontal: spacing.sm,
    gap: spacing.sm,
  },
  emojiToggle: {
    width: 36,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
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
});
