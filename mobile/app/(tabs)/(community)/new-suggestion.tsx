import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TextInput,
  KeyboardAvoidingView, Platform, ScrollView,
} from 'react-native';
import { router } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius, type } from '../../../src/theme/colors';
import { Button, useToast } from '../../../src/components/ui';
import { createSuggestion } from '../../../src/api/community';

export default function NewSuggestionScreen() {
  const { language } = useLanguage();
  const { showToast } = useToast();
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [tag, setTag] = useState('');
  const [isPosting, setIsPosting] = useState(false);

  const handleSubmit = async () => {
    if (!title.trim() || !content.trim()) return;
    setIsPosting(true);
    try {
      await createSuggestion({
        title: title.trim(),
        content: content.trim(),
        ...(tag.trim() ? { tag: tag.trim() } : {}),
      });
      router.back();
    } catch {
      showToast(t('community.suggestionError'), 'error');
    } finally {
      setIsPosting(false);
    }
  };

  const canSubmit = title.trim().length > 0 && content.trim().length > 0 && !isPosting;

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView style={styles.container} contentContainerStyle={styles.scrollContent}>
        {/* Title */}
        <Text style={styles.label}>{t('community.suggestionTitle')}</Text>
        <TextInput
          style={styles.titleInput}
          placeholder={t('community.suggestionTitlePlaceholder')}
          placeholderTextColor={colors.textMuted}
          value={title}
          onChangeText={setTitle}
          maxLength={200}
          autoFocus
        />

        {/* Content */}
        <Text style={styles.label}>{t('community.suggestionContent')}</Text>
        <TextInput
          style={styles.contentInput}
          placeholder={t('community.suggestionContentPlaceholder')}
          placeholderTextColor={colors.textMuted}
          value={content}
          onChangeText={setContent}
          multiline
          maxLength={1000}
        />
        <Text style={styles.charCount}>{content.length}/1000</Text>

        {/* Tag */}
        <Text style={styles.label}>{t('community.suggestionTag')}</Text>
        <TextInput
          style={styles.tagInput}
          placeholder={t('community.suggestionTagPlaceholder')}
          placeholderTextColor={colors.textMuted}
          value={tag}
          onChangeText={setTag}
          maxLength={50}
        />
      </ScrollView>

      {/* Submit button */}
      <View style={styles.footer}>
        <Button
          label={t('community.submitSuggestion')}
          onPress={handleSubmit}
          disabled={!canSubmit}
          loading={isPosting}
        />
      </View>
    </KeyboardAvoidingView>
  );
}

const inputBase = {
  backgroundColor: colors.surfaceLow,
  borderRadius: borderRadius.md,
  padding: spacing.md,
  color: colors.text,
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  scrollContent: { padding: spacing.md, paddingBottom: spacing.lg },
  label: {
    ...type.label,
    marginBottom: spacing.sm,
    marginTop: spacing.lg,
  },
  titleInput: {
    ...inputBase,
    fontSize: 16,
  },
  contentInput: {
    ...inputBase,
    fontSize: 15,
    lineHeight: 21,
    minHeight: 140,
    textAlignVertical: 'top' as const,
  },
  charCount: { color: colors.textMuted, fontSize: 11, textAlign: 'right', marginTop: spacing.xs },
  tagInput: {
    ...inputBase,
    fontSize: 15,
  },
  footer: {
    padding: spacing.md,
    paddingBottom: spacing.lg,
    backgroundColor: colors.background,
  },
});
