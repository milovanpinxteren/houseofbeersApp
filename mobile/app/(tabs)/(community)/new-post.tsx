import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, Pressable, ScrollView,
  Image, KeyboardAvoidingView, Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius, fonts, type } from '../../../src/theme/colors';
import { Button, Card, useToast } from '../../../src/components/ui';
import { createPost } from '../../../src/api/community';
import { getFavorites } from '../../../src/api/recommendations';

interface BeerAttachment {
  beer_id: string;
  beer_title: string;
  beer_vendor: string;
  beer_image_url: string;
  beer_style: string;
  beer_rating: number | null;
}

export default function NewPostScreen() {
  const { language } = useLanguage();
  const [content, setContent] = useState('');
  const [postType, setPostType] = useState<'text' | 'review' | 'share'>('text');
  const [beer, setBeer] = useState<BeerAttachment | null>(null);
  const [favorites, setFavorites] = useState<any[]>([]);
  const [showBeerPicker, setShowBeerPicker] = useState(false);
  const [isPosting, setIsPosting] = useState(false);
  const { showToast } = useToast();

  useEffect(() => {
    getFavorites()
      .then((data) => setFavorites(data.favorites))
      .catch(() => {});
  }, []);

  const handlePost = async () => {
    if (!content.trim()) return;
    setIsPosting(true);
    try {
      await createPost({
        post_type: postType,
        content: content.trim(),
        ...(beer ? {
          beer_id: beer.beer_id,
          beer_title: beer.beer_title,
          beer_vendor: beer.beer_vendor,
          beer_image_url: beer.beer_image_url,
          beer_style: beer.beer_style,
          beer_rating: beer.beer_rating ?? undefined,
        } : {}),
      });
      router.back();
    } catch {
      showToast(t('community.postError'), 'error');
    } finally {
      setIsPosting(false);
    }
  };

  const selectBeer = (fav: any) => {
    setBeer({
      beer_id: fav.beer_id,
      beer_title: fav.title,
      beer_vendor: fav.vendor || '',
      beer_image_url: fav.image_url || '',
      beer_style: fav.style || '',
      beer_rating: fav.untappd_rating,
    });
    setPostType(postType === 'text' ? 'share' : postType);
    setShowBeerPicker(false);
  };

  const postTypes = [
    { key: 'text' as const, label: t('community.textPost'), icon: 'chatbubble' as const },
    { key: 'share' as const, label: t('community.shareBeer'), icon: 'share-social' as const },
    { key: 'review' as const, label: t('community.shareReview'), icon: 'star' as const },
  ];

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView style={styles.container} contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
        {/* Post type selector */}
        <View style={styles.typeRow}>
          {postTypes.map(({ key, label, icon }) => (
            <Pressable
              key={key}
              style={({ pressed }) => [
                styles.typeBtn,
                postType === key && styles.typeBtnActive,
                pressed && { opacity: 0.85 },
              ]}
              onPress={() => setPostType(key)}
            >
              <Ionicons name={icon} size={15} color={postType === key ? colors.background : colors.textMuted} />
              <Text style={[styles.typeText, postType === key && styles.typeTextActive]}>
                {label}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Content input */}
        <TextInput
          style={styles.textInput}
          placeholder={t('community.postPlaceholder')}
          placeholderTextColor={colors.textMuted}
          value={content}
          onChangeText={setContent}
          multiline
          maxLength={1000}
          autoFocus
        />
        <Text style={styles.charCount}>{content.length}/1000</Text>

        {/* Attached beer */}
        {beer && (
          <Card variant="inset" style={styles.attachedBeer} padded={false}>
            <View style={styles.attachedBeerInner}>
              {beer.beer_image_url ? (
                <Image source={{ uri: beer.beer_image_url }} style={styles.attachedBeerImg} />
              ) : (
                <View style={styles.attachedBeerPlaceholder}>
                  <Ionicons name="beer" size={20} color={colors.tertiary} />
                </View>
              )}
              <View style={styles.attachedBeerInfo}>
                <Text style={styles.attachedBeerTitle} numberOfLines={1}>{beer.beer_title}</Text>
                {beer.beer_vendor ? (
                  <Text style={styles.attachedBeerVendor} numberOfLines={1}>{beer.beer_vendor}</Text>
                ) : null}
              </View>
              <TouchableOpacity
                onPress={() => setBeer(null)}
                hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
              >
                <Ionicons name="close-circle" size={22} color={colors.textMuted} />
              </TouchableOpacity>
            </View>
          </Card>
        )}

        {/* Attach beer button */}
        {!beer && (
          <Button
            label={t('community.attachBeer')}
            onPress={() => setShowBeerPicker(true)}
            variant="ghost"
            size="sm"
            icon="beer"
            style={styles.attachBtn}
          />
        )}

        {/* Beer picker */}
        {showBeerPicker && (
          <Card style={styles.beerPicker}>
            <Text style={styles.pickerTitle}>{t('community.selectBeer')}</Text>
            {favorites.length === 0 ? (
              <Text style={styles.noBeer}>{t('community.noBeerToAttach')}</Text>
            ) : (
              favorites.map((fav: any, index: number) => (
                <Pressable
                  key={fav.id}
                  style={({ pressed }) => [
                    styles.pickerItem,
                    index > 0 && styles.pickerItemDivider,
                    pressed && { opacity: 0.7 },
                  ]}
                  onPress={() => selectBeer(fav)}
                >
                  {fav.image_url ? (
                    <Image source={{ uri: fav.image_url }} style={styles.pickerItemImg} />
                  ) : (
                    <View style={styles.pickerItemPlaceholder}>
                      <Ionicons name="beer" size={16} color={colors.tertiary} />
                    </View>
                  )}
                  <View style={{ flex: 1 }}>
                    <Text style={styles.pickerItemTitle} numberOfLines={1}>{fav.title}</Text>
                    {fav.vendor ? <Text style={styles.pickerItemMeta}>{fav.vendor}</Text> : null}
                  </View>
                  <Ionicons name="add-circle-outline" size={20} color={colors.primary} />
                </Pressable>
              ))
            )}
          </Card>
        )}
      </ScrollView>

      {/* Post button */}
      <View style={styles.footer}>
        <Button
          label={t('community.post')}
          onPress={handlePost}
          loading={isPosting}
          disabled={!content.trim()}
        />
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  scrollContent: { padding: spacing.md },

  typeRow: { flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.md },
  typeBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 5,
    minHeight: 40,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.xs,
    borderRadius: borderRadius.pill,
    backgroundColor: colors.surface,
  },
  typeBtnActive: { backgroundColor: colors.primary },
  typeText: {
    fontFamily: fonts.heading,
    fontSize: 11,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    color: colors.textMuted,
  },
  typeTextActive: { color: colors.background },

  textInput: {
    backgroundColor: colors.surfaceLow,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    paddingTop: spacing.md,
    color: colors.text,
    fontFamily: fonts.serif,
    fontSize: 17,
    lineHeight: 24,
    minHeight: 140,
    textAlignVertical: 'top',
  },
  charCount: { color: colors.textMuted, fontSize: 12, textAlign: 'right', marginTop: spacing.xs },

  attachedBeer: { marginTop: spacing.md },
  attachedBeerInner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.sm,
  },
  attachedBeerImg: { width: 44, height: 44, borderRadius: borderRadius.sm },
  attachedBeerPlaceholder: {
    width: 44,
    height: 44,
    borderRadius: borderRadius.sm,
    backgroundColor: colors.surfaceHigh,
    justifyContent: 'center',
    alignItems: 'center',
  },
  attachedBeerInfo: { flex: 1 },
  attachedBeerTitle: { fontFamily: fonts.heading, fontSize: 14, letterSpacing: 0.3, color: colors.text },
  attachedBeerVendor: { color: colors.textMuted, fontSize: 12, marginTop: 2 },

  attachBtn: { alignSelf: 'flex-start', marginTop: spacing.sm },

  beerPicker: { marginTop: spacing.sm },
  pickerTitle: { ...type.label, marginBottom: spacing.sm },
  noBeer: { fontFamily: fonts.serif, fontSize: 15, color: colors.textMuted },
  pickerItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm + 2,
    minHeight: 48,
  },
  pickerItemDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  pickerItemImg: { width: 36, height: 36, borderRadius: borderRadius.sm },
  pickerItemPlaceholder: {
    width: 36,
    height: 36,
    borderRadius: borderRadius.sm,
    backgroundColor: colors.surfaceHigh,
    justifyContent: 'center',
    alignItems: 'center',
  },
  pickerItemTitle: { color: colors.text, fontSize: 14, fontWeight: '500' },
  pickerItemMeta: { color: colors.textMuted, fontSize: 12, marginTop: 1 },

  footer: {
    padding: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    backgroundColor: colors.background,
  },
});
