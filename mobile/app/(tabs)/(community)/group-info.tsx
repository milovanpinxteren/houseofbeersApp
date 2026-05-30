import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, router } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
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
        try { await leaveGroup(gId); router.back(); } catch {}
      }},
    ]);
  };

  if (isLoading) return <View style={[styles.container, styles.center]}><ActivityIndicator size="large" color={colors.primary} /></View>;
  if (!group) return <View style={[styles.container, styles.center]}><Text style={styles.emptyText}>Group not found</Text></View>;

  return (
    <ScrollView style={styles.container}>
      <View style={styles.header}>
        <View style={styles.avatarLarge}>
          <Ionicons name="people" size={36} color={colors.primary} />
        </View>
        <Text style={styles.groupName}>{group.name}</Text>
        {group.description ? <Text style={styles.groupDesc}>{group.description}</Text> : null}
        <Text style={styles.memberCount}>{group.member_count} {t('community.groupMembers').toLowerCase()}</Text>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>{t('community.groupMembers')}</Text>
        {group.members.map((member) => (
          <TouchableOpacity
            key={member.user_id}
            style={styles.memberRow}
            onPress={() => router.push(`/(tabs)/(community)/member-profile?userId=${member.user_id}`)}
          >
            <View style={styles.avatarSm}>
              <Ionicons name="person" size={16} color={colors.textMuted} />
            </View>
            <Text style={styles.memberName}>{member.display_name}</Text>
            {member.role === 'admin' && (
              <View style={styles.adminBadge}>
                <Text style={styles.adminBadgeText}>Admin</Text>
              </View>
            )}
          </TouchableOpacity>
        ))}
      </View>

      <TouchableOpacity style={styles.leaveBtn} onPress={handleLeave}>
        <Ionicons name="exit-outline" size={20} color={colors.error} />
        <Text style={styles.leaveBtnText}>{t('community.leaveGroup')}</Text>
      </TouchableOpacity>

      <View style={{ height: spacing.xl }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  header: { alignItems: 'center', padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.tertiary + '20' },
  avatarLarge: { width: 72, height: 72, borderRadius: 36, backgroundColor: colors.primary + '20', justifyContent: 'center', alignItems: 'center', marginBottom: spacing.md },
  groupName: { color: colors.text, fontSize: 22, fontWeight: '700' },
  groupDesc: { color: colors.textMuted, fontSize: 14, textAlign: 'center', marginTop: spacing.xs, paddingHorizontal: spacing.lg },
  memberCount: { color: colors.textMuted, fontSize: 13, marginTop: spacing.sm },
  section: { padding: spacing.md },
  sectionTitle: { color: colors.primary, fontSize: 16, fontWeight: '700', marginBottom: spacing.md },
  memberRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: spacing.sm, gap: spacing.sm },
  avatarSm: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.tertiary + '30', justifyContent: 'center', alignItems: 'center' },
  memberName: { color: colors.text, fontSize: 15, flex: 1 },
  adminBadge: { backgroundColor: colors.primary + '30', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 8 },
  adminBadgeText: { color: colors.primary, fontSize: 11, fontWeight: '700' },
  leaveBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm, marginHorizontal: spacing.md, marginTop: spacing.lg, padding: spacing.md, borderRadius: borderRadius.md, borderWidth: 1, borderColor: colors.error },
  leaveBtnText: { color: colors.error, fontSize: 15, fontWeight: '600' },
  emptyText: { color: colors.textMuted, fontSize: 14 },
});
