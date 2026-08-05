import React, { useState, useEffect, useCallback } from 'react';
import { View, Text, StyleSheet, FlatList, RefreshControl } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius, fonts } from '../../../src/theme/colors';
import { Card, Button, EmptyState, SkeletonCard } from '../../../src/components/ui';
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

  const openChat = (item: Group) =>
    router.push(`/(tabs)/(community)/group-chat?groupId=${item.id}&groupName=${encodeURIComponent(item.name)}`);

  if (isLoading) {
    return (
      <View style={[styles.container, { paddingTop: spacing.md, paddingHorizontal: spacing.md }]}>
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <FlatList
        data={groups}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => (
          <Card
            style={styles.groupCard}
            onPress={item.is_member ? () => openChat(item) : undefined}
          >
            <View style={styles.cardRow}>
              <View style={styles.avatar}>
                <Ionicons name="people" size={22} color={colors.primary} />
              </View>
              <View style={styles.groupInfo}>
                <Text style={styles.groupName} numberOfLines={1}>{item.name}</Text>
                <Text style={styles.groupMeta}>
                  {item.member_count} {t('community.groupMembers').toLowerCase()}
                </Text>
              </View>
              {item.is_member ? (
                <Button
                  label={t('community.joined')}
                  onPress={() => openChat(item)}
                  variant="secondary"
                  size="sm"
                  icon="checkmark"
                />
              ) : (
                <Button
                  label={t('community.joinGroup')}
                  onPress={() => handleJoin(item.id)}
                  size="sm"
                  loading={joiningId === item.id}
                />
              )}
            </View>
            {item.description ? (
              <Text style={styles.groupDesc} numberOfLines={2}>{item.description}</Text>
            ) : null}
          </Card>
        )}
        ListEmptyComponent={
          <View style={styles.emptyWrap}>
            <EmptyState
              icon="people-outline"
              title={t('community.noGroups')}
              message={t('community.noGroupsHint')}
            />
          </View>
        }
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={() => { setIsRefreshing(true); load(); }}
            tintColor={colors.primary}
          />
        }
        contentContainerStyle={groups.length === 0 ? { flex: 1 } : styles.listContent}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  listContent: { padding: spacing.md, paddingBottom: spacing.xl },
  groupCard: { marginBottom: spacing.sm },
  cardRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  avatar: {
    width: 46,
    height: 46,
    borderRadius: borderRadius.md,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
  },
  groupInfo: { flex: 1 },
  groupName: {
    fontFamily: fonts.heading,
    fontSize: 17,
    letterSpacing: 0.4,
    color: colors.text,
  },
  groupMeta: { color: colors.textMuted, fontSize: 12, marginTop: 2 },
  groupDesc: {
    fontFamily: fonts.serif,
    fontSize: 15,
    lineHeight: 21,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
  emptyWrap: { flex: 1, justifyContent: 'center' },
});
