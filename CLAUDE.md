# House of Beers App

## Project Overview
A loyalty and community app for houseofbeers.nl. This is a new project built from scratch. The app targets existing loyal customers — SEO is not a concern.

## Stack
- **Backend**: Django + Django REST Framework, hosted on Dokku at `appadmin.houseofbeers.nl`
- **Frontend**: Expo (React Native) with Expo Router
  - **All platforms**: Progressive Web App (PWA) at `app.houseofbeers.nl`
  - The native Android app (Google Play) is **deprecated** — every user is on
    the PWA, so frontend changes ship with a Netlify deploy, no store release.
- **Database**: PostgreSQL (production), SQLite (development)
- **Task Queue**: Celery + Redis (background sync, scheduled tasks)
- **Hosting**: Dokku (backend), Netlify (PWA)

## Repository Structure
```
/backend
  /config              → Django settings, urls, wsgi, celery
  /users               → User model, auth, Shopify service
  /loyalty             → Points, rewards, notifications, campaigns & raffles, Campagne Studio, sync tasks
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

# Scale gunicorn workers for more concurrent users (livestreams)
dokku config:set houseofbeers-api WEB_CONCURRENCY=4    # ~300-400 viewers (+200MB RAM)
dokku config:set houseofbeers-api WEB_CONCURRENCY=8    # ~600+ viewers (+400MB RAM)
# Default (unset) = 2 workers, handles ~150-200 concurrent viewers comfortably
# Set back after event: dokku config:unset houseofbeers-api WEB_CONCURRENCY
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

### Native Android app — DEPRECATED
The Google Play listing is retired; all users (Android and iOS) use the PWA.
Do not create EAS builds or Play Store submissions. The EAS project
(`nl.houseofbeers.app`, https://expo.dev/accounts/milovp/projects/house-of-beers)
remains only as historical reference.

---

## Brand Identity & Styling

### Color Palette
| Name | Hex | Usage |
|------|-----|-------|
| Beige/Tan | `#d5c8ad` | Primary accent, buttons, badges |
| Dark Brown | `#954e3b` | Secondary accent |
| Warm Brown | `#bea488` | Tertiary accent |
| Warm near-black | `#0c0a08` | Backgrounds (not pure black) |
| Surfaces | `#171310` / `#221c16` / `#100e0b` | Elevation via contrast steps, not borders |
| Warm off-white | `#f5efe4` | Text |

### Typography (matches houseofbeers.nl)
- **Headings / numbers / buttons / tab titles**: Oswald (`@expo-google-fonts/oswald`) — condensed, uppercase with letter-spacing for labels
- **Editorial text** (greetings, descriptions, notification bodies): Crimson Text (`@expo-google-fonts/crimson-text`), 15px+ only
- **Small functional UI text**: system sans
- Fonts loaded in `mobile/app/_layout.tsx`; families + type scale exported from `mobile/src/theme/colors.ts` (`fonts`, `type`)

### Design Principles
- Dark, premium aesthetic with elegant beige accents; elevation through surface contrast, borders only for accent cards
- Shared UI kit in `mobile/src/components/ui/` (Screen, Card, Button, ListItem, SectionHeader, Badge, EmptyState, Skeleton, Toast) — build new screens with these, not ad-hoc styles
- Feedback via toasts (`useToast`), loading via skeletons, press feedback on all touchables
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
- [x] Account deletion endpoint (originally for Google Play compliance; kept for GDPR)

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

### Phase 11: Loyalty Campaigns & Raffles ✅
- [x] Admin-defined campaigns: structured conditions → action (points / discount code / raffle entry) → notifications, alongside the PointsRule engine (see Loyalty Campaigns & Raffles section)
- [x] Cumulative cross-order condition evaluation (k-of-n products, window aggregates, customer conditions)
- [x] Two evaluation paths: per-order sync hook + shop-wide backfill (retroactive windows)
- [x] Raffles: weighted atomic draw, Shopify prize codes (`WIN-`) or manual fulfillment, redemption detection
- [x] Notification stages via the notifications outbox (`raffle` kind): qualify, ~3h pre-draw reminder, win/lose result
- [x] Campagne Studio at `/admin/campaign-studio/`: builder with live NL rule sentence + Shopify product search, async preview with near-misses, funnel monitor, CSV export
- [x] Mobile: RaffleSection cards on Home + Loyalty, replayable draw-reveal animation, `/raffle/{id}` push deep link, full funnel tracking (entered → notified → opened → watched → redeemed)

### Phase 12: Pickup RSVP ✅
- [x] Members announce their store pickup day on the orders screen (replaces the WhatsApp poll + hand-written warehouse list)
- [x] `fulfillment/` backend app: schedule (Fri/Sat seeded), closures, RSVPs, action log with hob-sync health
- [x] Server-to-server push to hob sets the warehouse queue (`Afhalen`) + priority (see Pickup RSVP section)
- [x] Orders screen renamed "Bestelgeschiedenis" → "Bestellingen"; `/pickup` deep link

---

## Current App Structure

### Backend Apps
- `users/` - User model, authentication, Shopify service, account deletion
- `loyalty/` - Points rules, rewards, balances, transactions, redemptions, notifications, campaigns & raffles, Campagne Studio, Celery sync tasks
- `recommendations/` - Beer recommendations, Untappd integration, favorites, taste profiles
- `fulfillment/` - Pickup RSVP (schedule, closures, RSVPs, hob sync); future home of other user fulfillment requests ("ship my orders", "check my orders")

### Mobile Tabs (redesigned Aug 2026)
- **Home** - Editorial greeting, notifications, events, quick links to Ontdek/Loyalty
- **Ontdek (Discover)** - Hub for recommendations, taste profile, favorites, Untappd link — future discovery features (random beer generator, subscriptions) slot in here
- **Community** - Feed, groups, chats, suggestions, livestreams (12-screen stack)
- **Loyalty** - Membership-card points hero, rewards, history, redemption codes, "how to earn" explainer
- **Profiel** - Pure account/settings: edit profile, orders, birthday, notifications, Shopify sync, language, logout

