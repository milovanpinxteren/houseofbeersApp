import { useCallback, useEffect, useState } from 'react';
import { Platform } from 'react-native';
import {
  getPermissionState,
  getPushBlocker,
  isPushSupported,
  subscribeToPush,
  unsubscribeFromPush,
  PushBlocker,
  PushPermissionState,
  SubscribeFailure,
} from '../utils/webPush';
import { updateNotificationPreferences } from '../api/push';
import { t } from '../i18n';

export interface PushFeedback {
  type: 'success' | 'error' | 'info';
  message: string;
}

/**
 * Shared push permission state.
 *
 * Permission lives in the browser, not in React, so every mounted consumer is
 * refreshed together after a change — that way the settings section reacts when
 * the birthday card is what actually turned notifications on.
 */
const listeners = new Set<() => void>();

function broadcast() {
  listeners.forEach((listener) => listener());
}

function messageForFailure(reason: SubscribeFailure): PushFeedback {
  switch (reason) {
    case 'denied':
      return { type: 'error', message: t('notifications.deniedText') };
    case 'dismissed':
      return { type: 'info', message: t('notifications.subscribeDismissed') };
    case 'ios-not-installed':
      return { type: 'info', message: t('notifications.iosInstallText') };
    case 'unsupported':
      return {
        type: 'info',
        message:
          Platform.OS === 'web'
            ? t('notifications.unsupportedText')
            : t('notifications.nativeUnsupportedText'),
      };
    case 'no-key':
    case 'backend':
    case 'no-service-worker':
      return { type: 'error', message: t('notifications.backendError') };
    default:
      return { type: 'error', message: t('notifications.subscribeError') };
  }
}

export function usePushSubscription() {
  const [permission, setPermission] = useState<PushPermissionState>(() => getPermissionState());
  const [blocker, setBlocker] = useState<PushBlocker>(() => getPushBlocker());
  const [isBusy, setIsBusy] = useState(false);
  const [feedback, setFeedback] = useState<PushFeedback | null>(null);

  const refresh = useCallback(() => {
    setPermission(getPermissionState());
    setBlocker(getPushBlocker());
  }, []);

  useEffect(() => {
    listeners.add(refresh);
    refresh();
    return () => {
      listeners.delete(refresh);
    };
  }, [refresh]);

  /** Must be called straight from a tap handler — iOS needs the user gesture. */
  const enable = useCallback(async (): Promise<boolean> => {
    setIsBusy(true);
    setFeedback(null);
    try {
      const result = await subscribeToPush();
      if (result.ok) {
        // Best effort: a fresh opt-in should also flip the master switch.
        try {
          await updateNotificationPreferences({ push_enabled: true });
        } catch (error) {
          console.log('[Push] Could not set push_enabled:', error);
        }
        setFeedback({ type: 'success', message: t('notifications.enabledConfirmation') });
        broadcast();
        return true;
      }
      setFeedback(messageForFailure(result.reason));
      broadcast();
      return false;
    } finally {
      setIsBusy(false);
    }
  }, []);

  const disable = useCallback(async (): Promise<void> => {
    setIsBusy(true);
    setFeedback(null);
    try {
      const removed = await unsubscribeFromPush();
      try {
        await updateNotificationPreferences({ push_enabled: false });
      } catch (error) {
        console.log('[Push] Could not clear push_enabled:', error);
      }
      setFeedback(
        removed
          ? { type: 'info', message: t('notifications.turnedOff') }
          : { type: 'error', message: t('notifications.turnOffError') }
      );
      broadcast();
    } finally {
      setIsBusy(false);
    }
  }, []);

  const clearFeedback = useCallback(() => setFeedback(null), []);

  return {
    permission,
    blocker,
    isSupported: isPushSupported(),
    isBusy,
    feedback,
    enable,
    disable,
    refresh,
    clearFeedback,
  };
}
