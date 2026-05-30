import React, { useState, useCallback, useEffect } from 'react';
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity,
  RefreshControl, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useLanguage } from '../../../src/context/LanguageContext';
import { useAuth } from '../../../src/context/AuthContext';
import { t } from '../../../src/i18n';
import { colors, spacing, borderRadius } from '../../../src/theme/colors';
import { getConversations, ConversationSummary } from '../../../src/api/community';

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return '<1m';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

export default function MessagesScreen() {
  const { language } = useLanguage();
  const { user } = useAuth();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const loadConversations = useCallback(async () => {
    try {
      const data = await getConversations();
      setConversations(data.conversations);
    } catch {
      // silent
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => { loadConversations(); }, [loadConversations]);

  if (isLoading) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <FlatList
        data={conversations}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => {
          const lastMsg = item.last_message;
          const isOwnLastMsg = lastMsg?.sender_id === user?.id;
          const preview = lastMsg
            ? (lastMsg.has_beer ? '🍺 ' : '') + (isOwnLastMsg ? `${t('community.you')}: ` : '') + lastMsg.content
            : '';

          return (
            <TouchableOpacity
              style={styles.conversationCard}
              onPress={() => router.push(
                `/(tabs)/(community)/conversation?conversationId=${item.id}&name=${item.other_user.display_name}`
              )}
              activeOpacity={0.7}
            >
              <View style={styles.avatar}>
                <Ionicons name="person" size={20} color={colors.textMuted} />
              </View>
              <View style={styles.convInfo}>
                <View style={styles.convHeader}>
                  <Text style={[styles.convName, item.unread_count > 0 && styles.convNameBold]}>
                    {item.other_user.display_name}
                  </Text>
                  {lastMsg && (
                    <Text style={styles.convTime}>{timeAgo(lastMsg.created_at)}</Text>
                  )}
                </View>
                {preview ? (
                  <Text
                    style={[styles.convPreview, item.unread_count > 0 && styles.convPreviewUnread]}
                    numberOfLines={1}
                  >
                    {preview}
                  </Text>
                ) : null}
              </View>
              {item.unread_count > 0 && (
                <View style={styles.unreadBadge}>
                  <Text style={styles.unreadText}>
                    {item.unread_count > 9 ? '9+' : item.unread_count}
                  </Text>
                </View>
              )}
            </TouchableOpacity>
          );
        }}
        ListEmptyComponent={
          <View style={[styles.center, { paddingTop: 80 }]}>
            <Ionicons name="chatbubbles-outline" size={48} color={colors.textMuted} />
            <Text style={styles.emptyText}>{t('community.noMessages')}</Text>
            <Text style={styles.emptyHint}>{t('community.noMessagesHint')}</Text>
          </View>
        }
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={() => { setIsRefreshing(true); loadConversations(); }}
            tintColor={colors.primary}
          />
        }
        contentContainerStyle={conversations.length === 0 ? { flex: 1 } : { paddingBottom: spacing.lg }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { justifyContent: 'center', alignItems: 'center' },
  conversationCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    marginHorizontal: spacing.md,
    marginTop: spacing.sm,
    borderRadius: borderRadius.md,
    padding: spacing.md,
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.tertiary + '30',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: spacing.md,
  },
  convInfo: { flex: 1 },
  convHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  convName: { color: colors.text, fontSize: 15 },
  convNameBold: { fontWeight: '700' },
  convTime: { color: colors.textMuted, fontSize: 12 },
  convPreview: { color: colors.textMuted, fontSize: 13, marginTop: 2 },
  convPreviewUnread: { color: colors.text },
  unreadBadge: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    minWidth: 20,
    height: 20,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 6,
    marginLeft: spacing.sm,
  },
  unreadText: { color: colors.background, fontSize: 11, fontWeight: '700' },
  emptyText: { color: colors.textMuted, fontSize: 16, marginTop: spacing.md },
  emptyHint: { color: colors.textMuted, fontSize: 13, marginTop: spacing.xs },
});
