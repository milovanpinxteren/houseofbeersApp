import type { ComponentProps } from 'react';
import { Ionicons } from '@expo/vector-icons';

type IoniconName = ComponentProps<typeof Ionicons>['name'];

// Wizard style families -> recommender style_category values.
// Category names must match the recommender's style_mapper output exactly.
export interface StyleFamily {
  key: string;
  categories: string[];
  icon: IoniconName;
}

export const STYLE_FAMILIES: StyleFamily[] = [
  { key: 'sour_funky', categories: ['Sour', 'Wild/Lambic'], icon: 'flask-outline' },
  { key: 'dark_heavy', categories: ['Stout', 'Porter'], icon: 'moon-outline' },
  { key: 'hoppy', categories: ['IPA', 'Pale Ale'], icon: 'leaf-outline' },
  { key: 'belgian_classic', categories: ['Belgian'], icon: 'business-outline' },
  { key: 'blond_light', categories: ['Lager', 'German', 'British'], icon: 'sunny-outline' },
  { key: 'wheat', categories: ['Wheat'], icon: 'nutrition-outline' },
  { key: 'barrel_barleywine', categories: ['Barleywine', 'Bock'], icon: 'cube-outline' },
];

export const FAMILY_LABEL_KEYS: Record<string, string> = {
  sour_funky: 'sixpack.familySourFunky',
  dark_heavy: 'sixpack.familyDarkHeavy',
  hoppy: 'sixpack.familyHoppy',
  belgian_classic: 'sixpack.familyBelgianClassic',
  blond_light: 'sixpack.familyBlondLight',
  wheat: 'sixpack.familyWheat',
  barrel_barleywine: 'sixpack.familyBarrelBarleywine',
};

export const BUDGET_PRESETS = [40, 55, 70, 85, 100] as const;

export type Adventurousness = 'safe' | 'balanced' | 'adventurous';

export interface SixpackPrefs {
  budget: number;
  excludedFamilies: string[];
  includeAlcoholFree: boolean;
  adventurousness: Adventurousness;
}

export const DEFAULT_PREFS: SixpackPrefs = {
  budget: 55,
  excludedFamilies: [],
  includeAlcoholFree: false,
  adventurousness: 'balanced',
};

export const PREFS_STORAGE_KEY = 'sixpack:prefs:v1';

export function excludedCategoriesFor(prefs: SixpackPrefs): string[] {
  return STYLE_FAMILIES.filter((f) => prefs.excludedFamilies.includes(f.key))
    .flatMap((f) => f.categories);
}
