import { apiFetch, setTokens, clearTokens } from './client';

interface RegisterData {
  email: string;
  password: string;
  password_confirm: string;
  first_name?: string;
  last_name?: string;
  /** Flyer code (?ref=CODE or typed by hand). Never blocks registration. */
  signup_code?: string;
}

export interface SignupCodeInfo {
  valid: boolean;
  label: string;
  points: number;
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
  birthdate?: string | null;
  birthdate_locked?: boolean;
  is_staff?: boolean;
}

export async function register(data: RegisterData): Promise<void> {
  await apiFetch('/auth/register/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * What a flyer code is worth. Unauthenticated - it runs before the account
 * exists. The backend answers 200 with valid:false for anything it will not
 * honour, so there is no error case to special-case here.
 */
export async function lookupSignupCode(code: string): Promise<SignupCodeInfo> {
  return apiFetch<SignupCodeInfo>(
    `/auth/signup-code/${encodeURIComponent(code)}/`
  );
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

/**
 * Sets the date of birth (YYYY-MM-DD). The backend validates it (real date,
 * 18+) and locks it once the first birthday gift has been issued, so callers
 * should show the returned error message rather than a generic one.
 */
export async function updateBirthdate(birthdate: string): Promise<User> {
  return apiFetch<User>('/users/me/birthdate/', {
    method: 'PATCH',
    body: JSON.stringify({ birthdate }),
  });
}
