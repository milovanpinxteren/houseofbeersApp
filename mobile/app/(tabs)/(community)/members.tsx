import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity, TextInput,
  RefreshControl, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius, fonts } from '../../../src/theme/colors';
import { Card, EmptyState, SkeletonCard } from '../../../src/components/ui';
import { getMembers, CommunityProfile } from '../../../src/api/community';

function MemberCard({ member }: { member: CommunityProfile }) {
  const { language } = useLanguage();
  return (
    <Card
      style={styles.memberCard}
      onPress={() => router.push(`/(tabs)/(community)/member-profile?userId=${member.user_id}`)}
    >
      <View style={styles.memberRow}>
        <View style={styles.avatar}>
          <Ionicons name="person" size={22} color={colors.tertiary} />
        </View>
        <View style={styles.memberInfo}>
          <Text style={styles.memberName}>{member.display_name_resolved}</Text>
          {member.bio ? <Text style={styles.memberBio} numberOfLines={2}>{member.bio}</Text> : null}
          <View style={styles.memberMeta}>
            {member.has_untappd && (
              <View style={styles.metaBadge}>
                <Ionicons name="beer" size={11} color={colors.primary} />
                <Text style={styles.metaText}>Untappd</Text>
              </View>
            )}
            {(member.favorite_count ?? 0) > 0 && (
              <Text style={styles.metaStat}>{member.favorite_count} {t('community.favorites')}</Text>
            )}
            {(member.checkin_count ?? 0) > 0 && (
              <Text style={styles.metaStat}>{member.checkin_count} {t('community.beersTried')}</Text>
            )}
          </View>
        </View>
        <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
      </View>
    </Card>
  );
}

export default function MembersScreen() {
  const { language } = useLanguage();
  const [members, setMembers] = useState<CommunityProfile[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seqRef = useRef(0);

  const loadMembers = useCallback(async (search = '') => {
    const seq = ++seqRef.current;
    try {
      const data = await getMembers(1, search);
      if (seq !== seqRef.current) return; // stale response, a newer request is in flight
      setMembers(data.results);
      setNextPage(data.next ? 2 : null);
    } catch {} finally {
      if (seq === seqRef.current) { setIsLoading(false); setIsRefreshing(false); }
    }
  }, []);

  useEffect(() => { loadMembers(); }, [loadMembers]);

  // Clear any pending debounce timer on unmount
  useEffect(() => () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
  }, []);

  const loadMore = useCallback(async () => {
    if (!nextPage || loadingMore) return;
    const seq = seqRef.current;
    setLoadingMore(true);
    try {
      const data = await getMembers(nextPage, searchQuery);
      if (seq !== seqRef.current) return; // search changed while loading
      setMembers(prev => [...prev, ...data.results]);
      setNextPage(data.next ? nextPage + 1 : null);
    } catch {} finally { setLoadingMore(false); }
  }, [nextPage, loadingMore, searchQuery]);

  const handleSearchChange = (text: string) => {
    setSearchQuery(text);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setIsLoading(true);
      loadMembers(text);
    }, 300);
  };

  const handleClearSearch = () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setSearchQuery('');
    loadMembers('');
  };

  return (
    <View style={styles.container}>
      <View style={styles.searchBar}>
        <Ionicons name="search" size={18} color={colors.textMuted} />
        <TextInput
          style={styles.searchInput}
          placeholder={t('community.searchPlaceholder')}
          placeholderTextColor={colors.textMuted}
          value={searchQuery}
          onChangeText={handleSearchChange}
        />
        {searchQuery ? (
          <TouchableOpacity onPress={handleClearSearch} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
            <Ionicons name="close-circle" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        ) : null}
      </View>
      {isLoading ? (
        <View style={styles.skeletonWrap}>
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </View>
      ) : (
        <FlatList
          data={members}
          keyExtractor={(item) => item.user_id.toString()}
          renderItem={({ item }) => <MemberCard member={item} />}
          ListEmptyComponent={
            <EmptyState
              icon="people-outline"
              title={t('community.noMembers')}
            />
          }
          refreshControl={
            <RefreshControl refreshing={isRefreshing} onRefresh={() => { setIsRefreshing(true); loadMembers(searchQuery); }} tintColor={colors.primary} />
          }
          onEndReached={loadMore}
          onEndReachedThreshold={0.5}
          ListFooterComponent={loadingMore ? <ActivityIndicator color={colors.primary} style={{ padding: spacing.md }} /> : null}
          contentContainerStyle={members.length === 0 ? styles.emptyListContent : styles.listContent}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  skeletonWrap: { padding: spacing.md },
  listContent: { paddingBottom: spacing.xl },
  emptyListContent: { flexGrow: 1, justifyContent: 'center' },

  searchBar: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surfaceLow,
    marginHorizontal: spacing.md,
    marginTop: spacing.sm,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
    minHeight: 44,
  },
  searchInput: { flex: 1, color: colors.text, fontSize: 15, paddingVertical: spacing.sm },

  memberCard: { marginHorizontal: spacing.md, marginTop: spacing.sm },
  memberRow: { flexDirection: 'row', alignItems: 'center' },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.surfaceHigh,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: spacing.md,
  },
  memberInfo: { flex: 1 },
  memberName: { fontFamily: fonts.heading, fontSize: 16, letterSpacing: 0.4, color: colors.text },
  memberBio: { color: colors.textMuted, fontSize: 13, lineHeight: 18, marginTop: 3 },
  memberMeta: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: 6, flexWrap: 'wrap' },
  metaBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: colors.primary + '18',
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: borderRadius.pill,
  },
  metaText: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    color: colors.primary,
  },
  metaStat: { fontSize: 12, color: colors.textMuted },
});
