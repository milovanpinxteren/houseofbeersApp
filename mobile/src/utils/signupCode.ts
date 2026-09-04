import { useEffect } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Linking from 'expo-linking';

/**
 * Signup codes: a printed flyer's QR points at
 * https://app.houseofbeers.nl/?ref=CODE. We grab that code the moment the app
 * boots — before any auth, because the visitor has no account yet and will
 * wander around the login/register screens first — and persist it so it is
 * still there when they finally hit "Registreren".
 *
 * iOS caveat this design has to live with: adding the PWA to the home screen
 * creates a SEPARATE storage partition, so a code captured in Safari is
 * invisible to the installed app. That is why the register screen shows the
 * Actiecode field instead of hiding it — the code is printed next to the QR
 * so it can be typed back in.
 */
const SIGNUP_CODE_KEY = 'signup_code';

/** The one place a raw code becomes a lookup key. Mirrors SignupCode.normalize. */
export function normalizeSignupCode(raw: string | null | undefined): string {
  return (raw || '').trim().toUpperCase();
}

export async function getStoredSignupCode(): Promise<string> {
  try {
    return normalizeSignupCode(await AsyncStorage.getItem(SIGNUP_CODE_KEY));
  } catch {
    return '';
  }
}

export async function storeSignupCode(code: string): Promise<void> {
  const normalized = normalizeSignupCode(code);
  if (!normalized) return;
  try {
    await AsyncStorage.setItem(SIGNUP_CODE_KEY, normalized);
  } catch {
    // A full/blocked storage must never break the app; the member can still
    // type the code off the flyer.
  }
}

export async function clearStoredSignupCode(): Promise<void> {
  try {
    await AsyncStorage.removeItem(SIGNUP_CODE_KEY);
  } catch {
    // Ignore - worst case a used code is offered again and simply wins nothing.
  }
}

/** Pull `ref` out of a launch URL. Returns '' when there is none. */
export function parseSignupCodeFromUrl(url: string | null): string {
  if (!url) return '';
  try {
    const { queryParams } = Linking.parse(url);
    const ref = queryParams?.ref;
    return normalizeSignupCode(Array.isArray(ref) ? ref[0] : (ref as string));
  } catch {
    return '';
  }
}

async function captureFromLaunchUrl(): Promise<void> {
  const url = await Linking.getInitialURL();
  const code = parseSignupCodeFromUrl(url);
  if (!code) return;

  await storeSignupCode(code);

  // On web the query string is dropped from the address bar afterwards: the
  // URL is meant to be scanned, not shared or bookmarked, and leaving it
  // there means a reload keeps re-applying a code the member may have
  // deliberately cleared.
  if (typeof window !== 'undefined' && window.history?.replaceState) {
    const params = new URLSearchParams(window.location.search);
    params.delete('ref');
    const query = params.toString();
    window.history.replaceState(
      {},
      '',
      window.location.pathname + (query ? `?${query}` : '') + window.location.hash
    );
  }
}

let capturePromise: Promise<void> | null = null;

/**
 * Capture `?ref=CODE` exactly once per app launch, and hand every caller the
 * same promise. Anything that reads the stored code during startup must await
 * this first, otherwise it races the capture and sees an empty store.
 */
export function ensureSignupCodeCaptured(): Promise<void> {
  if (!capturePromise) {
    capturePromise = captureFromLaunchUrl().catch(() => {
      // A malformed launch URL must never block startup.
    });
  }
  return capturePromise;
}

export function useSignupCodeCapture(): void {
  useEffect(() => {
    void ensureSignupCodeCaptured();
  }, []);
}
