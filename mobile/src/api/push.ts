import { apiFetch } from './client';

/**
 * Web Push subscription + notification preference API.
 *
 * Separate from `notifications.ts`, which handles the in-app (admin managed)
 * notification feed. This file only deals with browser push subscriptions and
 * the per-category delivery preferences.
 */

export interface VapidKeyResponse {
  public_key: string;
}

export interface PushSubscriptionKeys {
  p256dh: string;
  auth: string;
}

export interface PushSubscriptionPayload {
  endpoint: string;
  keys: PushSubscriptionKeys;
  device_label?: string;
}

export interface NotificationPreferences {
  push_enabled: boolean;
  email_enabled: boolean;
  birthday: boolean;
  announcements: boolean;
  recommendations: boolean;
  raffle: boolean;
}

/** Per-category opt-outs the settings UI exposes. */
export type NotificationCategory = 'birthday' | 'announcements' | 'recommendations' | 'raffle';

export async function getVapidPublicKey(): Promise<string> {
  const response = await apiFetch<VapidKeyResponse>('/notifications/vapid-public-key/');
  return response.public_key;
}

export async function subscribePush(payload: PushSubscriptionPayload): Promise<void> {
  await apiFetch('/notifications/subscribe/', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function unsubscribePush(endpoint: string): Promise<void> {
  await apiFetch('/notifications/unsubscribe/', {
    method: 'POST',
    body: JSON.stringify({ endpoint }),
  });
}

export async function getNotificationPreferences(): Promise<NotificationPreferences> {
  return apiFetch<NotificationPreferences>('/notifications/preferences/');
}

export async function updateNotificationPreferences(
  data: Partial<NotificationPreferences>
): Promise<NotificationPreferences> {
  return apiFetch<NotificationPreferences>('/notifications/preferences/', {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}
