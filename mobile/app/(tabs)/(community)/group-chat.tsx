import React, { useCallback } from 'react';
import { Pressable, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, router } from 'expo-router';
import ChatScreen from '../../../src/components/ChatScreen';
import { colors } from '../../../src/theme/colors';
import {
  getGroupMessages, sendGroupMessage, deleteGroupMessage, markGroupRead,
} from '../../../src/api/community';

export default function GroupChatScreen() {
  const { groupId, groupName } = useLocalSearchParams<{ groupId: string; groupName: string }>();
  const gId = parseInt(groupId || '0', 10);

  const fetchMessages = useCallback((page: number) => getGroupMessages(gId, page), [gId]);
  const handleSend = useCallback((content: string) => sendGroupMessage(gId, { content }), [gId]);
  const handleDelete = useCallback((messageId: number) => deleteGroupMessage(gId, messageId), [gId]);
  const markRead = useCallback(() => markGroupRead(gId), [gId]);

  return (
    <ChatScreen
      title={groupName || ''}
      showSenderNames
      headerAction={
        <Pressable
          onPress={() => router.push(`/(tabs)/(community)/group-info?groupId=${gId}`)}
          style={({ pressed }) => [styles.infoBtn, pressed && { opacity: 0.7 }]}
          hitSlop={8}
        >
          <Ionicons name="information-circle-outline" size={24} color={colors.primary} />
        </Pressable>
      }
      fetchMessages={fetchMessages}
      onSend={handleSend}
      onDeleteMessage={handleDelete}
      markRead={markRead}
    />
  );
}

const styles = StyleSheet.create({
  infoBtn: {
    minWidth: 44,
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
