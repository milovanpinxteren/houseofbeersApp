import { apiFetch, setTokens, clearTokens } from './client';

interface RegisterData {
  email: string;
  password: string;
  password_confirm: string;
  first_name?: string;
  last_name?: string;
}

interface LoginData {
  email: string;
  password: string;
}

interface LoginResponse {
  access: string;
  refresh: string;
}

interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  shopify_customer_id: string | null;
  shopify_linked_at: string | null;
  date_joined: string;
}

export async function register(data: RegisterData): Promise<void> {
  await apiFetch('/auth/register/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function login(data: LoginData): Promise<void> {
  const response = await apiFetch<LoginResponse>('/auth/login/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
  await setTokens(response);
}

export async function logout(): Promise<void> {
  await clearTokens();
}

export async function getMe(): Promise<User> {
  return apiFetch<User>('/users/me/');
}

export async function requestPasswordReset(email: string): Promise<void> {
  await apiFetch('/auth/password-reset/', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

export async function confirmPasswordReset(
  uid: string,
  token: string,
  password: string
): Promise<void> {
  await apiFetch('/auth/password-reset/confirm/', {
    method: 'POST',
    body: JSON.stringify({ uid, token, password, password_confirm: password }),
  });
}

export async function syncShopify(): Promise<User> {
  return apiFetch<User>('/users/me/sync-shopify/', {
    method: 'POST',
  });
}

export async function updateProfile(data: { first_name?: string; last_name?: string }): Promise<User> {
  return apiFetch<User>('/users/me/', {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}
