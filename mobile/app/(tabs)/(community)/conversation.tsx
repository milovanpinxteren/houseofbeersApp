import React, { useCallback } from 'react';
import { useLocalSearchParams } from 'expo-router';
import ChatScreen from '../../../src/components/ChatScreen';
import {
  getMessages, sendMessage, deleteMessage, markConversationRead,
} from '../../../src/api/community';

export default function ConversationScreen() {
  const { conversationId, name } = useLocalSearchParams<{ conversationId: string; name: string }>();
  const convId = parseInt(conversationId || '0', 10);

  const fetchMessages = useCallback((page: number) => getMessages(convId, page), [convId]);
  const handleSend = useCallback((content: string) => sendMessage(convId, { content }), [convId]);
  const handleDelete = useCallback((messageId: number) => deleteMessage(convId, messageId), [convId]);
  const markRead = useCallback(() => markConversationRead(convId), [convId]);

  return (
    <ChatScreen
      title={name || ''}
      fetchMessages={fetchMessages}
      onSend={handleSend}
      onDeleteMessage={handleDelete}
      markRead={markRead}
    />
  );
}
