import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity, TextInput,
  RefreshControl, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
import { getMembers, CommunityProfile } from '../../../src/api/community';

function MemberCard({ member }: { member: CommunityProfile }) {
  const { language } = useLanguage();
  return (
    <TouchableOpacity
      style={styles.memberCard}
      onPress={() => router.push(`/(tabs)/(community)/member-profile?userId=${member.user_id}`)}
      activeOpacity={0.7}
    >
      <View style={styles.avatar}>
        <Ionicons name="person" size={24} color={colors.textMuted} />
      </View>
      <View style={styles.memberInfo}>
        <Text style={styles.memberName}>{member.display_name_resolved}</Text>
        {member.bio ? <Text style={styles.memberBio} numberOfLines={2}>{member.bio}</Text> : null}
        <View style={styles.memberMeta}>
          {member.has_untappd && (
            <View style={styles.metaBadge}>
              <Ionicons name="beer" size={12} color={colors.primary} />
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
      <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
    </TouchableOpacity>
  );
}

export default function MembersScreen() {
  const { language } = useLanguage();
  const [members, setMembers] = useState<CommunityProfile[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadMembers = useCallback(async (search = '') => {
    try {
      const data = await getMembers(1, search);
      setMembers(data.results);
    } catch {} finally { setIsLoading(false); setIsRefreshing(false); }
  }, []);

  useEffect(() => { loadMembers(); }, [loadMembers]);

  const handleSearchChange = (text: string) => {
    setSearchQuery(text);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setIsLoading(true);
      loadMembers(text);
    }, 300);
  };

  if (isLoading && !searchQuery) {
    return <View style={[styles.container, styles.center]}><ActivityIndicator size="large" color={colors.primary} /></View>;
  }

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
          <TouchableOpacity onPress={() => { setSearchQuery(''); loadMembers(''); }}>
            <Ionicons name="close-circle" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        ) : null}
      </View>
      <FlatList
        data={members}
        keyExtractor={(item) => item.user_id.toString()}
        renderItem={({ item }) => <MemberCard member={item} />}
        ListEmptyComponent={
          <View style={[styles.center, { paddingTop: 60 }]}>
            <Ionicons name="people-outline" size={48} color={colors.textMuted} />
            <Text style={styles.emptyText}>{t('community.noMembers')}</Text>
          </View>
        }
        refreshControl={
          <RefreshControl refreshing={isRefreshing} onRefresh={() => { setIsRefreshing(true); loadMembers(searchQuery); }} tintColor={colors.primary} />
        }
        contentContainerStyle={members.length === 0 ? { flex: 1 } : { paddingBottom: spacing.lg }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { justifyContent: 'center', alignItems: 'center' },
  searchBar: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.surface, marginHorizontal: spacing.md, marginTop: spacing.sm, borderRadius: borderRadius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, gap: spacing.sm },
  searchInput: { flex: 1, color: colors.text, fontSize: 15 },
  memberCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.surface, marginHorizontal: spacing.md, marginTop: spacing.sm, borderRadius: borderRadius.md, padding: spacing.md },
  avatar: { width: 48, height: 48, borderRadius: 24, backgroundColor: colors.tertiary + '30', justifyContent: 'center', alignItems: 'center', marginRight: spacing.md },
  memberInfo: { flex: 1 },
  memberName: { color: colors.text, fontSize: 16, fontWeight: '600' },
  memberBio: { color: colors.textMuted, fontSize: 13, marginTop: 2 },
  memberMeta: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: 4 },
  metaBadge: { flexDirection: 'row', alignItems: 'center', gap: 2, backgroundColor: colors.primary + '20', paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  metaText: { fontSize: 11, color: colors.primary, fontWeight: '600' },
  metaStat: { fontSize: 12, color: colors.textMuted },
  emptyText: { color: colors.textMuted, fontSize: 15, marginTop: spacing.md },
});
