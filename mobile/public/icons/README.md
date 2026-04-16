# PWA Icons

This directory contains icons for the Progressive Web App.

## Generate Icons Automatically

1. Install sharp: `npm install sharp --save-dev`
2. Run: `node scripts/generate-pwa-icons.js`

## Generate Icons Manually

Use https://www.pwabuilder.com/imageGenerator with `assets/icon.png`

### Required Icons

| File | Size | Purpose |
|------|------|---------|
| icon-192.png | 192x192 | Standard PWA icon |
| icon-512.png | 512x512 | Large PWA icon |
| icon-maskable-192.png | 192x192 | Maskable (with safe zone padding) |
| icon-maskable-512.png | 512x512 | Maskable (with safe zone padding) |
| apple-touch-icon.png | 180x180 | iOS home screen |
| apple-touch-icon-152.png | 152x152 | iPad |
| apple-touch-icon-167.png | 167x167 | iPad Pro |
| apple-touch-icon-180.png | 180x180 | iPhone |
| favicon-16.png | 16x16 | Browser tab |
| favicon-32.png | 32x32 | Browser tab |
| badge-72.png | 72x72 | Notification badge |

### Optional Splash Screens

| File | Size | Device |
|------|------|--------|
| splash-1170x2532.png | 1170x2532 | iPhone 12/13/14 |
| splash-1284x2778.png | 1284x2778 | iPhone Pro Max |
| splash-1179x2556.png | 1179x2556 | iPhone 14 Pro |

**Tip:** Use black (#000000) background with centered logo for splash screens.
