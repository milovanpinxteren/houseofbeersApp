import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { getTokens, clearTokens } from '../api/client';
import { getMe, login as apiLogin, logout as apiLogout, register as apiRegister } from '../api/auth';
import { syncExistingSubscription } from '../utils/webPush';

interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  shopify_customer_id: string | null;
  birthdate?: string | null;
  birthdate_locked?: boolean;
}

/**
 * What the caller of `register` needs from the register response. The
 * register endpoint is the ONLY place that reports the welcome bonus, so it
 * is handed back rather than swallowed.
 */
export interface RegisterResult {
  /** Welcome bonus actually awarded; 0 when there was none. */
  signupBonusPoints: number;
  shopifyLinked: boolean;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    firstName?: string,
    lastName?: string,
    signupCode?: string
  ) => Promise<RegisterResult>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    checkAuth();
  }, []);

  // Repair the push subscription once per logged-in session. Browsers drop
  // subscriptions when the PWA is removed and re-added, and can rotate them on
  // their own, so we re-upload whatever the browser currently has. Deliberately
  // not awaited: it must never delay startup, and it no-ops without push support.
  useEffect(() => {
    if (!user) return;
    void syncExistingSubscription();
  }, [user?.id]);

  async function checkAuth() {
    // Demo mode (see api/orders.ts): a fixture user so the orders screen is
    // reachable without a backend. Inert in real builds — the flag is never
    // set in .env.production and EXPO_PUBLIC_* is inlined at build time.
    if (process.env.EXPO_PUBLIC_MOCK_ORDERS) {
      setUser({
        id: 0,
        email: 'demo@houseofbeers.nl',
        first_name: 'Demo',
        last_name: 'Proever',
        shopify_customer_id: '9001',
      });
      setIsLoading(false);
      return;
    }
    try {
      const tokens = await getTokens();
      if (tokens) {
        const userData = await getMe();
        setUser(userData);
      }
    } catch {
      await clearTokens();
    } finally {
      setIsLoading(false);
    }
  }

  async function login(email: string, password: string) {
    await apiLogin({ email, password });
    const userData = await getMe();
    setUser(userData);
  }

  async function register(
    email: string,
    password: string,
    firstName?: string,
    lastName?: string,
    signupCode?: string
  ): Promise<RegisterResult> {
    const response = await apiRegister({
      email,
      password,
      password_confirm: password,
      first_name: firstName,
      last_name: lastName,
      // Sent as typed; the backend normalizes and decides. An unusable code
      // is recorded for attribution and simply wins no bonus.
      signup_code: signupCode || undefined,
    });
    await login(email, password);
    // Older backends (and a response shape that ever changes) must not break
    // registration itself, so both fields are read defensively.
    return {
      signupBonusPoints: Number(response?.signup_bonus_points) || 0,
      shopifyLinked: !!response?.shopify_linked,
    };
  }

  async function logout() {
    await apiLogout();
    setUser(null);
  }

  async function refreshUser() {
    const userData = await getMe();
    setUser(userData);
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        register,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
