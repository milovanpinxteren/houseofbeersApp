/**
 * PWA Icon Generator Script
 *
 * This script requires the 'sharp' package to resize images.
 * Run: npm install sharp --save-dev
 * Then: node scripts/generate-pwa-icons.js
 *
 * Alternatively, you can manually create these icons using an online tool like:
 * https://www.pwabuilder.com/imageGenerator
 *
 * Required icons (place in mobile/public/icons/):
 * - icon-192.png (192x192) - Standard PWA icon
 * - icon-512.png (512x512) - Large PWA icon
 * - icon-maskable-192.png (192x192) - Maskable icon with safe zone padding
 * - icon-maskable-512.png (512x512) - Maskable icon with safe zone padding
 * - apple-touch-icon.png (180x180) - iOS home screen icon
 * - apple-touch-icon-152.png (152x152) - iPad
 * - apple-touch-icon-167.png (167x167) - iPad Pro
 * - apple-touch-icon-180.png (180x180) - iPhone
 * - favicon-16.png (16x16) - Browser tab icon
 * - favicon-32.png (32x32) - Browser tab icon
 * - badge-72.png (72x72) - Notification badge (monochrome white-on-transparent!)
 * - badge-96.png (96x96) - Notification badge (monochrome white-on-transparent!)
 *
 * iOS Splash Screens (optional but recommended):
 * - splash-1170x2532.png - iPhone 12/13/14
 * - splash-1284x2778.png - iPhone 12/13/14 Pro Max
 * - splash-1179x2556.png - iPhone 14 Pro
 */

const fs = require('fs');
const path = require('path');

// Check if sharp is installed
let sharp;
try {
  sharp = require('sharp');
} catch (e) {
  console.log('Sharp is not installed. Install it with: npm install sharp --save-dev');
  console.log('');
  console.log('Alternatively, manually create the icons using https://www.pwabuilder.com/imageGenerator');
  console.log('');
  console.log('Required icons (save to mobile/public/icons/):');
  console.log('  - icon-192.png (192x192)');
  console.log('  - icon-512.png (512x512)');
  console.log('  - icon-maskable-192.png (192x192 with padding)');
  console.log('  - icon-maskable-512.png (512x512 with padding)');
  console.log('  - apple-touch-icon.png (180x180)');
  console.log('  - apple-touch-icon-152.png (152x152)');
  console.log('  - apple-touch-icon-167.png (167x167)');
  console.log('  - apple-touch-icon-180.png (180x180)');
  console.log('  - favicon-16.png (16x16)');
  console.log('  - favicon-32.png (32x32)');
  console.log('  - badge-72.png (72x72)');
  process.exit(0);
}

const sourceIcon = path.join(__dirname, '..', 'assets', 'icon.png');
const sourceLogo = path.join(__dirname, '..', 'assets', 'logo.png');
const outputDir = path.join(__dirname, '..', 'public', 'icons');

// Ensure output directory exists
fs.mkdirSync(outputDir, { recursive: true });

// Icon sizes to generate
const icons = [
  // PWA standard icons
  { name: 'icon-192.png', size: 192 },
  { name: 'icon-512.png', size: 512 },

  // Maskable icons (with padding for safe zone)
  { name: 'icon-maskable-192.png', size: 192, maskable: true },
  { name: 'icon-maskable-512.png', size: 512, maskable: true },

  // Apple touch icons
  { name: 'apple-touch-icon.png', size: 180 },
  { name: 'apple-touch-icon-152.png', size: 152 },
  { name: 'apple-touch-icon-167.png', size: 167 },
  { name: 'apple-touch-icon-180.png', size: 180 },

  // Favicons
  { name: 'favicon-16.png', size: 16 },
  { name: 'favicon-32.png', size: 32 }

  // NOTE: badge-72/badge-96 are NOT in this list on purpose. Android
  // notification badges must be monochrome white-on-transparent (alpha only);
  // a colored/flattened icon renders as a solid white square in the status
  // bar. They are generated separately in generateBadges() below.
];

// Notification badge icons (Android status bar). White-on-transparent only.
const badges = [
  { name: 'badge-72.png', size: 72 },
  { name: 'badge-96.png', size: 96 }
];

// The wordmark in logo.png is unreadable at badge size, so the badge uses
// only the emblem (hop cone + house + barley sprigs) from the top of the
// logo. Bounding box measured on assets/logo.png (1022x606); re-measure if
// the logo file is ever replaced.
const EMBLEM_CROP = { left: 241, top: 15, width: 537, height: 297 };

