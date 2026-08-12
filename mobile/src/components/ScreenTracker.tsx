import { useEffect } from 'react';
import { usePathname } from 'expo-router';
import { trackEvent } from '../api/analytics';

/**
 * Reports every navigation as a screen_view event (route path as screen
 * name). Renders nothing; mounted once in the root layout.
 */
export function ScreenTracker() {
  const pathname = usePathname();

  useEffect(() => {
    if (pathname) {
      trackEvent('screen_view', { screen: pathname });
    }
  }, [pathname]);

  return null;
}
