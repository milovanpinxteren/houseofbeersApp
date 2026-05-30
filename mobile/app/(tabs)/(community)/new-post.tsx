import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView,
  Image, ActivityIndicator, Alert, KeyboardAvoidingView, Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
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
      Alert.alert(t('error'), t('community.postError'));
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
      <ScrollView style={styles.container} contentContainerStyle={styles.scrollContent}>
        {/* Post type selector */}
        <View style={styles.typeRow}>
          {postTypes.map(({ key, label, icon }) => (
            <TouchableOpacity
              key={key}
              style={[styles.typeBtn, postType === key && styles.typeBtnActive]}
              onPress={() => setPostType(key)}
            >
              <Ionicons name={icon} size={16} color={postType === key ? colors.background : colors.textMuted} />
              <Text style={[styles.typeText, postType === key && styles.typeTextActive]}>
                {label}
              </Text>
            </TouchableOpacity>
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
          <View style={styles.attachedBeer}>
            {beer.beer_image_url ? (
              <Image source={{ uri: beer.beer_image_url }} style={styles.attachedBeerImg} />
            ) : null}
            <View style={styles.attachedBeerInfo}>
              <Text style={styles.attachedBeerTitle} numberOfLines={1}>{beer.beer_title}</Text>
              <Text style={styles.attachedBeerVendor} numberOfLines={1}>{beer.beer_vendor}</Text>
            </View>
            <TouchableOpacity onPress={() => setBeer(null)}>
              <Ionicons name="close-circle" size={22} color={colors.textMuted} />
            </TouchableOpacity>
          </View>
        )}

        {/* Attach beer button */}
        {!beer && (
          <TouchableOpacity
            style={styles.attachBtn}
            onPress={() => setShowBeerPicker(true)}
          >
            <Ionicons name="beer" size={18} color={colors.primary} />
            <Text style={styles.attachBtnText}>{t('community.attachBeer')}</Text>
          </TouchableOpacity>
        )}

        {/* Beer picker */}
        {showBeerPicker && (
          <View style={styles.beerPicker}>
            <Text style={styles.pickerTitle}>{t('community.selectBeer')}</Text>
            {favorites.length === 0 ? (
              <Text style={styles.noBeer}>{t('community.noBeerToAttach')}</Text>
            ) : (
              favorites.map((fav: any) => (
                <TouchableOpacity
                  key={fav.id}
                  style={styles.pickerItem}
                  onPress={() => selectBeer(fav)}
                >
                  {fav.image_url ? (
                    <Image source={{ uri: fav.image_url }} style={styles.pickerItemImg} />
                  ) : null}
                  <View style={{ flex: 1 }}>
                    <Text style={styles.pickerItemTitle} numberOfLines={1}>{fav.title}</Text>
                    <Text style={styles.pickerItemMeta}>{fav.vendor}</Text>
                  </View>
                </TouchableOpacity>
              ))
            )}
          </View>
        )}
      </ScrollView>

      {/* Post button */}
      <View style={styles.footer}>
        <TouchableOpacity
          style={[styles.postBtn, (!content.trim() || isPosting) && styles.postBtnDisabled]}
          onPress={handlePost}
          disabled={!content.trim() || isPosting}
        >
          {isPosting ? (
            <ActivityIndicator size="small" color={colors.background} />
          ) : (
            <Text style={styles.postBtnText}>{t('community.post')}</Text>
          )}
        </TouchableOpacity>
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
    gap: 4,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.sm,
    backgroundColor: colors.surface,
  },
  typeBtnActive: { backgroundColor: colors.primary },
  typeText: { color: colors.textMuted, fontSize: 12, fontWeight: '600' },
  typeTextActive: { color: colors.background },
  textInput: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    color: colors.text,
    fontSize: 16,
    minHeight: 120,
    textAlignVertical: 'top',
  },
  charCount: { color: colors.textMuted, fontSize: 12, textAlign: 'right', marginTop: 4 },
  attachedBeer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.sm,
    padding: spacing.sm,
    marginTop: spacing.md,
    gap: spacing.sm,
  },
  attachedBeerImg: { width: 44, height: 44, borderRadius: 6 },
  attachedBeerInfo: { flex: 1 },
  attachedBeerTitle: { color: colors.text, fontSize: 14, fontWeight: '600' },
  attachedBeerVendor: { color: colors.textMuted, fontSize: 12 },
  attachBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginTop: spacing.md,
    padding: spacing.sm,
  },
  attachBtnText: { color: colors.primary, fontSize: 14, fontWeight: '600' },
  beerPicker: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginTop: spacing.sm,
  },
  pickerTitle: { color: colors.text, fontSize: 14, fontWeight: '600', marginBottom: spacing.sm },
  noBeer: { color: colors.textMuted, fontSize: 13 },
  pickerItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.tertiary + '20',
  },
  pickerItemImg: { width: 36, height: 36, borderRadius: 4 },
  pickerItemTitle: { color: colors.text, fontSize: 14 },
  pickerItemMeta: { color: colors.textMuted, fontSize: 12 },
  footer: {
    padding: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.tertiary + '20',
  },
  postBtn: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  postBtnDisabled: { opacity: 0.5 },
  postBtnText: { color: colors.background, fontSize: 16, fontWeight: '700' },
});
