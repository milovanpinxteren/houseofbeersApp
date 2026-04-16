const fs = require('fs');
const path = require('path');

const publicDir = path.join(__dirname, '..', 'public');
const distDir = path.join(__dirname, '..', 'dist');

// Files to copy from public to dist (NOT index.html - we merge that separately)
const filesToCopy = [
  'manifest.json',
  'service-worker.js'
];

// Directories to copy
const dirsToCopy = [
  'icons'
];

// FIRST: Read the Expo-generated index.html BEFORE we copy anything
const expoIndexPath = path.join(distDir, 'index.html');
const pwaIndexPath = path.join(publicDir, 'index.html');

let expoScripts = '';
if (fs.existsSync(expoIndexPath)) {
  const expoHtml = fs.readFileSync(expoIndexPath, 'utf8');
  // Extract the script tags from Expo's HTML (the bundled JS)
  const scriptMatch = expoHtml.match(/<script[^>]*src="[^"]*"[^>]*><\/script>/g);
  expoScripts = scriptMatch ? scriptMatch.join('\n  ') : '';
  console.log(`Found Expo scripts: ${scriptMatch ? scriptMatch.length : 0}`);
}

// Copy individual files
filesToCopy.forEach(file => {
  const src = path.join(publicDir, file);
  const dest = path.join(distDir, file);

  if (fs.existsSync(src)) {
    fs.copyFileSync(src, dest);
    console.log(`Copied: ${file}`);
  } else {
    console.warn(`Warning: ${file} not found in public/`);
  }
});

// Copy directories recursively
function copyDir(src, dest) {
  if (!fs.existsSync(src)) {
    console.warn(`Warning: Directory ${src} not found`);
    return;
  }

  fs.mkdirSync(dest, { recursive: true });

  const entries = fs.readdirSync(src, { withFileTypes: true });

  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);

    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
      console.log(`Copied: icons/${entry.name}`);
    }
  }
}

dirsToCopy.forEach(dir => {
  copyDir(path.join(publicDir, dir), path.join(distDir, dir));
});

// NOW: Merge our PWA index.html with Expo scripts
if (fs.existsSync(pwaIndexPath) && expoScripts) {
  // Read our PWA index.html
  let pwaHtml = fs.readFileSync(pwaIndexPath, 'utf8');

  // Insert the Expo scripts before </body>
  // The app-loaded class should be added by the React app after it mounts, not immediately
  pwaHtml = pwaHtml.replace(
    '</body>',
    `  ${expoScripts}\n</body>`
  );

  // Write the merged HTML
  fs.writeFileSync(path.join(distDir, 'index.html'), pwaHtml);
  console.log('Merged PWA index.html with Expo scripts');
} else if (fs.existsSync(pwaIndexPath)) {
  // No Expo scripts found, just copy the PWA index.html (shouldn't happen normally)
  console.warn('Warning: No Expo scripts found, copying PWA index.html as-is');
  fs.copyFileSync(pwaIndexPath, path.join(distDir, 'index.html'));
}

console.log('PWA assets copied successfully!');
