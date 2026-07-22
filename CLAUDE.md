# House of Beers App

## Project Overview
A loyalty and community app for houseofbeers.nl. This is a new project built from scratch. The app targets existing loyal customers — SEO is not a concern.

## Stack
- **Backend**: Django + Django REST Framework, hosted on Dokku at `appadmin.houseofbeers.nl`
- **Frontend**: Expo (React Native) with Expo Router
  - **Android**: Native app on Google Play Store
  - **iOS**: Progressive Web App (PWA) at `app.houseofbeers.nl`
- **Database**: PostgreSQL (production), SQLite (development)
- **Task Queue**: Celery + Redis (background sync, scheduled tasks)
- **Hosting**: Dokku (backend), Netlify (PWA)

## Repository Structure
```
/backend
  /config              → Django settings, urls, wsgi, celery
  /users               → User model, auth, Shopify service
  /loyalty             → Points, rewards, notifications, sync tasks
  /recommendations     → Beer recommendations, taste profiles, favorites
  /templates           → Password reset web page

/mobile
  /app
    /(auth)            → Login, register, forgot-password screens
    /(tabs)            → Main app tabs
      index.tsx        → Home screen with notifications & beer journey menu
      favorites.tsx    → Favorites tab
      loyalty.tsx      → Loyalty points tab
      profile.tsx      → Profile hub with navigation
      /(profile)       → Profile sub-screens (Stack navigator inside tabs)
        recommendations.tsx  → Personalized beer recommendations
        taste-profile.tsx    → Taste wheel and style distribution
        favorites.tsx        → Manage favorite beers
        orders.tsx           → Shopify order history
        connect-untappd.tsx  → Link/unlink Untappd account
    reset-password.tsx → Password reset screen (unused, web version in backend)
    _layout.tsx        → Root layout with providers
  /src
    /api               → API client and endpoint functions
      recommendations.ts → Recommendations API (Untappd, favorites, taste profile)
    /context           → AuthContext, LanguageContext
    /i18n              → Translations (en.ts, nl.ts)
    /theme             → Colors and spacing
  /assets              → Logo, icons, splash screen
  /public              → PWA assets (icons, manifest, service worker)
  /scripts             → Build scripts (PWA icon generation, asset copying)
  eas.json             → EAS Build configuration

/netlify.toml          → Netlify deployment configuration
```

---

## Git Repository Structure

This is a monorepo containing both backend and mobile code. Each can be deployed independently.

### GitHub
- **Repository**: https://github.com/milovanpinxteren/houseofbeersApp
- **Branch**: `main`

Both `backend/` and `mobile/` are regular directories in the same repo (not submodules).

---

## Deployment

### Backend (Dokku)
- **URL**: https://appadmin.houseofbeers.nl
- **Admin**: https://appadmin.houseofbeers.nl/admin/
- **API**: https://appadmin.houseofbeers.nl/api/
- **Server**: 89.145.161.168
- **App name**: `houseofbeers-api`
- **Database**: PostgreSQL via `dokku-postgres` plugin
- **Redis**: `houseofbeers-redis` via `dokku-redis` plugin (Celery broker)
- **Processes**: web (gunicorn), worker (celery), beat (celery beat)

#### Deploy Backend
Deploy only the `backend/` folder to Dokku using git subtree:
```bash
# First time: add dokku remote
git remote add dokku dokku@89.145.161.168:houseofbeers-api

# Deploy backend folder to Dokku
git subtree push --prefix backend dokku main
```

#### Useful Dokku Commands
```bash
ssh root@89.145.161.168

# View logs
dokku logs houseofbeers-api -t
dokku logs houseofbeers-api -p worker    # Celery worker logs
dokku logs houseofbeers-api -p beat      # Celery beat logs

# Run Django commands
dokku run houseofbeers-api python manage.py createsuperuser
dokku run houseofbeers-api python manage.py migrate

# Points sync commands
dokku run houseofbeers-api python manage.py sync_points                        # Partial sync all users
dokku run houseofbeers-api python manage.py sync_points --type intermediate    # Intermediate sync all users
dokku run houseofbeers-api python manage.py sync_points --type full            # Full check-and-correct all users
dokku run houseofbeers-api python manage.py sync_points --email user@example.com  # Sync specific user
dokku run houseofbeers-api python manage.py sync_points --async                # Dispatch as Celery tasks

# Set environment variables
dokku config:set houseofbeers-api KEY=value

# View config
dokku config:report houseofbeers-api

# Process management
dokku ps:report houseofbeers-api         # Check all process statuses
dokku ps:scale houseofbeers-api web=1 worker=1 beat=1  # Scale processes
dokku ps:restart houseofbeers-api
```

