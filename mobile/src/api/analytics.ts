import { apiFetch, getTokens } from './client';

/**
 * Fire-and-forget usage event. Never throws and never blocks the UI;
 * skipped entirely when the user is not logged in.
 */
export function trackEvent(
  eventType: 'screen_view' | 'app_shop_checkout',
  metadata?: Record<string, unknown>
): void {
  getTokens()
    .then((tokens) => {
      if (!tokens) return;
      return apiFetch('/analytics/event/', {
        method: 'POST',
        body: JSON.stringify({ event_type: eventType, metadata: metadata ?? {} }),
      });
    })
    .catch(() => {});
}
