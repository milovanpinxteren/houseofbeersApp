import { t, getCurrentLanguage } from '../i18n';

/**
 * Relative time for recent moments, absolute date past a week — so old
 * content never reads "97d". Unit suffixes are localized (nl: 5m/3u/2d).
 */
export function timeAgo(dateStr: string): string {
  const date = new Date(dateStr);
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return t('time.now');
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t('time.minutes', { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('time.hours', { count: hours });
  const days = Math.floor(hours / 24);
  if (days < 7) return t('time.days', { count: days });

  const locale = getCurrentLanguage() === 'nl' ? 'nl-NL' : 'en-US';
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return date.toLocaleDateString(
    locale,
    sameYear
      ? { day: 'numeric', month: 'short' }
      : { day: 'numeric', month: 'short', year: 'numeric' }
  );
}