### PWA (Netlify) - For iOS Users
- **URL**: https://app.houseofbeers.nl
- **Hosting**: Netlify (auto-deploys from GitHub)
- **Config**: `netlify.toml` in repo root

The PWA is automatically deployed when you push to `main`. Netlify:
1. Reads `netlify.toml` from repo root
2. Changes to `mobile/` directory
3. Runs `npm run build:web`
4. Publishes `mobile/dist/`

#### PWA Features
- Installable on iOS home screen ("Add to Home Screen" in Safari)
- Offline support via service worker
- Push notifications (iOS 16.4+)
- Custom splash screens and icons

#### Manual PWA Build (Local Testing)
```bash
cd mobile
npm run build:web      # Build for production API
npm run serve:web      # Serve locally at http://localhost:3000
```

### Mobile App (EAS Build) - For Android
- **Build service**: Expo Application Services (EAS)
- **Package**: `nl.houseofbeers.app`
- **EAS Project**: https://expo.dev/accounts/milovp/projects/house-of-beers
- **Play Store**: Published on Google Play

#### Build Commands
```bash
cd mobile

# Preview build (APK for testing)
eas build --platform android --profile preview

# Production build (AAB for Play Store)
eas build --platform android --profile production

# Submit to Play Store
eas submit --platform android --profile production
```

---

## Brand Identity & Styling

### Color Palette
| Name | Hex | Usage |
|------|-----|-------|
| Beige/Tan | `#d5c8ad` | Primary accent, buttons, badges |
| Dark Brown | `#954e3b` | Secondary accent, logout button |
| Warm Brown | `#bea488` | Tertiary accent, borders |
| Black | `#000000` | Backgrounds |
| White | `#ffffff` | Text on dark backgrounds |

### Design Principles
- Dark, premium aesthetic with elegant beige accents
- High contrast for readability
- Rounded corners (borderRadius.md = 12px)
- Theme defined in `mobile/src/theme/colors.ts`

---

## Completed Features

### Phase 1: Authentication & Shopify Integration ✅
- [x] User registration and login (email + password, JWT auth)
- [x] Custom User model with Shopify customer ID field
- [x] Shopify customer lookup and linking (automatic on register, manual sync button)
- [x] Password reset via email (Hostinger SMTP)
- [x] Password reset web page at `/reset-password/`
- [x] Profile screen with Shopify link status
- [x] Account deletion endpoint (Google Play compliance)

### Phase 2: Order History ✅
- [x] Orders tab showing Shopify order history
- [x] Order details with line items (expandable cards)
- [x] Pull-to-refresh

### Phase 3: Loyalty Points Program ✅
- [x] Points earning rules (configurable via Django admin):
  - Points per Euro spent
  - Points per order
  - Points for specific products (SKU or title)
  - Bonus for minimum order value
  - First order bonus
  - `only_after_registration` flag: only count orders placed after user joined the app
- [x] Rewards system (redeemable with points):
  - Fixed discount
  - Percentage discount
  - Free shipping
  - Free product (via Shopify product ID)
- [x] Shopify discount code generation on redemption (GraphQL API)
- [x] Loyalty tab with points balance, rewards, history, and redemption codes
- [x] Three-tier points sync system (see Loyalty Sync section below)
- [x] Admin-awarded points preserved across syncs
- [x] Copy discount code to clipboard

### Phase 4: Notifications ✅
- [x] Admin-managed notifications (Django admin)
- [x] Notification types: announcement, promotion, event, news
- [x] Optional link button on notifications
- [x] Dismissable notifications (tracked per user)
- [x] Display on home screen with color-coded icons

### Phase 5: Localization ✅
- [x] Multi-language support (English, Dutch)
- [x] Language picker in Profile screen
- [x] Persisted language preference (AsyncStorage)
- [x] Auto-detect device language on first launch
- [x] All screens translated