Sub-screens live in `(profile)` and `(community)` stacks (bottom bar stays visible); all have real header titles (no more logo-only header). Old `/favorites` tab route redirects to `(profile)/favorites`.

**Navigation model (Aug 2026 rework):** plain stack history — back is always one real
step back. Sub-screen headers use the shared `src/navigation/subStack.tsx`
(BackButton + screenOptions + stale-stack collapse); the Tabs navigator runs
`backBehavior="history"` so bubbling back (and Android hardware back) returns to
the tab you actually came from instead of Home. The old `useOriginPush`/`?from=`
system is deleted — push screens with plain `router.push`. Root `index` renders a
branded boot screen (logo + spinner, headerShown false) during the auth check.

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
| GET | `/api/loyalty/transactions/` | Transaction history (with per-rule `breakdown` and `reward_name`) |
| GET | `/api/loyalty/rules/` | Active points rules (used by the app's "How do I earn points?" section) |
| GET | `/api/loyalty/rewards/` | Available rewards |
| POST | `/api/loyalty/redeem/` | Redeem a reward |
| GET | `/api/loyalty/redemptions/` | User's redemptions |
| POST | `/api/loyalty/sync/` | Sync points (intermediate sync) |
| GET | `/api/loyalty/sync/status/` | Check sync status |
| GET | `/api/loyalty/campaigns/` | Non-raffle campaigns for the in-app "Acties" cards (teaser / qualified state) |
| GET | `/api/loyalty/raffles/` | Campaign raffles for the Home/Loyalty cards (FROZEN shape, see Campaigns section) |
| POST | `/api/loyalty/raffles/<id>/seen/` | Mark raffle card opened (empty 204; no-op without entry) |
| POST | `/api/loyalty/raffles/<id>/result-seen/` | Mark draw reveal watched (empty 204) |
| GET | `/api/loyalty/notifications/` | Active notifications |
| POST | `/api/loyalty/notifications/<id>/dismiss/` | Dismiss notification |

### Service API (server-to-server, used by hob)

Mounted at `/api/service/loyalty/` (`loyalty/service_api.py` + `service_urls.py`).
NOT for the mobile app: plain Django views authenticated by an HMAC-SHA256
signature over the raw body (`X-Signature: sha256=<hexdigest>`, shared secret
`SERVICE_API_HMAC_SECRET` — empty secret disables the API with 503). All
endpoints are POST with a JSON body. Caller: the houseofbeers_whatsapp app
("hob"), which awards loyalty points announced in WhatsApp sale chats
("En de 100 punten gaan naar +31 6 ...").

| Endpoint | Does |
|---|---|
| `grant/` | Award points. Idempotent on `dedupe_key`. Identity: `shopify_customer_id` → `email` (case-insensitive); ambiguous matches fail loudly (400). No member match → grant stored `pending`. `phone` is audit-only (User has no phone field). |
| `lookup/` | Membership check + pending points parked for an identity |
| `status/` | One grant by `dedupe_key` (404 if unknown) or filtered list |
| `revoke/` | Undo a grant; granted ones get a compensating negative transaction. Idempotent. |

Key design decisions (`loyalty/models_grants.py`, `loyalty/services/grants.py`):

- **`ServiceGrant`** model: one row per grant, `dedupe_key` unique (the
  idempotency guard, same idiom as `ProcessedOrder`), status
  `pending`/`granted`/`revoked`, decoupled `notified_delivery_id` int.
  Read-only in Django admin.
- **Points land as `earned` transactions** with `rule=None` and NO
  `shopify_order_id` (same shape as campaign awards): rendered verbatim by
  the mobile app (description fallback + `rule_name` in the breakdown for the
  expander), never touched by full sync's check-and-correct, counted by
  `repair_loyalty_history`'s earned recompute — zero mobile changes needed.
  Never use `adjusted` (renders as generic "Adjustment by House of Beers")
  and never set `shopify_order_id` on a grant row (repair would delete it).
- **Pending grants are claimed** by `claim_pending_grants(user)` (matches
  `shopify_customer_id` OR `email__iexact`), hooked into
  `ShopifyService.link_customer_to_user` (covers register auto-link, manual
  sync, bulk sync) AND `RegisterView.create` (email-only matches when no
  Shopify customer exists). MAX_GRANT_POINTS = 100,000 sanity cap.
- Grant notification via the outbox: kind `announcement`, dedupe
  `grant:<dedupe_key>`, url `/loyalty`; `notify: false` suppresses.
- Balance updates lock the `PointsBalance` row (`select_for_update`) — the
  first writer in the codebase to do so.
- Tests: `backend/loyalty/test_service_grants.py`.

### Recommendations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/recommendations/` | Get personalized recommendations |
| GET | `/api/recommendations/profile/` | Get taste profile analysis |
| GET | `/api/recommendations/untappd/` | Get linked Untappd profile |
| POST | `/api/recommendations/untappd/link/` | Link Untappd username |
| POST | `/api/recommendations/untappd/unlink/` | Unlink Untappd account |
| GET | `/api/recommendations/app-shop/` | App-exclusive beers (leftover sale stock at app price) |
| GET | `/api/recommendations/favorites/` | Get user's favorite beers |
| POST | `/api/recommendations/favorites/` | Add beer to favorites |
| DELETE | `/api/recommendations/favorites/<id>/` | Remove from favorites |
| POST | `/api/recommendations/favorites/cart-link/` | Generate Shopify cart URL |

### Pickup
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/pickup/days/` | Offered pickup days (next 14 days) with the caller's RSVP status |
| POST | `/api/pickup/rsvp/` | Announce pickup for a date (`{date}` → `{date, rsvp: true}`) |
| POST | `/api/pickup/rsvp/cancel/` | Withdraw a pickup RSVP (`{date}` → `{date, rsvp: false}`) |

### Web Pages
| URL | Description |
|-----|-------------|
| `/admin/` | Django admin panel |
| `/admin/campaign-studio/` | Campagne Studio (staff-only campaign builder/preview/monitor) |
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
- Earned transactions store a per-rule `breakdown` (JSON) so the app can explain where points came from
- The app renders transaction labels client-side from structured fields (localized); `description` is a fallback only
- Service: `backend/loyalty/services/points.py`

### Discount Code Creation
- Uses Shopify GraphQL Admin API — `create_basic_discount()` /
  `create_free_shipping_discount()` / `create_free_product_discount()` in
  `users/services/shopify.py`. There is no REST price-rule path any more (it
  could not carry `combinesWith`, see below).
- Supports: fixed discount, percentage discount, free shipping, free product
- Free product requires Shopify Product GID (e.g., `gid://shopify/Product/123456`)
- `customer_id` locks a code to one Shopify customer (the birthday gift uses it)

**Codes must combine (2026-09-05).** Shopify defaults every `combinesWith`
field to **false**, i.e. "this code cannot be used alongside any other
discount" — members reported not being able to use two of our codes in one
order and that default was the whole reason. Every creator now sends
`COMBINES_WITH_ALL` (all three discount classes true) unless a caller passes
`combines_with` explicitly; that covers reward redemptions, campaign codes,
raffle prizes (`WIN-`), birthday gifts (`BDAY-`) and sixpack codes (`SIX-`).
Things that are NOT in our control:

- Combination is **symmetric** — a discount created by hand in the Shopify
  admin needs its own Combinations boxes ticked or it still blocks ours.
- Our cart-wide fixed/percentage codes target `items: {all: true}`, which makes
  them **order**-class. Shopify only offers order+order and product+order
  combination to stores without `checkout.liquid` customizations. Free-product
  codes are product-class and free shipping is shipping-class, and those
  combine everywhere.
- Checkout caps at **5 product/order codes + 1 shipping code** per order, and
  two shipping discounts never stack.

`combinesWith` lives on the Shopify discount, not on our row, so codes minted
before this change stay non-combinable until repaired:
`python manage.py backfill_discount_combines [--apply]` (dry-run by default)
walks every still-redeemable code and calls
`ShopifyService.set_discount_combines_with()`. Tests:
`backend/loyalty/test_discount_combines.py`, `backend/users/tests.py`
(`ShopifyCombinesWithTests`, `ShopifySetCombinesWithTests`).

---

## Loyalty Sync System

Three-tier sync system for keeping loyalty points in sync with Shopify orders. All syncs only process users who exist in the Django database and have a linked `shopify_customer_id` — no bulk Shopify customer fetching.

### Sync Tiers

| | Partial | Intermediate | Full |
|---|---|---|---|
| **What** | New orders since last sync | All orders, process unprocessed | Check-and-correct all orders |
| **Schedule** | Manual/CLI only (beat entry removed 2026-08-10, ~2,000 Shopify calls/day for ~24 orders) | Nightly 3 AM (all users) | Manual only |
| **Triggered by** | CLI | Celery beat, user taps "Sync" | Django admin action, CLI |
| **Runs in** | Celery worker (async) | Celery worker (async) / synchronous (user tap) | Celery worker (async) |
| **Shopify calls/user** | 1 | 1-3 (paginated) | 1-3 (paginated) |
| **Deletes anything** | No | No | No |

### How Each Sync Works

**Partial**: Looks at `SyncState.last_successful_sync` and calls `get_customer_orders_since()` to fetch only new orders. Passes them to `process_all_orders_for_user()` which skips already-processed orders via `ProcessedOrder` check.

**Intermediate**: Calls `get_all_customer_orders()` (paginated, 250/page) to fetch ALL orders. Same processing — skips already-processed orders. Catches anything the partial sync missed (backdated orders, pagination gaps).

**Full (check-and-correct)**: Fetches ALL orders, then for each already-processed order, recalculates what it SHOULD award with current rules and compares to what WAS awarded. If different, the original `earned` transaction for that order is **updated in place** (points, description, breakdown) so users always see one clean row per order — no visible correction rows. If the new amount is 0 the earned row is deleted; `balance_after` is rewritten chronologically afterwards. Unprocessed orders are awarded normally. Discount codes and redemptions are never touched.

**Lifetime counter semantics**: `lifetime_spent` counts ONLY reward redemptions (cancel-and-refund decrements it). Corrections and manual admin adjustments are applied signed to `lifetime_earned`, never to `lifetime_spent`. The invariant `balance == lifetime_earned - lifetime_spent` holds for every user.

**One-off repair** (`python manage.py repair_loyalty_history`): folds legacy "Points correction" adjusted rows into their original earned rows, deletes them, recomputes both lifetime counters from source data (redemptions / earned transactions / manual adjustments), rewrites `balance_after`, and verifies the invariant. Dry-run by default; pass `--apply` to write, `--email user@example.com` for one user. This fixed the "5289 punten uitgegeven" complaints caused by rule-change corrections being counted as spent.

### Key Models

- **`SyncState`** (OneToOne with User): Tracks `last_successful_sync`, `last_shopify_order_id`, `sync_status` (idle/in_progress/failed), `sync_started_at`, `last_error`. Prevents concurrent syncs with a lock (stale after 10 min).
- **`ProcessedOrder`**: Tracks which Shopify orders have been awarded points (`shopify_order_id` unique). Prevents duplicate awards.

### Key Files

- `backend/loyalty/services/points.py` — `partial_sync_for_user()`, `intermediate_sync_for_user()`, `full_sync_for_user()`, `check_and_correct_points()`
- `backend/loyalty/tasks.py` — Celery tasks wrapping the service methods
- `backend/loyalty/management/commands/sync_points.py` — CLI entry point
- `backend/users/services/shopify.py` — `_paginated_request()`, `get_all_customer_orders()`, `get_customer_orders_since()`

---

## Loyalty Campaigns & Raffles

Admin-defined **campaigns**: structured purchase/customer conditions → one action (points, discount code, or raffle entry) → notifications. Campaigns sit ALONGSIDE the `PointsRule` engine — they never replace or modify it; they piggyback on the same order stream. Conditions are evaluated **cumulatively across all of a user's paid orders inside the campaign window**, so "buy 2 of these 3 beers" works across separate orders. Built and operated entirely from the Campagne Studio (below); the plain Django admin has read-only-ish ModelAdmins as an escape hatch (`backend/loyalty/admin.py`).

### Model Family

All in `backend/loyalty/models_campaigns.py`, star-imported at the end of `loyalty/models.py` (so `from loyalty.models import Campaign` works):

- **`Campaign`** — window, conditions, action config (`action_type`: points/discount_code/raffle), notification config, `rule_sentence` (auto-generated NL summary, editable, shown to customers), `status`, `preview_stale`, tag/collection snapshot (`resolved_product_ids`, `resolved_at`)
- **`CampaignProgress`** (unique campaign+user) — cumulative state in a `data` JSON: `spend`, `order_count`, `matcher_qty` (per-matcher quantities; key `'*'` when there are no matchers), `matched_order_ids`, `matched_products`, `max_order_value`, `first_order_ok`, and `processed_order_ids` — the **idempotency guard**: an order id already present is skipped entirely. `qualified_at` set once when thresholds first met.
- **`CampaignAward`** (unique campaign+user) — audit + idempotency of the fired action: `points_awarded` (cumulative for per_item), FK to the `PointsTransaction`, `discount_code`/`shopify_discount_id`, `notified_delivery_id` (plain int, NOT a FK — loyalty and notifications stay decoupled)
- **`CampaignRaffle`** (OneToOne `campaign.raffle`) — prize fields, `num_winners`, `draw_at` (null = manual draw only), `entry_mode` (`single` | `per_order` | `per_item`), `fulfillment_type` (`shopify_code` uses the campaign's `discount_*` fields as prize config | `manual`), `status` open/drawn, `send_reminder`/`reminder_sent_at`
- **`CampaignRafflePrize`** (`raffle.prizes`, ordered `ordering, id`) — an optional **prize tier**: one raffle can award several DIFFERENT prizes (shirt, hoodie, cap) from ONE entrant pool. `name`/`description`/`image_url`, `quantity` (how many winners get THIS prize) and its own `discount_*` config (blank fields fall back to the campaign's). `CampaignRaffle.prize_name` stays the headline the card shows; **no prize rows = pre-tier behaviour** (`num_winners` winners of the headline prize)
- **`RaffleEntry`** (unique raffle+user) — `ticket_count`, `matched_products` (display strings), `seen_at` (opened the card) and `result_seen_at` (watched the reveal) — the funnel timestamps
- **`CampaignRaffleWinner`** (unique raffle+user) — `prize` (nullable FK to the tier, SET_NULL), `prize_code`, `code_expires_at`, `fulfillment_status` (pending/code_issued/manual_pending/fulfilled), `redeemed_at`, `result_delivery_id` (int, not FK)
- **`CampaignPreview`** — async dry-run results for the Studio (`status`, `result` JSON with qualified + near-miss users)

### Condition Semantics

ALL configured conditions must hold; blank/null = condition not used.

- **`product_matchers`**: JSON list `[{"type": "sku"|"product_id"|"title"|"tag"|"collection", "value": "..."}]` (optional `label` for display only). Empty list = every paid order in the window counts. `title` matches case-insensitive substring.
- **k-of-n**: `min_distinct_products` = number of distinct matchers satisfied across the whole window. Each matcher is ONE slot — a tag/collection matcher is satisfied when any product in its resolved set is bought. `min_total_quantity` = total matched item quantity across the window.
- **Window aggregates**: `min_order_value` (at least one order with total ≥), `min_total_spend` (cumulative spend of ALL paid window orders, not just matched), `min_order_count`.
- **Customer conditions**: `first_order_only` (first-ever order in the window — judged against `ProcessedOrder`, so pre-app history is invisible, same as the first_order PointsRule), `only_after_registration`, `requires_untappd` (linked `UntappdProfile`), `min_points_balance` (at evaluation time), `registered_after`.
- **Snapshot**: tag/collection matchers are resolved to product-id lists via Shopify (`resolve_product_matchers()`) and stored on the campaign (`{matcher_index: [product_id, ...]}`). Refreshed nightly by `refresh_campaign_snapshots`; a failed Shopify call keeps that matcher's previous snapshot instead of wiping it.
- **Near miss** (preview only): every condition satisfied except exactly 1 short on `min_distinct_products`, `min_total_quantity`, or `min_order_count`.

### Audience Selection (2026-08-23)

Campaigns can target a **doelgroep** besides (or instead of) purchase conditions. `Campaign.audience_mode`:

- **`orders`** (default): purchase conditions drive qualification; a configured audience is an extra GATE (`checks['audience']` in `_condition_checks`, never a near-miss). No audience configured = everyone (pre-feature behavior).
- **`audience`**: the audience itself qualifies — no purchase needed. The order hook skips these campaigns entirely; `run_backfill` routes to `run_audience_backfill` (DB-only, no Shopify): dry-run returns the preview shape (audience = qualified list, `orders_scanned: 0`), live run qualifies each member once (idempotent via `qualified_at`/`CampaignAward`). New filter matches are added nightly by `refresh_campaign_snapshots`. Raffle `entry_mode` and `points_mode` are forced to `single`/`fixed` (no purchases to count). Open audience raffles are hidden from non-entrants in `RafflesListView` (no teaser you can't act on).

Audience = (users matching ALL `audience_filters`) ∪ (`manual_user_ids`), active users only. Filters (`loyalty/services/audience.py`, keys whitelisted in `FILTER_KEYS`): `min_age` & `birthday_month` (from `birthdate`; users without one never match), `min_app_age_days` (`date_joined`), `min_lifetime_orders` (ProcessedOrder count), `active_within_days` (`last_active_at`). Studio builder has a Doelgroep panel: mode select, filter inputs, live user search (`user-search/`) with chips, and a live audience count (`audience-count/`). Rule sentence: "Ieder lid dat in september jarig is, doet mee in de loting …" (audience mode) / "… Alleen voor leden die …" (orders-mode gate).

### Two Evaluation Paths

1. **Sync hook**: `process_all_orders_for_user()` in `points.py` calls `apply_order_to_campaigns(user, order)` for EVERY paid order (even 0-point ones), inside try/except — a campaign bug must never break the points sync. Applies the order to each `active` campaign whose window contains the order's `created_at`; atomic per campaign+user, idempotent via `processed_order_ids`.
2. **Shop-wide backfill**: `run_backfill(campaign, dry_run)` — ONE paginated scan via `ShopifyService.get_shop_orders_in_window(start, end)`; only orders whose `customer.id` matches an app user's `shopify_customer_id` count. Orders are applied oldest-first so progress and the qualification moment are chronological. `dry_run=True` produces the `CampaignPreview.result` shape without writing anything; a live run feeds each order through the same per-order logic as the sync hook. Runs on activation (covers retroactive windows: `window_start` before activation is fine).

**Qualification** fires exactly once (`CampaignAward`'s unique constraint is the guard, `fire_qualification()`): points → `earned` `PointsTransaction` with `rule=None` and breakdown `[{"campaign_id", "campaign_name", "points"}]` (points_mode `per_item` awards incrementally as later qualifying orders arrive); discount_code → single-use `HOB-XXXXXXXX` code via `services/discounts.py:create_discount_code()` (extracted from the old Reward path — reward redemptions now go through the same helper); raffle → `RaffleEntry` with tickets per `entry_mode`, recomputed on later orders while the raffle is open.

**Redeem links (`cart_url`)**: every minted code also gets a storefront link, resolved once at mint time by `services/discounts.py:build_cart_url()` and stored on `CampaignAward.cart_url` / `CampaignRaffleWinner.cart_url` (so serving a card costs no Shopify call). A `free_product` discount is 100% off ONE product and prize products are typically **UNLISTED** in the webshop — a bare code is then literally unredeemable, because the customer can neither find nor add the product, and Shopify rejects the code with a misleading "usage limit reached" message. So free_product codes get `/cart/<variant>:1?discount=<code>` (variant via `ShopifyService.get_product_cart_variant_id()`, prefers an available-for-sale variant; same permalink shape the sixpack checkout uses); every other type applies cart-wide and gets `/discount/<code>`. A failed variant lookup falls back to `/discount/<code>` rather than no link. Backfill for codes minted before the field existed: `python manage.py backfill_discount_cart_urls [--apply]`. Tests: `backend/loyalty/test_discount_cart_url.py`.

### Campaign Lifecycle

`draft` → `previewed` (a successful preview promotes it) → `active` (Studio activation; dispatches the live backfill) → `completed` → `archived`. Completion happens three ways: a raffle campaign completes when its raffle is drawn; a non-raffle campaign completes nightly once past `window_end` (`refresh_campaign_snapshots`); the Studio "deactivate" button completes immediately. Completed/archived campaigns are not editable. Activation is additionally blocked when `window_end` is already past (the audience backfill ignores the window, so an ended campaign would qualify people and then auto-complete the same night).

**`preview_stale` gating**: `Campaign.save()` sets `preview_stale=True` whenever any field in `Campaign.CONDITION_FIELDS` changes while draft/previewed; queryset `.update()` deliberately bypasses this (the preview task uses it to clear the flag). Activation requires status `previewed` AND `preview_stale=False` AND (for raffles) an existing `CampaignRaffle` — so you always activate against a preview of the actual conditions.

### Raffle Draw Semantics

`draw_raffle(raffle)` in `services/raffles.py` (mirrors `events/models.py:Raffle.draw_winners`):

- `select_for_update` on the raffle row; returns `None` if already drawn (double-draw/retry safe).
- **Weighted sampling WITHOUT replacement** by `ticket_count` — a user wins at most once, more tickets = better odds. `num_to_draw = min(prize_slots, entrant_count)`. Winners created individually so draw order = pk order.
- **Multi-prize**: `_prize_slots()` expands the prize tiers by quantity in (ordering, id) order; slot *i* goes to winner *i* of the SAME single sample, so prize 1 goes to the first name drawn and the winner of prize 1 can never also win prize 2. No tiers = `num_winners` slots with `prize=None` (unchanged).
- Raffle `status='drawn'` and campaign `status='completed'` flip **inside the locked transaction**; fulfillment and notifications run **after commit** (network I/O must never undo or re-run the draw).
- Fulfillment: `shopify_code` → `WIN-XXXXXXXX` single-use code per winner from that winner's prize config (`_discount_config()`: the tier's `discount_*` fields, campaign's as fallback) → `code_issued`; a failed mint leaves the winner `pending` (visible in the Studio monitor as needing attention). `manual` → `manual_pending`; the monitor's "afgehandeld" toggle sets `fulfilled`. (Code prefixes: `WIN-` raffle prizes, `HOB-` campaign qualification + reward codes, `BDAY-`/`SIX-` taken elsewhere — distinct prefixes keep order attribution clean.)
- Redemption detection: `check_winner_redemptions()` asks Shopify for usage (`get_discount_code_usage`, codeDiscountNodeByCode) and stamps `redeemed_at`. Best effort — one hiccup skips that winner, never the run.

### Notification Stages & Dedupe Keys

All via the notifications outbox (`notifications.services.send_notification`), kind `raffle` for raffle campaigns / `announcement` otherwise. The `raffle` kind (migration `notifications/0007_raffle_kind.py`) has push + email-fallback policy and its own `NotificationPreference.raffle` category. Sends never raise into campaign/draw logic.

| Stage | dedupe_key | Notes |
|-------|------------|-------|
| Qualify | `campaign:{cid}:{uid}:qualified` | Title/body from `qualify_title`/`qualify_body`, NL defaults built from rule_sentence/prize; url `/raffle/{rid}` (raffle) or `/loyalty`. `Campaign.qualify_email_fallback` (Studio checkbox, default OFF): members with NO active push subscription get `email_policy='always'` — otherwise a push-skip sends nothing at all (skip ≠ fail, so the kind's fallback policy never triggers) |
| Reminder | `campaign:{cid}:{uid}:reminder` | ~3h before `draw_at` (`REMINDER_WINDOW`), once per raffle via `reminder_sent_at` |
| Result | `campaign:{cid}:{uid}:result` | Winners: `email_policy='always'` when a code is attached (the code must reach an inbox); losers get a soft NL body. Same url |
| Studio test | `campaign:{cid}:test:{uid}:{preview_id}` | Sent only to the logged-in admin; excluded from the funnel |

**Funnel tracking**: entered (`RaffleEntry` / `qualified_at`) → notified (`NotificationDelivery` filtered on dedupe-key prefix `campaign:{cid}:`, `:test:` excluded; delivery ids also stored on `CampaignAward.notified_delivery_id` / `CampaignRaffleWinner.result_delivery_id`) → opened (`seen_at`) → watched draw (`result_seen_at`) → redeemed/fulfilled (`redeemed_at` or `fulfillment_status='fulfilled'`).

### Campagne Studio

Staff-only custom admin at **`/admin/campaign-studio/`** (`loyalty/studio_views.py` + `studio_urls.py`, one include in `config/urls.py`; templates `loyalty/templates/loyalty/studio/`, styling scoped under a `.studio` root and driven by the Django admin's own theme CSS variables so it follows the admin light/dark toggle). Reachable from the admin index via a `CampagneStudio` proxy model in `loyalty/admin.py` whose changelist redirects to the Studio (same trick as analytics `DashboardProxy`). Mirrors the analytics dashboard pattern: Celery dispatch with a synchronous fallback when no broker is running (local dev), status polled client-side. Dutch-first UI.

- **List** (`/`): all campaigns with status chips and funnel mini-stats (qualified/entries/winners).
- **Builder** (`new/`, `<pk>/edit/`): guided form; live Shopify product search (`product-search/` → `ShopifyService.search_products()`); live NL rule-sentence preview (POST `sentence/` shares the form parser); raffle section (prize, winners, draw time, entry mode, fulfillment) plus repeatable **prize rows** (hidden `raffle_prizes` JSON, same idiom as `product_matchers`; per row name/omschrijving/afbeelding/aantal + its own code config — with rows present `num_winners` is forced to the summed quantities and the manual field hides). Blank `rule_sentence` gets auto-generated via `build_rule_sentence()`. Changing the action away from `raffle` is blocked once tickets exist; prize rows are frozen once the raffle is drawn.
- **Preview** (`<pk>/`): "run preview" creates a `CampaignPreview` and dispatches `campaign_backfill(id, preview_id=...)`; polls `preview/status/`; shows qualified list, tickets, near-misses, orders scanned. "Stuur test naar mij" sends the qualify notification to the admin only. Activation lives here, gated as described above; deactivate/archive too.
- **Monitor** (`<pk>/monitor/`): funnel, per-user rows, prize-tier table, winner rows with the prize they won + prize codes, "Trek nu" (dispatches `draw_campaign_raffle`), "Check redemptions", manual-fulfill toggle, entrants CSV export (`<pk>/entrants.csv`).

### Mobile

- **API layer** `mobile/src/api/raffles.ts`: `getRaffles()`, `markRaffleSeen(id)`, `markRaffleResultSeen(id)`. The response shape is **FROZEN** (typed in that file, produced by `serialize_raffle` in `backend/loyalty/serializers.py`) — do not rename fields. `GET /api/loyalty/raffles/` returns open raffles of active campaigns to EVERY authenticated user (non-entrants get a teaser, `entered: false`) plus the caller's drawn-raffle archive: every drawn raffle they entered, newest first, capped at `RafflesListView.DRAWN_HISTORY_LIMIT` (20) — no time cutoff, so prize codes stay reachable while valid. Post-draw it adds `entrant_first_names` (shuffled, for the animation), `winner_first_names`/`public_winner_names` (draw order), `did_win`, and `my_code`/`my_code_expires_at`/`my_code_cart_url` for a winning caller. Multi-prize raffles additionally carry `prizes` (`[{id, name, description, image_url, quantity, ordering}]`, `[]` without tiers), `winner_prizes` (parallel to `winner_first_names`, null pre-draw AND for a tier-less raffle) and `my_prize_name` (the caller's tier, null when they didn't win or the raffle has no tiers) — all three are tier info, so a tier-less raffle reports them empty/null and the app falls back to `prize_name`. `my_code_cart_url` is the redeem link (see Redeem links above); `RaffleReveal` renders it as a "Prijs verzilveren" button under the code, because a bare prize code cannot be redeemed by browsing the shop.
- **204 contract**: the seen endpoints return an empty 204; `apiFetch` always calls `response.json()`, which throws `SyntaxError` on the empty body — `postNoContent()` treats that as success. Keep the backend responses empty.
- **Cards**: `RaffleSection` + `RaffleCard` in `mobile/src/components/RaffleCard.tsx`. Three variants keep the busier screens calm: `variant='alert'` (Home `app/(tabs)/index.tsx`) shows ONLY a drawn raffle the user entered and hasn't watched — everything else is hidden so Home stays quiet; `variant='active'` (default; Loyalty top `app/(tabs)/loyalty.tsx`) shows open raffles and drawn-but-reveal-not-watched; `variant='history'` (inside the Loyalty "Codes" tab, below redemption codes) is the archive: watched past draws as a vertical compact list under "Eerdere trekkingen", with code access for wins. Fetches on focus and on the host's pull-to-refresh (`refreshSignal`); renders NOTHING when its filtered list is empty (the normal state); active renders one card or a horizontal rail, sorted most-actionable-first (unseen draw → open+entered → teaser). Four card states: open+entered (tickets + draw time), open+not entered (rule-sentence teaser), drawn+not result_seen (prominent "Bekijk de trekking"), drawn+seen (compact winners line, code access for winners).
- **In-app "Acties" surface (non-raffle campaigns)**: `GET /api/loyalty/campaigns/` (`CampaignsListView` + `serialize_campaign`) serves active points/discount campaigns as teaser (rule sentence + end date) or qualified state (points awarded / copyable discount code with expiry plus a `discount_cart_url` "Korting verzilveren" button — see Redeem links above); completed campaigns stay visible while the caller holds a discount code from them (cap 10). Visibility mirrors raffles: audience-mode campaigns only for qualified members, orders-mode audience gates hide the teaser from outsiders. UI: `CampaignSection`/`CampaignCard` in `mobile/src/components/CampaignCard.tsx`, rendered ONLY on the Ontdek tab (below `AppShopSection`) — deliberately not on Home or Loyalty, both were too busy. i18n under `campaign.*`. Tests: `backend/loyalty/test_campaign_api.py`.
- **Reveal**: screen `mobile/app/(tabs)/(profile)/raffle/[id].tsx` (shared sub-stack, tab bar stays visible) renders `mobile/src/components/RaffleReveal.tsx` — the name-cycling animation ported from the livestream raffle overlay (decelerating shuffle → spring winner reveal → personal result with copyable code), with a replay button. Calls `markRaffleSeen` on first open pre-draw and `markRaffleResultSeen` when the reveal finishes.
- **Deep link**: push notifications link to `/raffle/{id}`; `mobile/app/raffle/[id].tsx` redirects into the `(profile)` sub-stack (same pattern as the old `/favorites` redirect).
- **i18n**: all strings under the `raffle.` namespace in both `en.ts` and `nl.ts`.

### Key Files

- `backend/loyalty/models_campaigns.py` — the model family above
- `backend/loyalty/services/campaigns.py` — `apply_order_to_campaigns()`, `fire_qualification()`, `run_backfill()`, `build_rule_sentence()`, `resolve_product_matchers()`
- `backend/loyalty/services/raffles.py` — `draw_raffle()`, `send_raffle_reminders()`, `check_winner_redemptions()`
- `backend/loyalty/services/discounts.py` — shared `create_discount_code()` (campaigns, raffle prizes, AND reward redemptions)
- `backend/loyalty/tasks.py` — `campaign_backfill`, `refresh_campaign_snapshots`, `draw_campaign_raffle`, `campaign_raffle_scheduler`, `check_winner_redemptions`
- `backend/loyalty/views.py` + `serializers.py` — `RafflesListView`, seen endpoints, `serialize_raffle()`
- `backend/loyalty/studio_views.py` + `studio_urls.py` — Campagne Studio
- `backend/users/services/shopify.py` — `get_shop_orders_in_window()`, `get_product_ids_by_tag()`, `get_collection_product_ids()`, `search_products()`, `get_discount_code_usage()`
- `backend/notifications/` — `raffle` kind + preference category (migration 0007)
- `mobile/src/api/raffles.ts`, `mobile/src/components/RaffleCard.tsx`, `RaffleReveal.tsx`, `mobile/app/(tabs)/(profile)/raffle/[id].tsx`, `mobile/app/raffle/[id].tsx`
- Tests: `backend/loyalty/test_campaigns.py`, `test_raffles.py`, `test_studio.py`, `test_campaign_e2e.py`

---

## Pickup RSVP (Afhalen)

Members announce on the orders screen which store-open day (Fri 10:00–20:00 /
Sat 10:00–17:00, Prior van Millstraat 2 Uden) they'll come pick up their
order — replaces the occasional WhatsApp poll whose answers were hand-copied
for the warehouse. Backend app `fulfillment/`, deliberately also the future
home of other user fulfillment requests ("ship my orders", "check my
orders"). Design rule: NO automation — no beat tasks, no auto queue
clearing, no priority recalculation; staff clear the hob queue manually
during pickup, exactly as before.

- **Models** (`backend/fulfillment/models.py`): `PickupSchedule` (weekday +
  open/close times; Fri/Sat seeded by migration 0002), `PickupClosure`
  (date + reason removes a day), `PickupRSVP` (unique user+date,
  active/cancelled, re-RSVP reactivates the same row), `PickupActionLog` —
  one row per rsvp/cancel action, doubling as usage log AND hob-sync health
  (`sync_status` pending/success/failed/skipped, attempts, response
  snippet) so a broken hob link is visible in the appadmin.
- **API**: `GET /api/pickup/days/` = next 14 days with an active schedule
  minus closures; today is dropped once local time ≥ close_time
  (TIME_ZONE is Europe/Amsterdam = store time). The POSTs are idempotent
  and return real JSON 200s (no 204s). Analytics events `pickup_rsvp` /
  `pickup_rsvp_cancel`.
- **hob sync** (`fulfillment/services/hob_sync.py` + Celery task, 3 retries,
  inline fallback without broker): every action row is POSTed to hob at
  `{HOB_SERVICE_URL}/api/service/app/pickup-rsvp/`, HMAC-SHA256 over the
  raw body (`X-Signature: sha256=<hex>`) — the outbound mirror of the
  inbound loyalty service API. Settings `HOB_SERVICE_URL` +
  `HOB_SERVICE_HMAC_SECRET`; either empty → rows are `skipped` and RSVPs
  still work. Success requires 2xx AND `{"success": true}`; hob's
  `customer_found: false` is a success (no retry loop for unlinked users).
- **hob side** (hob repo `apps/order_management/app_service.py`): rsvp sets
  customer queue `Afhalen` + priority `max(current, 80)` (metafield-first
  via the shared `customer_queue.py` write path, audit row username `app`);
  cancel reverts ONLY its own values (queue still `Afhalen`, priority
  exactly 80 → back to auto). The `Afhalen` choice must exist in Shopify's
  `custom.queue` customer-metafield definition. Secret env on hob:
  `APP_SERVICE_HMAC_SECRET` (same value as the app's
  `HOB_SERVICE_HMAC_SECRET`).
- **Admin**: schedule + closures editable; RSVP list with CSV export
  (`afhaal-aanmeldingen.csv` — the warehouse list, until the hob queue
  makes it redundant); action log read-only with an "Opnieuw
  synchroniseren met hob" action to re-push after an outage.
- **Mobile**: `PickupSection` (`mobile/src/components/PickupSection.tsx`) at
  the top of the orders screen (title renamed Bestelgeschiedenis →
  "Bestellingen"): quiet collapsed Card row; expanded = one-tap toggle
  chips per day ("vr 26 sep · 10:00–20:00") + address/route link; renders
  NOTHING on empty/error (the normal state for the ~80% delivery
  members). Deep link `/pickup` (`mobile/app/pickup.tsx`) opens the orders
  screen with the section expanded — target for "geef het door in de app"
  WhatsApp/push nudges. API layer `mobile/src/api/pickup.ts`; i18n under
  `pickup.*`.
- Tests: `backend/fulfillment/tests.py` (26); hob
  `apps/order_management/tests_app_service.py` (31).

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
Loyalty entries (other apps — birthday scan, notifications, recommendations — register their own entries in `settings.py` too):

| Task | Schedule | Description |
|------|----------|-------------|
| `loyalty.tasks.periodic_intermediate_sync` | Daily at 3:00 AM | Intermediate sync for all users |
| `loyalty.tasks.refresh_campaign_snapshots` | Daily at 3:30 AM | Re-resolve campaign tag/collection snapshots; complete non-raffle campaigns past `window_end` (after the 3:00 sync so completion sees that night's final progress) |
| `loyalty.tasks.campaign_raffle_scheduler` | Every 5 minutes | Draw open raffles past `draw_at`; send ~3h pre-draw reminders |
| `loyalty.tasks.check_winner_redemptions` | Daily at 4:00 AM | Mark raffle prize codes redeemed once Shopify reports usage |

`periodic_partial_sync` no longer has a beat entry (removed 2026-08-10 — too many Shopify calls). The intermediate sync dispatches individual per-user tasks staggered 2 seconds apart to respect Shopify rate limits.

### Tasks
| Task | Description | Retry |
|------|-------------|-------|
| `partial_sync_user_points(user_id)` | Partial sync for one user | 3x, 60s delay |
| `intermediate_sync_user_points(user_id)` | Intermediate sync for one user | 3x, 60s delay |
| `full_sync_user_points(user_id)` | Full check-and-correct for one user | 2x, 120s delay |
| `periodic_partial_sync()` | Dispatches partial sync per user (no beat entry) | — |
| `periodic_intermediate_sync()` | Dispatches intermediate sync per user | — |
| `campaign_backfill(campaign_id, preview_id=None)` | Shop-wide scan for one campaign; with `preview_id` a dry-run whose result lands in that CampaignPreview | 2x, 120s (live run only) |
| `refresh_campaign_snapshots()` | Nightly snapshot refresh + completes ended non-raffle campaigns | — |
| `draw_campaign_raffle(raffle_id)` | Draw one campaign raffle (scheduler or Studio "Trek nu"); already-drawn = logged no-op | 2x, 60s delay |
| `campaign_raffle_scheduler()` | Draws due raffles inline + sends reminders | — |
| `check_winner_redemptions()` | Stamps `redeemed_at` on used prize codes | — |

---

## Livestream Performance

### Polling Architecture
The livestream uses a single combined poll endpoint (`GET /events/{id}/poll/`) instead of separate requests for chat, winners, and auction. This reduces load by ~4.5x.

- **Poll interval**: 3 seconds (chat responsiveness)
- **Heartbeat** (presence update): every 60 seconds (every 20th poll)
- **Viewer count cutoff**: 90 seconds (matches heartbeat frequency)
- **Winner data**: only sent when winner count changes (server compares to client's `known_winner_count`)
- **Viewer names**: included alongside winner data for raffle animation (no extra request)

### Capacity

| Gunicorn Workers (`WEB_CONCURRENCY`) | Max Concurrent Viewers | RAM Impact |
|---|---|---|
| 2 (default) | ~150-200 | Baseline |
| 4 | ~300-400 | +200MB |
| 8 | ~600+ | +400MB |

To scale up before a big event:
```bash
dokku config:set houseofbeers-api WEB_CONCURRENCY=4
```
To reset after:
```bash
dokku config:unset houseofbeers-api WEB_CONCURRENCY
```

The bottleneck is gunicorn workers, not the database. Each poll is ~5-15ms DB time.

---

## Planned Features (Not Yet Implemented)
- Community / chat
- Push notifications (separate from in-app notifications)
- Product browsing from Shopify
- Loyalty tiers/levels
- ~~App-exclusive shop UI~~ **DONE (2026-08-11)**: the `houseofbeers_whatsapp`
  pipeline tags leftover WhatsApp-sale products `app-only` and moves remaining
  stock to an "App" variant at a secondary price. Backend:
  `GET /api/recommendations/app-shop/` serves them on demand (cached 30 min,
  empty state 5 min, **deliberately no beat task** — zero background Shopify
  calls) with `title` (clean `custom.app_title`), `price`/`variant_id`/
  `inventory` from the **App variant** (never `variants[0]` — that's the Sale
  variant), Untappd rating/check-ins, style, ABV, description, and a
  ready-made `cart_url`. Mobile: `AppShopSection` at the top of the Ontdek
  tab — renders NOTHING when the list is empty (the normal state), card rail
  + detail bottom sheet with a Bestellen button that opens `cart_url`.
  Products are UNLISTED in the webshop — the app is the only place they're
  visible. Tested end-to-end with a live temp product (created + deleted).
  **Gemist wall (2026-08-18)**: when hob archives a batch (next sale arrived)
  it zeroes the App variant and adds tag `app-archived`; those products stay
  in the API response with `buyable: false`, `sale_price` (WhatsApp deal
  price) next to `price`, and `cart_url: null`. UI shows them dimmed with a
  "Sale voorbij" badge, both prices struck through, no order button — the
  FOMO wall (hob keeps the 5 most recent archived sales, older ones get the
  tags removed and disappear). Sold-out-but-NOT-archived products are still
  dropped as before. Local demo: `APP_SHOP_DEMO=1` includes two archived
  items.

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
