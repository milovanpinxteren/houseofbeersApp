import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { initializeLocale, setLanguage as setI18nLanguage, getCurrentLanguage, languages } from '../i18n';

interface LanguageContextType {
  language: string;
  setLanguage: (code: string) => Promise<void>;
  isLoading: boolean;
  languages: typeof languages;
}

const LanguageContext = createContext<LanguageContextType | undefined>(undefined);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [language, setLanguageState] = useState(getCurrentLanguage());
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    initializeLocale().then((locale) => {
      setLanguageState(locale);
      setIsLoading(false);
    });
  }, []);

  const setLanguage = useCallback(async (code: string) => {
    await setI18nLanguage(code);
    setLanguageState(code);
  }, []);

  return (
    <LanguageContext.Provider value={{ language, setLanguage, isLoading, languages }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useLanguage must be used within a LanguageProvider');
  }
  return context;
}
