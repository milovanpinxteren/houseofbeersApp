# House of Beers App

## Project Overview
A loyalty and community app for houseofbeers.nl. This is a new project built from scratch. The app targets existing loyal customers — SEO is not a concern.

## Stack
- **Backend**: Django + Django REST Framework, hosted on Dokku at `appadmin.houseofbeers.nl`
- **Frontend**: Expo (React Native) with Expo Router. Native mobile app for iOS and Android.
- **Database**: PostgreSQL (production), SQLite (development)

## Repository Structure
```
/backend
  /config              → Django settings, urls, wsgi
  /users               → User model, auth, Shopify service
  /loyalty             → Points, rewards, notifications
  /templates           → Password reset web page

/mobile
  /app
    /(auth)            → Login, register, forgot-password screens
    /(tabs)            → Main app tabs (home, orders, loyalty, profile)
    reset-password.tsx → Password reset screen (unused, web version in backend)
    _layout.tsx        → Root layout with providers
  /src
    /api               → API client and endpoint functions
    /context           → AuthContext, LanguageContext
    /i18n              → Translations (en.ts, nl.ts)
    /theme             → Colors and spacing
  /assets              → Logo, icons, splash screen
  eas.json             → EAS Build configuration
```

---

## Deployment

### Backend (Dokku)
- **URL**: https://appadmin.houseofbeers.nl
- **Admin**: https://appadmin.houseofbeers.nl/admin/
- **API**: https://appadmin.houseofbeers.nl/api/
- **Server**: 89.145.161.168
- **App name**: `houseofbeers-api`
- **Database**: PostgreSQL via `dokku-postgres` plugin

#### Deploy Backend
```bash
cd backend
git add .
git commit -m "Your commit message"
git push dokku master:main
```

#### Useful Dokku Commands
```bash
ssh root@89.145.161.168

# View logs
dokku logs houseofbeers-api -t

# Run Django commands
dokku run houseofbeers-api python manage.py createsuperuser
dokku run houseofbeers-api python manage.py migrate

# Set environment variables
dokku config:set houseofbeers-api KEY=value

# View config
dokku config:report houseofbeers-api

# Restart app
dokku ps:restart houseofbeers-api
```

### Mobile (EAS Build)
- **Build service**: Expo Application Services (EAS)
- **Package**: `nl.houseofbeers.app`
- **EAS Project**: https://expo.dev/accounts/milovp/projects/house-of-beers

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
- [x] Rewards system (redeemable with points):
  - Fixed discount
  - Percentage discount
  - Free shipping
  - Free product (via Shopify product ID)
- [x] Shopify discount code generation on redemption (GraphQL API)
- [x] Loyalty tab with points balance, rewards, history, and redemption codes
- [x] Sync points from Shopify orders (recalculates with current rules)
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

---

## Current App Structure

### Backend Apps
- `users/` - User model, authentication, Shopify service, account deletion
- `loyalty/` - Points rules, rewards, balances, transactions, redemptions, notifications

### Mobile Tabs
- **Home** - Welcome message, notifications
- **Orders** - Shopify order history
- **Loyalty** - Points balance, rewards, transactions, redemption codes
- **Profile** - User info, Shopify sync, language picker, logout

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
| POST | `/api/loyalty/sync/` | Sync points from orders |
| GET | `/api/loyalty/notifications/` | Active notifications |
| POST | `/api/loyalty/notifications/<id>/dismiss/` | Dismiss notification |

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

# CORS
CORS_ALLOWED_ORIGINS=https://appadmin.houseofbeers.nl
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
python manage.py createsuperuser        # Create admin user
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
- Order fetching for linked customers
- Discount code creation via GraphQL API (supports all 4 discount types)

### Mobile Token Storage
- Native (iOS/Android): `expo-secure-store`
- Web: `localStorage` fallback
- Automatic token refresh on 401
- Handled in `mobile/src/api/client.ts`

### Points Calculation
- Rules evaluated in priority order
- Only processes paid orders
- Sync recalculates all points from scratch using current rules
- Service: `backend/loyalty/services/points.py`

### Discount Code Creation
- Uses Shopify GraphQL Admin API
- Supports: fixed discount, percentage discount, free shipping, free product
- Free product requires Shopify Product GID (e.g., `gid://shopify/Product/123456`)

---

## Planned Features (Not Yet Implemented)
- Community / chat
- Push notifications (separate from in-app notifications)
- Product browsing from Shopify
- Loyalty tiers/levels
- iOS App Store release

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
