import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { getTokens, clearTokens } from '../api/client';
import { getMe, login as apiLogin, logout as apiLogout, register as apiRegister } from '../api/auth';

interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  shopify_customer_id: string | null;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, firstName?: string, lastName?: string) => Promise<void>;
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

  async function checkAuth() {
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

  async function register(email: string, password: string, firstName?: string, lastName?: string) {
    await apiRegister({
      email,
      password,
      password_confirm: password,
      first_name: firstName,
      last_name: lastName,
    });
    await login(email, password);
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
