const CACHE_NAME = 'hob-cache-v2';
const STATIC_ASSETS = [
  '/',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/apple-touch-icon.png',
  '/icons/badge-96.png'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  // Activate immediately
  self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    })
  );
  // Take control immediately
  self.clients.claim();
});

// Fetch event - network first, fallback to cache
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }

  // Skip API requests - always go to network
  if (url.pathname.startsWith('/api') || url.origin !== self.location.origin) {
    return;
  }

  // For navigation requests (HTML pages), always serve index.html for SPA routing
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch('/index.html')
        .then((response) => {
          return response;
        })
        .catch(() => {
          return caches.match('/index.html') || caches.match('/');
        })
    );
    return;
  }

  // For other requests (JS, CSS, images), use network-first strategy
  event.respondWith(
    fetch(request)
      .then((response) => {
        // Clone the response before caching
        const responseClone = response.clone();

        // Cache successful responses
        if (response.status === 200) {
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, responseClone);
          });
        }

        return response;
      })
      .catch(() => {
        // Network failed, try cache
        return caches.match(request).then((cachedResponse) => {
          if (cachedResponse) {
            return cachedResponse;
          }

          // Return empty response for missing assets
          return new Response('', {
            status: 404,
            statusText: 'Not Found'
          });
        });
      })
  );
});

// Handle push notifications.
// The payload contract lives in backend/notifications/services.py
// (_deliver_push): { title, body, url, tag }. Keep the two in sync.
self.addEventListener('push', (event) => {
  if (!event.data) return;

  let data = {};
  try {
    data = event.data.json();
  } catch (e) {
    // Not JSON (e.g. a test push from DevTools) - show it as plain text.
    data = { body: event.data.text() };
  }

  const options = {
    body: data.body || '',
    // Colored app icon shown inside the notification.
    icon: '/icons/icon-192.png',
    // Status bar / badge icon. Android requires a white-on-transparent
    // (alpha-only) PNG here - anything colored renders as a white square.
    badge: '/icons/badge-96.png',
    vibrate: [100, 50, 100],
    data: {
      url: data.url || '/'
    }
  };

  // Same tag = the new notification replaces the old one (dedupes retried
  // sends). Only set when the backend provides one so distinct untagged
  // messages still stack.
  if (data.tag) {
    options.tag = data.tag;
  }

  event.waitUntil(
    self.registration.showNotification(data.title || 'House of Beers', options)
  );
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const url = event.notification.data?.url || '/';

  event.waitUntil(
    clients.matchAll({ type: 'window' }).then((windowClients) => {
      // Check if there's already a window open
      for (const client of windowClients) {
        if (client.url === url && 'focus' in client) {
          return client.focus();
        }
      }
      // Open a new window
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});