### Phase 6: Production Deployment ✅
- [x] Backend deployed to Dokku with PostgreSQL
- [x] SSL via Let's Encrypt
- [x] EAS Build configuration for Android
- [x] Automatic token refresh in mobile app
- [x] Password reset web page

### Phase 7: Beer Recommendations & Personalization ✅
- [x] Untappd profile integration (link/unlink account)
- [x] Taste profile analysis from Untappd check-ins or order history
- [x] Personalized beer recommendations from store inventory
- [x] Discovery picks (try something new)
- [x] Tried beers (beers you've had before)
- [x] Favorites system with heart button on beer cards
- [x] Add favorites to Shopify cart (generates cart permalink)
- [x] Taste wheel visualization (radar chart with style preferences)
- [x] Style distribution chart
- [x] Top breweries list
- [x] ABV profile analysis

### Phase 8: UI/UX Improvements ✅
- [x] Reorganized navigation: Profile as hub with sub-screens
- [x] "Jouw Bierreis" (Your Beer Journey) menu on home and profile
- [x] Favorites tab in bottom navbar with badge count
- [x] Clickable logo returns to home from any screen
- [x] Bottom navbar stays visible on profile sub-screens (nested Stack in tabs)
- [x] Consistent header with logo across all screens

### Phase 9: PWA for iOS ✅
- [x] Progressive Web App build configuration
- [x] Service worker for offline support and caching
- [x] PWA manifest with app icons and splash screens
- [x] iOS-specific meta tags (apple-mobile-web-app-capable)
- [x] Netlify deployment with auto-deploy from GitHub
- [x] Custom domain: app.houseofbeers.nl

### Phase 10: Order Enhancements ✅
- [x] Estimated delivery date display on order line items
- [x] Fetches `custom.estimated_delivery_date` product metafield from Shopify
- [x] Batch GraphQL queries for efficient metafield retrieval

---

## Current App Structure

### Backend Apps
- `users/` - User model, authentication, Shopify service, account deletion
- `loyalty/` - Points rules, rewards, balances, transactions, redemptions, notifications, Celery sync tasks
- `recommendations/` - Beer recommendations, Untappd integration, favorites, taste profiles

### Mobile Tabs
- **Home** - Welcome message, notifications, "Your Beer Journey" menu
- **Favorites** - Beer wishlist with cart integration (badge shows count)
- **Loyalty** - Points balance, rewards, transactions, redemption codes
- **Profile** - User hub with navigation to:
  - Recommendations - Personalized beer picks
  - Taste Profile - Taste wheel, style distribution, top breweries
  - Favorites - Manage favorite beers
  - Orders - Shopify order history
  - Connect Untappd - Link/unlink Untappd account
  - Settings - Shopify sync, language picker, logout

---

## Localization (i18n)

### How It Works
- Uses `i18n-js` + `expo-localization`
- Translation files: `mobile/src/i18n/en.ts` and `mobile/src/i18n/nl.ts`
- LanguageContext provides `language`, `setLanguage`, and `languages` to all components
- Language preference stored in AsyncStorage

### Adding Translations
1. Add keys to both `en.ts` and `nl.ts`
2. Import and use in components:
```tsx
import { useLanguage } from '../../src/context/LanguageContext';
import { t } from '../../src/i18n';

function MyComponent() {
  const { language } = useLanguage(); // triggers re-render on language change
  return <Text>{t('my.translation.key')}</Text>;
}
```

### Adding a New Language
1. Create `mobile/src/i18n/xx.ts` with all translation keys
2. Import in `mobile/src/i18n/index.ts` and add to i18n translations
3. Add to `languages` array in index.ts

---

## API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register/` | Create account |
| POST | `/api/auth/login/` | Get JWT tokens (uses email) |
| POST | `/api/auth/refresh/` | Refresh access token |
| POST | `/api/auth/password-reset/` | Request password reset email |
| POST | `/api/auth/password-reset/confirm/` | Confirm password reset |

### Users
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/users/me/` | Get current user profile |
| POST | `/api/users/me/sync-shopify/` | Sync Shopify customer |
| GET | `/api/users/me/orders/` | Get Shopify orders |
| DELETE | `/api/users/me/delete/` | Delete user account |

### Loyalty
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/loyalty/summary/` | Points summary |
| GET | `/api/loyalty/balance/` | Detailed balance |
| GET | `/api/loyalty/transactions/` | Transaction history |
| GET | `/api/loyalty/rewards/` | Available rewards |
| POST | `/api/loyalty/redeem/` | Redeem a reward |
| GET | `/api/loyalty/redemptions/` | User's redemptions |
| POST | `/api/loyalty/sync/` | Sync points (intermediate sync) |
| GET | `/api/loyalty/sync/status/` | Check sync status |
| GET | `/api/loyalty/notifications/` | Active notifications |
| POST | `/api/loyalty/notifications/<id>/dismiss/` | Dismiss notification |

### Recommendations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/recommendations/` | Get personalized recommendations |
| GET | `/api/recommendations/profile/` | Get taste profile analysis |
| GET | `/api/recommendations/untappd/` | Get linked Untappd profile |
| POST | `/api/recommendations/untappd/link/` | Link Untappd username |
| POST | `/api/recommendations/untappd/unlink/` | Unlink Untappd account |
| GET | `/api/recommendations/favorites/` | Get user's favorite beers |
| POST | `/api/recommendations/favorites/` | Add beer to favorites |
| DELETE | `/api/recommendations/favorites/<id>/` | Remove from favorites |
| POST | `/api/recommendations/favorites/cart-link/` | Generate Shopify cart URL |

### Web Pages
| URL | Description |
|-----|-------------|
| `/admin/` | Django admin panel |
| `/reset-password/` | Password reset form |

---

## Environment Variables

### Backend (Dokku)
```bash
# Set via: dokku config:set houseofbeers-api KEY=value

SECRET_KEY=<auto-generated>
DEBUG=False
ALLOWED_HOSTS=appadmin.houseofbeers.nl
CSRF_TRUSTED_ORIGINS=https://appadmin.houseofbeers.nl
DATABASE_URL=<auto-set by postgres plugin>

# Shopify Admin API
SHOPIFY_STORE_URL=your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxx

# SMTP Email (Hostinger)
EMAIL_HOST=smtp.hostinger.com
EMAIL_PORT=465
EMAIL_USE_SSL=True
EMAIL_HOST_USER=your-email@houseofbeers.nl
EMAIL_HOST_PASSWORD=your-password
DEFAULT_FROM_EMAIL=noreply@houseofbeers.nl

# Password reset links
FRONTEND_URL=https://appadmin.houseofbeers.nl

# CORS (include PWA domain)
CORS_ALLOWED_ORIGINS=https://appadmin.houseofbeers.nl,https://app.houseofbeers.nl

# Redis (auto-set by dokku-redis plugin)
REDIS_URL=redis://...
```

### Mobile (eas.json)
API URL is configured per build profile in `eas.json`:
- **development**: `http://localhost:8000/api`
- **preview**: `https://appadmin.houseofbeers.nl/api`
- **production**: `https://appadmin.houseofbeers.nl/api`

---

## Development Commands

### Backend (Local)
```bash
cd backend
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# Management commands
python manage.py sync_shopify           # Sync unlinked users to Shopify
python manage.py sync_shopify --all     # Resync all users
python manage.py sync_points            # Partial sync all users (inline)
python manage.py sync_points --type intermediate  # Intermediate sync all users
python manage.py sync_points --type full          # Full check-and-correct all users
python manage.py sync_points --email user@example.com  # Sync specific user
python manage.py sync_points --async    # Dispatch as Celery tasks
python manage.py createsuperuser        # Create admin user

# Run Celery worker locally (for development)
celery -A config worker --loglevel=debug
celery -A config beat --loglevel=debug
```

### Mobile (Local)
```bash
cd mobile
npm install
npx expo start
# Press 'a' for Android, 'i' for iOS, 'w' for web
```

---

## Django Admin Setup

1. Create superuser: `dokku run houseofbeers-api python manage.py createsuperuser`
2. Access admin at: https://appadmin.houseofbeers.nl/admin/
3. Configure loyalty:
   - Add Points Rules (e.g., "1 point per €10 spent" → multiplier=0.1, points=1)
   - Add Rewards (e.g., "€5 off for 500 points")
   - Enable "Create Shopify discount" on rewards to auto-generate codes
4. Create notifications:
   - Add Notifications with title, message, type
   - Set optional show_from/show_until dates
   - Add optional link_url and link_text

---

## Key Implementation Notes

### JWT Authentication
- Uses `djangorestframework-simplejwt`
- Custom `EmailTokenObtainPairSerializer` to use email instead of username
- Access token: 30 minutes, Refresh token: 7 days
- Mobile app automatically refreshes tokens on 401 responses

### Shopify Integration
- Service: `backend/users/services/shopify.py`
- Auto-adds `https://` prefix to store URL if missing
- Customer lookup by email
- Order fetching for linked customers (with pagination via `Link` header)
- `get_customer_orders_since(customer_id, since_date)` — partial sync (new orders only)
- `get_all_customer_orders(customer_id)` — paginated fetch of ALL orders (250/page)
- Discount code creation via GraphQL API (supports all 4 discount types)

### Mobile Token Storage
- Native (iOS/Android): `expo-secure-store`
- Web: `localStorage` fallback
- Automatic token refresh on 401
- Handled in `mobile/src/api/client.ts`

### Points Calculation
- Rules evaluated in priority order, matched against the order's creation date
- Only processes paid orders (`financial_status='paid'`)
- `only_after_registration` flag on rules: skips orders placed before user's `date_joined`
- Admin-awarded points (adjusted transactions) are preserved across all sync types
- `balance_after` on all transactions is recalculated chronologically after full sync
- Service: `backend/loyalty/services/points.py`

### Discount Code Creation
- Uses Shopify GraphQL Admin API
- Supports: fixed discount, percentage discount, free shipping, free product
- Free product requires Shopify Product GID (e.g., `gid://shopify/Product/123456`)

---

## Loyalty Sync System

Three-tier sync system for keeping loyalty points in sync with Shopify orders. All syncs only process users who exist in the Django database and have a linked `shopify_customer_id` — no bulk Shopify customer fetching.

### Sync Tiers

| | Partial | Intermediate | Full |
|---|---|---|---|
| **What** | New orders since last sync | All orders, process unprocessed | Check-and-correct all orders |
| **Schedule** | Every 3 hours (all users) | Nightly 3 AM (all users) | Manual only |
| **Triggered by** | Celery beat | Celery beat, user taps "Sync" | Django admin action, CLI |
| **Runs in** | Celery worker (async) | Celery worker (async) / synchronous (user tap) | Celery worker (async) |
| **Shopify calls/user** | 1 | 1-3 (paginated) | 1-3 (paginated) |
| **Deletes anything** | No | No | No |

### How Each Sync Works

**Partial**: Looks at `SyncState.last_successful_sync` and calls `get_customer_orders_since()` to fetch only new orders. Passes them to `process_all_orders_for_user()` which skips already-processed orders via `ProcessedOrder` check.

**Intermediate**: Calls `get_all_customer_orders()` (paginated, 250/page) to fetch ALL orders. Same processing — skips already-processed orders. Catches anything the partial sync missed (backdated orders, pagination gaps).

**Full (check-and-correct)**: Fetches ALL orders, then for each already-processed order, recalculates what it SHOULD award with current rules and compares to what WAS awarded. If different, creates an `adjusted` transaction for the difference (e.g., "Points correction for order #1234 (50 → 75)"). Unprocessed orders are awarded normally. No deletions — preserves all history, discount codes, and redemptions.

### Key Models

- **`SyncState`** (OneToOne with User): Tracks `last_successful_sync`, `last_shopify_order_id`, `sync_status` (idle/in_progress/failed), `sync_started_at`, `last_error`. Prevents concurrent syncs with a lock (stale after 10 min).
- **`ProcessedOrder`**: Tracks which Shopify orders have been awarded points (`shopify_order_id` unique). Prevents duplicate awards.

### Key Files

- `backend/loyalty/services/points.py` — `partial_sync_for_user()`, `intermediate_sync_for_user()`, `full_sync_for_user()`, `check_and_correct_points()`
- `backend/loyalty/tasks.py` — Celery tasks wrapping the service methods
- `backend/loyalty/management/commands/sync_points.py` — CLI entry point
- `backend/users/services/shopify.py` — `_paginated_request()`, `get_all_customer_orders()`, `get_customer_orders_since()`

---

## Celery & Redis

### Infrastructure
- **Broker**: Redis via Dokku plugin (`dokku-redis`), auto-sets `REDIS_URL`
- **Config**: `backend/config/celery.py` (app definition), `backend/config/settings.py` (broker, beat schedule)
- **Init**: `backend/config/__init__.py` imports the celery app

### Dokku Processes (Procfile)
```
web: gunicorn config.wsgi --log-file -
worker: celery -A config worker --loglevel=info --concurrency=2
beat: celery -A config beat --loglevel=info
release: python manage.py migrate --noinput
```

### Beat Schedule
| Task | Schedule | Description |
|------|----------|-------------|
| `loyalty.tasks.periodic_partial_sync` | Every 3 hours | Partial sync for all users with Shopify accounts |
| `loyalty.tasks.periodic_intermediate_sync` | Daily at 3:00 AM | Intermediate sync for all users |

Both periodic tasks dispatch individual per-user tasks staggered 2 seconds apart to respect Shopify rate limits.

### Tasks
| Task | Description | Retry |
|------|-------------|-------|
| `partial_sync_user_points(user_id)` | Partial sync for one user | 3x, 60s delay |
| `intermediate_sync_user_points(user_id)` | Intermediate sync for one user | 3x, 60s delay |
| `full_sync_user_points(user_id)` | Full check-and-correct for one user | 2x, 120s delay |
| `periodic_partial_sync()` | Dispatches partial sync per user | — |
| `periodic_intermediate_sync()` | Dispatches intermediate sync per user | — |

---

## Planned Features (Not Yet Implemented)
- Community / chat
- Push notifications (separate from in-app notifications)
- Product browsing from Shopify
- Loyalty tiers/levels

---

## Recommendations System

### How It Works
The recommendations system analyzes user taste preferences to suggest beers from the House of Beers inventory.

**Data Sources (in priority order):**
1. **Untappd profile** - If linked, scrapes public check-ins to build taste profile
2. **Order history** - Falls back to Shopify purchase history if no Untappd

**Recommendation Types:**
- **Recommendations** - Best matches based on style preferences
- **Discovery Picks** - Beers outside comfort zone to try something new
- **Tried Beers** - Beers from inventory that user has already consumed

### Taste Profile Analysis
- **Radar Chart (Taste Wheel)** - Visual representation of style preferences
- **Style Distribution** - Bar chart of top beer styles
- **Top Breweries** - Favorite breweries by count
- **ABV Profile** - Preferred alcohol strength range

### Favorites & Cart Integration
- Users can favorite beers from recommendations
- Favorites stored in backend with beer metadata
- "Add to Cart" generates Shopify cart permalink with selected variants
- Cart link opens in browser, ready for checkout

### Mobile Navigation Pattern
Profile sub-screens use a nested Stack navigator inside the tabs:
```
/(tabs)
  /(profile)           → Stack navigator (hidden from tab bar)
    _layout.tsx        → Stack with logo header
    recommendations.tsx
    taste-profile.tsx
    favorites.tsx
    orders.tsx
    connect-untappd.tsx
```
This keeps the bottom tab bar visible while navigating profile screens.

---

## Troubleshooting

### "No active account found" on login
- JWT expects email field. Ensure `EmailTokenObtainPairSerializer` is used.

### Shopify customer not found
- Check `SHOPIFY_STORE_URL` has correct format (no https:// needed, added automatically)
- Verify customer email matches exactly in Shopify

### Token expired / Session errors
- Mobile app should auto-refresh tokens
- If issues persist, log out and log back in

### CORS errors
- Add frontend URL to `CORS_ALLOWED_ORIGINS` in Dokku config

### Discount code not created
- Ensure "Create Shopify discount" is enabled on the reward in Django admin
- Check Shopify API permissions include write access to discounts

### Password reset email shows localhost
- Set `FRONTEND_URL=https://appadmin.houseofbeers.nl` on Dokku

### Build fails on EAS
- Check build logs at https://expo.dev
- Common issue: dependency version conflicts (check package.json)

### PWA not updating
- Service worker caches aggressively; users may need to close all tabs and reopen
- Clear service worker in DevTools → Application → Service Workers → Unregister

### PWA shows wrong API URL
- Check `EXPO_PUBLIC_API_URL` in `netlify.toml` for production
- Local `.env` file overrides for development
- Rebuild with `npm run build:web` after changes

### Git subtree push fails
- If you get "Updates were rejected", try:
  ```bash
  git subtree split --prefix backend -b backend-deploy
  git push dokku backend-deploy:main --force
  git branch -D backend-deploy
  ```
