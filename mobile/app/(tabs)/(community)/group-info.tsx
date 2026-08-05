import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, Alert } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, router } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, fonts, type } from '../../../src/theme/colors';
import {
  Screen, Card, ListItem, SectionHeader, Button, EmptyState, Skeleton,
} from '../../../src/components/ui';
import { getGroupDetail, leaveGroup, GroupDetail } from '../../../src/api/community';

export default function GroupInfoScreen() {
  const { language } = useLanguage();
  const { groupId } = useLocalSearchParams<{ groupId: string }>();
  const gId = parseInt(groupId || '0', 10);
  const [group, setGroup] = useState<GroupDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!gId) return;
    getGroupDetail(gId)
      .then(setGroup)
      .catch(() => {})
      .finally(() => setIsLoading(false));
  }, [gId]);

  const handleLeave = () => {
    Alert.alert(t('community.leaveGroup'), t('community.leaveGroupConfirm'), [
      { text: t('cancel'), style: 'cancel' },
      { text: t('community.leaveGroup'), style: 'destructive', onPress: async () => {
        // Go back to the community tab root — the group chat behind us is now inaccessible.
        try { await leaveGroup(gId); router.replace('/(tabs)/community'); } catch {}
      }},
    ]);
  };

  if (isLoading) {
    return (
      <Screen scroll={false}>
        <View style={styles.skeletonHero}>
          <Skeleton width={72} height={72} radius={36} />
          <Skeleton width={160} height={20} style={{ marginTop: spacing.md }} />
          <Skeleton width={100} height={12} style={{ marginTop: spacing.sm }} />
        </View>
        <Skeleton height={180} radius={20} style={{ marginTop: spacing.lg }} />
      </Screen>
    );
  }

  if (!group) {
    return (
      <Screen scroll={false}>
        <View style={styles.centerFill}>
          <EmptyState icon="alert-circle-outline" title={t('community.groupNotFound')} />
        </View>
      </Screen>
    );
  }

  return (
    <Screen>
      {/* Hero */}
      <View style={styles.hero}>
        <View style={styles.avatarLarge}>
          <Ionicons name="people" size={32} color={colors.primary} />
        </View>
        <Text style={styles.groupName}>{group.name}</Text>
        {group.description ? <Text style={styles.groupDesc}>{group.description}</Text> : null}
        <Text style={styles.memberCount}>
          {group.member_count} {t('community.groupMembers').toLowerCase()}
        </Text>
      </View>

      {/* Members */}
      <SectionHeader title={t('community.groupMembers')} />
      <Card padded={false}>
        {group.members.map((member, index) => (
          <ListItem
            key={member.user_id}
            icon="person"
            label={member.display_name}
            right={member.role === 'admin' ? (
              <View style={styles.adminBadge}>
                <Text style={styles.adminBadgeText}>{t('community.admin')}</Text>
              </View>
            ) : undefined}
            onPress={() => router.push(`/(tabs)/(community)/member-profile?userId=${member.user_id}`)}
            last={index === group.members.length - 1}
          />
        ))}
      </Card>

      <Button
        label={t('community.leaveGroup')}
        onPress={handleLeave}
        variant="danger"
        icon="exit-outline"
        style={styles.leaveBtn}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  centerFill: { flex: 1, justifyContent: 'center' },
  skeletonHero: { alignItems: 'center', paddingTop: spacing.xl },
  hero: { alignItems: 'center', paddingTop: spacing.lg, paddingBottom: spacing.sm },
  avatarLarge: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.primary + '14',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  groupName: {
    ...type.title,
    textAlign: 'center',
  },
  groupDesc: {
    fontFamily: fonts.serif,
    fontSize: 16,
    lineHeight: 23,
    color: colors.textMuted,
    textAlign: 'center',
    marginTop: spacing.xs,
    paddingHorizontal: spacing.lg,
  },
  memberCount: { color: colors.textMuted, fontSize: 12, marginTop: spacing.sm },
  adminBadge: {
    backgroundColor: colors.primary + '1f',
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: 999,
  },
  adminBadgeText: {
    fontFamily: fonts.heading,
    fontSize: 10,
    letterSpacing: 1,
    textTransform: 'uppercase',
    color: colors.primary,
  },
  leaveBtn: { marginTop: spacing.lg },
});
