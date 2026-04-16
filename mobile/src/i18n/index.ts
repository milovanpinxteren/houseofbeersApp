import { I18n } from 'i18n-js';
import * as Localization from 'expo-localization';
import AsyncStorage from '@react-native-async-storage/async-storage';
import en from './en';
import nl from './nl';

const i18n = new I18n({
  en,
  nl,
});

// Set default locale based on device
i18n.defaultLocale = 'en';
i18n.enableFallback = true;

// Storage key for persisted language preference
const LANGUAGE_KEY = 'user_language';

// Available languages
export const languages = [
  { code: 'en', name: 'English', nativeName: 'English' },
  { code: 'nl', name: 'Dutch', nativeName: 'Nederlands' },
];

// Initialize locale from stored preference or device locale
export async function initializeLocale(): Promise<string> {
  try {
    const storedLanguage = await AsyncStorage.getItem(LANGUAGE_KEY);
    if (storedLanguage && (storedLanguage === 'en' || storedLanguage === 'nl')) {
      i18n.locale = storedLanguage;
      return storedLanguage;
    }
  } catch (error) {
    console.log('Error reading stored language:', error);
  }

  // Fall back to device locale
  const deviceLocale = Localization.getLocales()[0]?.languageCode || 'en';
  const locale = deviceLocale === 'nl' ? 'nl' : 'en';
  i18n.locale = locale;
  return locale;
}

// Set and persist language
export async function setLanguage(languageCode: string): Promise<void> {
  i18n.locale = languageCode;
  try {
    await AsyncStorage.setItem(LANGUAGE_KEY, languageCode);
  } catch (error) {
    console.log('Error storing language:', error);
  }
}

// Get current language code
export function getCurrentLanguage(): string {
  return i18n.locale;
}

// Translation function
export function t(key: string, options?: Record<string, any>): string {
  return i18n.t(key, options);
}

export default i18n;
