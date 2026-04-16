import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000/api';

interface TokenPair {
  access: string;
  refresh: string;
}

let isRefreshing = false;
let refreshPromise: Promise<TokenPair | null> | null = null;

// Web fallback using localStorage
const webStorage = {
  getItem: (key: string): string | null => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(key);
    }
    return null;
  },
  setItem: (key: string, value: string): void => {
    if (typeof window !== 'undefined') {
      localStorage.setItem(key, value);
    }
  },
  deleteItem: (key: string): void => {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(key);
    }
  },
};

export async function getTokens(): Promise<TokenPair | null> {
  let access: string | null;
  let refresh: string | null;

  if (Platform.OS === 'web') {
    access = webStorage.getItem('access_token');
    refresh = webStorage.getItem('refresh_token');
  } else {
    access = await SecureStore.getItemAsync('access_token');
    refresh = await SecureStore.getItemAsync('refresh_token');
  }

  if (!access || !refresh) return null;
  return { access, refresh };
}

export async function setTokens(tokens: TokenPair): Promise<void> {
  if (Platform.OS === 'web') {
    webStorage.setItem('access_token', tokens.access);
    webStorage.setItem('refresh_token', tokens.refresh);
  } else {
    await SecureStore.setItemAsync('access_token', tokens.access);
    await SecureStore.setItemAsync('refresh_token', tokens.refresh);
  }
}

export async function clearTokens(): Promise<void> {
  if (Platform.OS === 'web') {
    webStorage.deleteItem('access_token');
    webStorage.deleteItem('refresh_token');
  } else {
    await SecureStore.deleteItemAsync('access_token');
    await SecureStore.deleteItemAsync('refresh_token');
  }
}

async function refreshAccessToken(): Promise<TokenPair | null> {
  // Prevent multiple simultaneous refresh requests
  if (isRefreshing && refreshPromise) {
    return refreshPromise;
  }

  isRefreshing = true;
  refreshPromise = (async () => {
    try {
      const tokens = await getTokens();
      if (!tokens?.refresh) {
        return null;
      }

      console.log('[API] Refreshing access token...');

      const response = await fetch(API_BASE_URL + '/auth/refresh/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh: tokens.refresh }),
      });

      if (!response.ok) {
        console.log('[API] Token refresh failed, status:', response.status);
        await clearTokens();
        return null;
      }

      const data = await response.json();
      const newTokens: TokenPair = {
        access: data.access,
        refresh: data.refresh || tokens.refresh,
      };

      await setTokens(newTokens);
      console.log('[API] Token refreshed successfully');
      return newTokens;
    } catch (error) {
      console.log('[API] Token refresh error:', error);
      await clearTokens();
      return null;
    } finally {
      isRefreshing = false;
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

export async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {},
  _isRetry = false
): Promise<T> {
  let tokens = await getTokens();

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  if (tokens?.access) {
    (headers as Record<string, string>)['Authorization'] = 'Bearer ' + tokens.access;
  }

  console.log('[API] Request:', options.method || 'GET', endpoint);

  const response = await fetch(API_BASE_URL + endpoint, {
    ...options,
    headers,
  });

  console.log('[API] Response:', response.status);

  // Handle 401 Unauthorized - try to refresh token
  if (response.status === 401 && !_isRetry && tokens?.refresh) {
    console.log('[API] Got 401, attempting token refresh...');
    const newTokens = await refreshAccessToken();

    if (newTokens) {
      // Retry the original request with new token
      return apiFetch<T>(endpoint, options, true);
    } else {
      // Refresh failed - user needs to log in again
      throw new Error('Session expired. Please log in again.');
    }
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    console.log('[API] Error body:', JSON.stringify(error));

    // Parse DRF validation errors
    if (typeof error === 'object' && error !== null) {
      const messages: string[] = [];
      for (const key of Object.keys(error)) {
        if (key === 'detail') continue;
        const val = (error as Record<string, unknown>)[key];
        if (Array.isArray(val)) {
          messages.push(key + ': ' + val.join(', '));
        } else if (typeof val === 'string') {
          messages.push(key + ': ' + val);
        }
      }
      if (messages.length > 0) {
        throw new Error(messages.join('\n'));
      }
      if (error.detail) {
        throw new Error(String(error.detail));
      }
    }
    throw new Error('Request failed with status ' + response.status);
  }

  return response.json();
}
