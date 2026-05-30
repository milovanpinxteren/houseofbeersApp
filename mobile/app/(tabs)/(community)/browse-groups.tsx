import React, { useState, useEffect, useCallback } from 'react';
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity,
  ActivityIndicator, RefreshControl,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
import { getAvailableGroups, joinGroup, Group } from '../../../src/api/community';

export default function BrowseGroupsScreen() {
  const { language } = useLanguage();
  const [groups, setGroups] = useState<Group[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [joiningId, setJoiningId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try { const data = await getAvailableGroups(); setGroups(data.groups); }
    catch {} finally { setIsLoading(false); setIsRefreshing(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleJoin = async (groupId: number) => {
    setJoiningId(groupId);
    try {
      await joinGroup(groupId);
      setGroups(prev => prev.map(g => g.id === groupId ? { ...g, is_member: true, member_count: g.member_count + 1 } : g));
    } catch {} finally { setJoiningId(null); }
  };

  if (isLoading) return <View style={[styles.container, styles.center]}><ActivityIndicator size="large" color={colors.primary} /></View>;

  return (
    <View style={styles.container}>
      <FlatList
        data={groups}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => (
          <View style={styles.groupCard}>
            <View style={styles.avatar}>
              <Ionicons name="people" size={24} color={colors.primary} />
            </View>
            <View style={styles.groupInfo}>
              <Text style={styles.groupName}>{item.name}</Text>
              {item.description ? <Text style={styles.groupDesc} numberOfLines={2}>{item.description}</Text> : null}
              <Text style={styles.groupMeta}>{item.member_count} {t('community.groupMembers').toLowerCase()}</Text>
            </View>
            {item.is_member ? (
              <TouchableOpacity
                style={styles.joinedBtn}
                onPress={() => router.push(`/(tabs)/(community)/group-chat?groupId=${item.id}&groupName=${encodeURIComponent(item.name)}`)}
              >
                <Text style={styles.joinedBtnText}>{t('community.joined')}</Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity
                style={styles.joinBtn}
                onPress={() => handleJoin(item.id)}
                disabled={joiningId === item.id}
              >
                {joiningId === item.id ? (
                  <ActivityIndicator size="small" color={colors.background} />
                ) : (
                  <Text style={styles.joinBtnText}>{t('community.joinGroup')}</Text>
                )}
              </TouchableOpacity>
            )}
          </View>
        )}
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <Ionicons name="people-outline" size={48} color={colors.textMuted} />
            <Text style={styles.emptyText}>{t('community.noGroups')}</Text>
          </View>
        }
        refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={() => { setIsRefreshing(true); load(); }} tintColor={colors.primary} />}
        contentContainerStyle={groups.length === 0 ? { flex: 1 } : { paddingBottom: spacing.lg }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  groupCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.surface, marginHorizontal: spacing.md, marginTop: spacing.sm, borderRadius: borderRadius.md, padding: spacing.md },
  avatar: { width: 48, height: 48, borderRadius: 24, backgroundColor: colors.primary + '20', justifyContent: 'center', alignItems: 'center', marginRight: spacing.md },
  groupInfo: { flex: 1 },
  groupName: { color: colors.text, fontSize: 16, fontWeight: '600' },
  groupDesc: { color: colors.textMuted, fontSize: 13, marginTop: 2 },
  groupMeta: { color: colors.textMuted, fontSize: 12, marginTop: 4 },
  joinBtn: { backgroundColor: colors.primary, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: borderRadius.sm },
  joinBtnText: { color: colors.background, fontSize: 13, fontWeight: '700' },
  joinedBtn: { backgroundColor: colors.primary + '20', paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: borderRadius.sm },
  joinedBtnText: { color: colors.primary, fontSize: 13, fontWeight: '700' },
  emptyState: { flex: 1, justifyContent: 'center', alignItems: 'center', gap: spacing.md },
  emptyText: { color: colors.textMuted, fontSize: 15 },
});