// Splash screen sizes for iOS
const splashScreens = [
  { name: 'splash-1170x2532.png', width: 1170, height: 2532 }, // iPhone 12/13/14
  { name: 'splash-1284x2778.png', width: 1284, height: 2778 }, // iPhone 12/13/14 Pro Max
  { name: 'splash-1179x2556.png', width: 1179, height: 2556 }, // iPhone 14 Pro
];

/**
 * Notification badge icons.
 *
 * Android draws the badge as a silhouette: it only looks at the alpha channel
 * and paints every opaque pixel in the status bar color. The logo in
 * assets/logo.png is already white-on-transparent, so its alpha channel IS the
 * silhouette - we crop the emblem, take the alpha channel, and rebuild a pure
 * white image carrying that alpha.
 */
async function generateBadges() {
  console.log('Generating notification badges (white-on-transparent)...\n');

  for (const badge of badges) {
    const outputPath = path.join(outputDir, badge.name);

    try {
      // Small margin so the silhouette is not clipped by rounded masks.
      const margin = Math.round(badge.size * 0.05);
      const inner = badge.size - margin * 2;
      const transparent = { r: 0, g: 0, b: 0, alpha: 0 };

      const alpha = await sharp(sourceLogo)
        .extract(EMBLEM_CROP)
        .resize(inner, inner, { fit: 'contain', background: transparent })
        .extend({
          top: margin,
          bottom: margin,
          left: margin,
          right: margin,
          background: transparent
        })
        .ensureAlpha()
        .extractChannel('alpha')
        .toBuffer();

      // Solid white, with the emblem silhouette as the alpha channel.
      await sharp({
        create: {
          width: badge.size,
          height: badge.size,
          channels: 3,
          background: { r: 255, g: 255, b: 255 }
        }
      })
        .joinChannel(alpha)
        .png()
        .toFile(outputPath);

      console.log(`✓ Generated: ${badge.name}`);
    } catch (err) {
      console.error(`✗ Failed to generate ${badge.name}:`, err.message);
    }
  }
}

async function generateIcons() {
  if (process.argv.includes('--badges-only')) {
    await generateBadges();
    console.log('\nDone! Badges saved to public/icons/');
    return;
  }

  console.log('Generating PWA icons...\n');

  for (const icon of icons) {
    const outputPath = path.join(outputDir, icon.name);

    try {
      if (icon.maskable) {
        // Maskable icons need padding (safe zone is 80% of icon)
        const padding = Math.round(icon.size * 0.1);
        const innerSize = icon.size - (padding * 2);

        await sharp(sourceIcon)
          .resize(innerSize, innerSize)
          .extend({
            top: padding,
            bottom: padding,
            left: padding,
            right: padding,
            background: { r: 0, g: 0, b: 0, alpha: 1 }
          })
          .png()
          .toFile(outputPath);
      } else {
        await sharp(sourceIcon)
          .resize(icon.size, icon.size)
          .flatten({ background: { r: 0, g: 0, b: 0 } })
          .png()
          .toFile(outputPath);
      }
      console.log(`✓ Generated: ${icon.name}`);
    } catch (err) {
      console.error(`✗ Failed to generate ${icon.name}:`, err.message);
    }
  }

  console.log('\nGenerating splash screens...\n');

  // Get source image dimensions for centered splash screen
  const sourceMetadata = await sharp(sourceIcon).metadata();

  for (const splash of splashScreens) {
    const outputPath = path.join(outputDir, splash.name);

    try {
      // Create a black background with centered logo
      const logoSize = Math.min(splash.width, splash.height) * 0.3;

      const logo = await sharp(sourceIcon)
        .resize(Math.round(logoSize), Math.round(logoSize))
        .png()
        .toBuffer();

      await sharp({
        create: {
          width: splash.width,
          height: splash.height,
          channels: 4,
          background: { r: 0, g: 0, b: 0, alpha: 1 }
        }
      })
        .composite([{
          input: logo,
          gravity: 'center'
        }])
        .png()
        .toFile(outputPath);

      console.log(`✓ Generated: ${splash.name}`);
    } catch (err) {
      console.error(`✗ Failed to generate ${splash.name}:`, err.message);
    }
  }

  console.log('');
  await generateBadges();

  console.log('\nDone! Icons saved to public/icons/');
}

generateIcons().catch(console.error);
