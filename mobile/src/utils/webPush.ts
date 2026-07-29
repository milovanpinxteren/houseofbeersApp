import { Platform } from 'react-native';
import {
  getVapidPublicKey,
  subscribePush,
  unsubscribePush,
  PushSubscriptionPayload,
} from '../api/push';

/**
 * Browser Web Push plumbing.
 *
 * Every customer runs the PWA, so this is the standard browser Push API — not
 * expo-notifications, which has no web push support. Every function here is a
 * safe no-op on native and on browsers without support, and nothing ever
 * throws into render: callers get a result object or `void`.
 *
 * The service worker (public/service-worker.js) already handles the `push` and
 * `notificationclick` events; all that is left is permission -> subscribe ->
 * POST the subscription.
 */

export type PushPermissionState = 'granted' | 'denied' | 'default' | 'unsupported';

/** Why push cannot be offered here, if it cannot. */
export type PushBlocker = 'none' | 'ios-not-installed' | 'unsupported';

export type SubscribeFailure =
  | 'unsupported'
  | 'ios-not-installed'
  | 'denied'
  | 'dismissed'
  | 'no-key'
  | 'no-service-worker'
  | 'backend'
  | 'error';

export type SubscribeResult = { ok: true } | { ok: false; reason: SubscribeFailure };

const SW_READY_TIMEOUT_MS = 10000;

function isWebRuntime(): boolean {
  return Platform.OS === 'web' && typeof window !== 'undefined' && typeof navigator !== 'undefined';
}

/**
 * True only when this browser can actually do web push.
 *
 * Note iOS Safari does not expose PushManager in a normal tab — only once the
 * PWA is installed to the Home Screen — so this returns false there, and
 * `getPushBlocker()` explains why.
 */
export function isPushSupported(): boolean {
  if (!isWebRuntime()) return false;
  try {
    return (
      'serviceWorker' in navigator &&
      'PushManager' in window &&
      'Notification' in window
    );
  } catch {
    return false;
  }
}

export function isIOSBrowser(): boolean {
  if (!isWebRuntime()) return false;
  try {
    const ua = navigator.userAgent || '';
    return (
      /iPad|iPhone|iPod/.test(ua) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
    );
  } catch {
    return false;
  }
}

/** True when the PWA is running installed (Home Screen / standalone window). */
export function isStandalone(): boolean {
  if (!isWebRuntime()) return false;
  try {
    if ((window.navigator as any).standalone === true) return true;
    if (typeof window.matchMedia === 'function') {
      return window.matchMedia('(display-mode: standalone)').matches;
    }
    return false;
  } catch {
    return false;
  }
}

/**
 * Distinguishes "this browser will never do push" from "iOS can, but only once
 * the app is on the Home Screen" — the two need very different UI.
 */
export function getPushBlocker(): PushBlocker {
  if (isPushSupported()) return 'none';
  if (isIOSBrowser() && !isStandalone()) return 'ios-not-installed';
  return 'unsupported';
}

export function getPermissionState(): PushPermissionState {
  if (!isPushSupported()) return 'unsupported';
  try {
    const permission = window.Notification.permission;
    if (permission === 'granted' || permission === 'denied' || permission === 'default') {
      return permission;
    }
    return 'unsupported';
  } catch {
    return 'unsupported';
  }
}

/**
 * The VAPID application server key arrives as a base64url string and MUST be a
 * Uint8Array, or pushManager.subscribe() throws.
 */
export function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const output = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i += 1) {
    output[i] = rawData.charCodeAt(i);
  }
  return output;
}

