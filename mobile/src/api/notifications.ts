import { apiFetch } from './client';

export interface Notification {
  id: number;
  title: string;
  message: string;
  notification_type: string;
  notification_type_display: string;
  link_url: string;
  link_text: string;
  created_at: string;
  is_read: boolean;
}

export async function getNotifications(): Promise<Notification[]> {
  const response = await apiFetch<{ notifications: Notification[] }>('/loyalty/notifications/');
  return response.notifications;
}

export async function dismissNotification(notificationId: number): Promise<void> {
  await apiFetch(`/loyalty/notifications/${notificationId}/dismiss/`, {
    method: 'POST',
  });
}
