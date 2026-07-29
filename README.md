# House of Beers App

A loyalty and community mobile app for [House of Beers](https://houseofbeers.nl) customers.

## Overview

This app allows House of Beers customers to:
- View their Shopify order history
- Earn and redeem loyalty points
- Receive notifications about promotions and events
- Manage their account and preferences

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Django 5 + Django REST Framework |
| Database | PostgreSQL (prod) / SQLite (dev) |
| Android App | Expo (React Native) - Google Play Store |
| iOS App | Progressive Web App (PWA) |
| Backend Hosting | Dokku on VPS |
| PWA Hosting | Netlify (auto-deploy from GitHub) |
| Build Service | Expo Application Services (EAS) |
| E-commerce | Shopify (customer data, orders, discounts) |

## Project Structure

```
house_of_beers_app/
├── backend/                 # Django REST API
│   ├── config/             # Django settings, URLs
│   ├── users/              # Authentication, user management
│   ├── loyalty/            # Points, rewards, notifications
│   └── templates/          # Password reset web page
│
├── mobile/                  # Expo React Native app
│   ├── app/                # Screens (Expo Router)
│   ├── src/
│   │   ├── api/           # API client
│   │   ├── context/       # React contexts
│   │   ├── i18n/          # Translations (EN/NL)
│   │   └── theme/         # Colors, spacing
│   ├── public/            # PWA assets (icons, manifest, service worker)
│   ├── scripts/           # Build scripts
│   └── assets/            # Images, icons
│
├── netlify.toml            # Netlify PWA deployment config
├── CLAUDE.md               # Detailed developer documentation
└── README.md               # This file
```

## Environments

| Environment | URL | Purpose |
|-------------|-----|---------|
| Backend API | https://appadmin.houseofbeers.nl | Production API |
| PWA (iOS) | https://app.houseofbeers.nl | iOS Progressive Web App |
| Android | Google Play Store | Native Android app |
| Development | http://localhost:8000 | Local backend |

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+
- npm or yarn
- Git

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Create .env file (copy from .env.example)
cp .env.example .env

# Run migrations
python manage.py migrate

# Create admin user
python manage.py createsuperuser

# Start server
python manage.py runserver
```

### Mobile Setup

```bash
cd mobile

# Install dependencies
npm install

# Start Expo
npx expo start

# Press 'a' for Android, 'i' for iOS, 'w' for web
```

## Deployment

### Backend (Dokku)

The backend is deployed to a Dokku server at `89.145.161.168` using git subtree (since backend is part of a monorepo).

```bash
# First time: add dokku remote
git remote add dokku dokku@89.145.161.168:houseofbeers-api

# Deploy backend folder to Dokku
git subtree push --prefix backend dokku main
```

Key files for Dokku deployment:
- `Procfile` - Process definitions
- `runtime.txt` - Python version
- `requirements.txt` - Dependencies

### PWA (Netlify) - For iOS Users

The PWA auto-deploys from GitHub when you push to `main`. Configuration is in `netlify.toml`.

```bash
# Local testing
cd mobile
npm run build:web
npm run serve:web
```

### Android (EAS Build)

Mobile builds are created using Expo Application Services.

```bash
cd mobile

# Preview build (APK for testing)
eas build --platform android --profile preview

# Production build (AAB for Play Store)
eas build --platform android --profile production

# Submit to Google Play
eas submit --platform android --profile production
```

## Configuration

### Backend Environment Variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | Debug mode (False in production) |
| `DATABASE_URL` | PostgreSQL connection URL |
| `SHOPIFY_STORE_URL` | Shopify store domain |
| `SHOPIFY_ACCESS_TOKEN` | Shopify Admin API token |
| `EMAIL_HOST_USER` | SMTP email address |
| `EMAIL_HOST_PASSWORD` | SMTP password |
| `FRONTEND_URL` | URL for password reset links |

### Mobile Build Profiles

Configured in `eas.json`:
- **development** - Local API, development client
- **preview** - Production API, internal distribution (APK)
- **production** - Production API, Play Store (AAB)

## API Documentation

The API is a REST API with JWT authentication.

### Main Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /api/auth/login/` | Login (returns JWT tokens) |
| `POST /api/auth/register/` | Create account |
| `GET /api/users/me/` | Current user profile |
| `GET /api/users/me/orders/` | Shopify order history |
| `GET /api/loyalty/summary/` | Points balance |
| `GET /api/loyalty/rewards/` | Available rewards |
| `POST /api/loyalty/redeem/` | Redeem a reward |

See [CLAUDE.md](./CLAUDE.md) for complete API documentation.

## Features

### Implemented
- User authentication (JWT)
- Shopify customer linking
- Order history from Shopify with estimated delivery dates
- Loyalty points system
- Rewards redemption with Shopify discount codes
- Admin-managed notifications
- Multi-language support (EN/NL)
- Account deletion (GDPR/Play Store compliance)
- Beer recommendations based on taste profile
- Untappd integration
- Favorites system with cart integration
- PWA for iOS users (installable, offline support)

### Planned
- Push notifications
- Community features
- Product browsing
- Loyalty tiers

## Admin Panel

Access the Django admin at: https://appadmin.houseofbeers.nl/admin/

Features:
- Manage users
- Configure points rules
- Create rewards
- Send notifications
- View redemptions and transactions

## Contributing

1. Create a feature branch
2. Make changes
3. Test locally
4. Push to deploy

## Documentation

- **[CLAUDE.md](./CLAUDE.md)** - Detailed developer documentation including:
  - Complete API reference
  - Environment variables
  - Deployment commands
  - Troubleshooting guide
  - Implementation details

## License

Private - House of Beers
