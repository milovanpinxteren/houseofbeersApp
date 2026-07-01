import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity,
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform, ScrollView,
} from 'react-native';
import { router } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
import { createSuggestion } from '../../../src/api/community';

export default function NewSuggestionScreen() {
  const { language } = useLanguage();
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
      Alert.alert(t('error'), t('community.suggestionError'));
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
        <TouchableOpacity
          style={[styles.submitBtn, !canSubmit && styles.submitBtnDisabled]}
          onPress={handleSubmit}
          disabled={!canSubmit}
        >
          {isPosting ? (
            <ActivityIndicator size="small" color={colors.background} />
          ) : (
            <Text style={styles.submitBtnText}>{t('community.submitSuggestion')}</Text>
          )}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  scrollContent: { padding: spacing.md },
  label: { color: colors.text, fontSize: 14, fontWeight: '600', marginBottom: spacing.xs, marginTop: spacing.md },
  titleInput: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    color: colors.text,
    fontSize: 16,
  },
  contentInput: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    color: colors.text,
    fontSize: 15,
    minHeight: 120,
    textAlignVertical: 'top',
  },
  charCount: { color: colors.textMuted, fontSize: 12, textAlign: 'right', marginTop: 4 },
  tagInput: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    color: colors.text,
    fontSize: 15,
  },
  footer: {
    padding: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.tertiary + '20',
  },
  submitBtn: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  submitBtnDisabled: { opacity: 0.5 },
  submitBtnText: { color: colors.background, fontSize: 16, fontWeight: '700' },
});
