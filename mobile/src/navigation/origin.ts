import { router, usePathname } from 'expo-router';

type HrefObject = { pathname: string; params?: Record<string, unknown> };

/**
 * Push into a hidden stack while recording where the user came from.
 *
 * The stacks' header back arrows read the `from` param to return to the
 * actual origin tab instead of a hard-coded fallback, so screens reachable
 * from multiple places (home, ontdek, profile, notifications) always go
 * back to the right one.
 */
export function useOriginPush() {
  const pathname = usePathname();

  return (href: string | HrefObject) => {
    if (typeof href === 'string') {
      const sep = href.includes('?') ? '&' : '?';
      router.push(`${href}${sep}from=${encodeURIComponent(pathname)}` as any);
    } else {
      router.push({
        ...href,
        params: { ...(href.params || {}), from: pathname },
      } as any);
    }
  };
}

/** Only allow internal app paths as back targets. */
export function safeOrigin(from: unknown): string | null {
  if (typeof from === 'string' && from.startsWith('/') && !from.startsWith('//')) {
    return from;
  }
  return null;
}
