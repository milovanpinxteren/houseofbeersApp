// House of Beers design tokens.
// Typography matches houseofbeers.nl: Oswald (headings) + Crimson Text (body serif).

export const colors = {
  // Brand colors from houseofbeers.nl
  primary: '#d5c8ad',      // Beige/Tan - primary accent
  secondary: '#954e3b',    // Dark Brown - secondary accent
  tertiary: '#bea488',     // Warm Brown - tertiary accent

  // Base colors — warm near-black scale instead of pure black
  background: '#0c0a08',   // Warm near-black background
  surface: '#171310',      // Cards / elevated surfaces
  surfaceHigh: '#221c16',  // Higher elevation (modals, active cards)
  surfaceLow: '#100e0b',   // Recessed areas (input wells, insets)
  text: '#f5efe4',         // Warm off-white text
  textMuted: '#a89e8d',    // Warm muted text

  // Hairlines — prefer elevation contrast over borders; use sparingly
  border: 'rgba(213, 200, 173, 0.10)',
  borderStrong: 'rgba(213, 200, 173, 0.22)',

  // Semantic colors (warmed to sit well on the brown/beige palette)
  success: '#7cb46b',
  error: '#e2604c',
  warning: '#e0a43c',
  live: '#e2604c',
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
};

export const borderRadius = {
  sm: 8,
  md: 12,
  lg: 20,
  xl: 28,
  pill: 999,
};

// Font families (loaded in app/_layout.tsx)
export const fonts = {
  heading: 'Oswald_500Medium',
  headingRegular: 'Oswald_400Regular',
  headingBold: 'Oswald_600SemiBold',
  serif: 'CrimsonText_400Regular',
  serifItalic: 'CrimsonText_400Regular_Italic',
  serifBold: 'CrimsonText_600SemiBold',
};

// Type scale. Oswald is condensed and tall: give it letter-spacing and use
// uppercase for small labels; Crimson Text only at 15px and up for legibility.
export const type = {
  display: {
    fontFamily: fonts.headingBold,
    fontSize: 32,
    lineHeight: 40,
    letterSpacing: 0.5,
    color: colors.text,
  },
  title: {
    fontFamily: fonts.heading,
    fontSize: 22,
    lineHeight: 28,
    letterSpacing: 0.5,
    color: colors.text,
  },
  heading: {
    fontFamily: fonts.heading,
    fontSize: 17,
    lineHeight: 22,
    letterSpacing: 0.4,
    color: colors.text,
  },
  // Small uppercase section label, e.g. "JOUW BIERREIS"
  label: {
    fontFamily: fonts.heading,
    fontSize: 13,
    lineHeight: 18,
    letterSpacing: 1.6,
    textTransform: 'uppercase' as const,
    color: colors.textMuted,
  },
  serifBody: {
    fontFamily: fonts.serif,
    fontSize: 16,
    lineHeight: 23,
    color: colors.text,
  },
  serifLarge: {
    fontFamily: fonts.serif,
    fontSize: 19,
    lineHeight: 27,
    color: colors.text,
  },
  body: {
    fontSize: 14,
    lineHeight: 20,
    color: colors.text,
  },
  caption: {
    fontSize: 12,
    lineHeight: 16,
    color: colors.textMuted,
  },
};