function arrayBufferToBase64Url(buffer: ArrayBuffer | null): string {
  if (!buffer) return '';
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window.btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** A human readable label so users can recognise a device in support tickets. */
function getDeviceLabel(): string {
  try {
    const ua = navigator.userAgent || '';
    let device = 'Desktop';
    if (/iPhone/.test(ua)) device = 'iPhone';
    else if (/iPad/.test(ua)) device = 'iPad';
    else if (/Android/.test(ua)) device = 'Android';
    else if (/Macintosh/.test(ua)) device = 'Mac';
    else if (/Windows/.test(ua)) device = 'Windows';

    let browser = 'Browser';
    if (/Edg\//.test(ua)) browser = 'Edge';
    else if (/OPR\//.test(ua)) browser = 'Opera';
    else if (/Chrome\//.test(ua)) browser = 'Chrome';
    else if (/Firefox\//.test(ua)) browser = 'Firefox';
    else if (/Safari\//.test(ua)) browser = 'Safari';

    return `${device} ${browser}`.trim();
  } catch {
    return 'Web';
  }
}

/**
 * The service worker is registered from public/index.html, so it normally
 * exists already. `navigator.serviceWorker.ready` never rejects and can hang
 * forever if registration failed, hence the timeout.
 */
async function getRegistration(): Promise<ServiceWorkerRegistration | null> {
  try {
    const existing = await navigator.serviceWorker.getRegistration();
    if (existing) return existing;

    return await Promise.race([
      navigator.serviceWorker.ready,
      new Promise<null>((resolve) => setTimeout(() => resolve(null), SW_READY_TIMEOUT_MS)),
    ]);
  } catch (error) {
    console.log('[Push] Service worker lookup failed:', error);
    return null;
  }
}

/**
 * Public VAPID key. Prefers the backend so a rotated key propagates without a
 * redeploy, and falls back to the build-time env var when the endpoint is not
 * there yet.
 */
async function fetchVapidKey(): Promise<string | null> {
  try {
    const key = await getVapidPublicKey();
    if (key) return key;
  } catch (error) {
    console.log('[Push] VAPID key endpoint unavailable:', error);
  }
  const envKey = process.env.EXPO_PUBLIC_VAPID_PUBLIC_KEY;
  return envKey ? envKey : null;
}

function toPayload(subscription: PushSubscription): PushSubscriptionPayload | null {
  try {
    const json = subscription.toJSON();
    const keys = json.keys;
    const p256dh = keys?.p256dh ?? arrayBufferToBase64Url(subscription.getKey('p256dh'));
    const auth = keys?.auth ?? arrayBufferToBase64Url(subscription.getKey('auth'));
    if (!subscription.endpoint || !p256dh || !auth) return null;
    return {
      endpoint: subscription.endpoint,
      keys: { p256dh, auth },
      device_label: getDeviceLabel(),
    };
  } catch (error) {
    console.log('[Push] Could not serialize subscription:', error);
    return null;
  }
}

/** Upserts the subscription on the backend. Returns false on any failure. */
async function postSubscription(subscription: PushSubscription): Promise<boolean> {
  const payload = toPayload(subscription);
  if (!payload) return false;
  try {
    await subscribePush(payload);
    return true;
  } catch (error) {
    console.log('[Push] Subscription upload failed:', error);
    return false;
  }
}

async function createSubscription(
  registration: ServiceWorkerRegistration,
  key: string
): Promise<PushSubscription | null> {
  const applicationServerKey = urlBase64ToUint8Array(key);
  try {
    return await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey,
    });
  } catch (error) {
    // A subscription created with a different (rotated) VAPID key makes
    // subscribe() throw. Drop the stale one and try once more.
    console.log('[Push] Subscribe failed, retrying after cleanup:', error);
    try {
      const stale = await registration.pushManager.getSubscription();
      if (stale) {
        await stale.unsubscribe();
        return await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey,
        });
      }
    } catch (retryError) {
      console.log('[Push] Subscribe retry failed:', retryError);
    }
    return null;
  }
}

/**
 * Full opt-in flow. MUST be called from a user gesture (a tap) — iOS refuses
 * the permission prompt otherwise, and a refusal is permanent.
 */
export async function subscribeToPush(): Promise<SubscribeResult> {
  try {
    if (!isPushSupported()) {
      const blocker = getPushBlocker();
      return { ok: false, reason: blocker === 'ios-not-installed' ? 'ios-not-installed' : 'unsupported' };
    }

    let permission = getPermissionState();
    if (permission === 'denied') {
      return { ok: false, reason: 'denied' };
    }

    if (permission !== 'granted') {
      permission = (await window.Notification.requestPermission()) as PushPermissionState;
      if (permission === 'denied') return { ok: false, reason: 'denied' };
      if (permission !== 'granted') return { ok: false, reason: 'dismissed' };
    }

    const registration = await getRegistration();
    if (!registration) return { ok: false, reason: 'no-service-worker' };

    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      const key = await fetchVapidKey();
      if (!key) return { ok: false, reason: 'no-key' };
      subscription = await createSubscription(registration, key);
    }
    if (!subscription) return { ok: false, reason: 'error' };

    const uploaded = await postSubscription(subscription);
    return uploaded ? { ok: true } : { ok: false, reason: 'backend' };
  } catch (error) {
    console.log('[Push] subscribeToPush error:', error);
    return { ok: false, reason: 'error' };
  }
}

/**
 * Called once per launch for a logged-in user. Re-uploads the current
 * subscription so the backend record is repaired after the browser rotated it,
 * and re-creates one that was dropped when the PWA was removed and re-added.
 * Never prompts: it only runs when permission is already granted.
 */
export async function syncExistingSubscription(): Promise<void> {
  try {
    if (!isPushSupported()) return;
    if (getPermissionState() !== 'granted') return;

    const registration = await getRegistration();
    if (!registration) return;

    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      const key = await fetchVapidKey();
      if (!key) return;
      subscription = await createSubscription(registration, key);
    }
    if (!subscription) return;

    await postSubscription(subscription);
  } catch (error) {
    console.log('[Push] syncExistingSubscription error:', error);
  }
}

/** Opts out: tells the backend first, then drops the browser subscription. */
export async function unsubscribeFromPush(): Promise<boolean> {
  try {
    if (!isPushSupported()) return false;

    const registration = await getRegistration();
    if (!registration) return false;

    const subscription = await registration.pushManager.getSubscription();
    if (!subscription) return true;

    try {
      await unsubscribePush(subscription.endpoint);
    } catch (error) {
      console.log('[Push] Backend unsubscribe failed:', error);
    }

    await subscription.unsubscribe();
    return true;
  } catch (error) {
    console.log('[Push] unsubscribeFromPush error:', error);
    return false;
  }
}
