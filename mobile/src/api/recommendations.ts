import { apiFetch } from './client';

// Types

export interface Beer {
  id: number;
  title: string;
  vendor: string;
  price: string | null;
  image_url: string;
  product_url: string;
  untappd_rating: number | null;
  abv: number | null;
  style_category: string;
  variant_id: string;
}

export interface ScoredBeer {
  beer: Beer;
  score: number;
  confidence: 'high' | 'medium' | 'low';
  is_tried: boolean;
  reasons: string[];
}

export interface ProfileSummary {
  total_checkins: number;
  unique_beers: number;
  avg_rating: number;
  preferred_styles: string[];
  abv_range: string;
}

export interface RecommendationsResponse {
  profile_summary: ProfileSummary;
  recommendations: ScoredBeer[];
  discovery_picks: ScoredBeer[];
  tried_beers: ScoredBeer[];
  profile_source: 'untappd' | 'shopify';
  profile_identifier: string;
}

export interface RadarChartData {
  axes: string[];
  values: number[];
  details: Array<{
    style: string;
    count: number;
    avg_rating: number | null;
    score: number;
  }>;
}

export interface TasteProfileResponse {
  username: string;
  total_checkins: number;
  unique_beers: number;
  radar_chart: RadarChartData;
  style_distribution: Array<{
    style: string;
    count: number;
    percentage: number;
  }>;
  abv_profile: {
    min: number | null;
    max: number | null;
    avg: number | null;
    preferred_min: number | null;
    preferred_max: number | null;
    range_label: string;
    category: string;
  };
  rating_profile: {
    average: number;
    category: string;
  };
  top_breweries: Array<{
    brewery: string;
    count: number;
    avg_rating: number;
  }>;
  profile_source: 'untappd' | 'shopify';
  profile_identifier: string;
}

export interface UntappdProfile {
  username: string;
  linked_at: string;
  last_synced: string | null;
}

export interface Favorite {
  id: number;
  beer_id: string;
  variant_id: string;
  title: string;
  vendor: string;
  price: string | null;
  image_url: string;
  product_url: string;
  untappd_rating: number | null;
  abv: number | null;
  style: string;
  created_at: string;
}

export interface StyleOption {
  category: string;
  count: number;
}

export interface CartLinkResponse {
  cart_url: string;
  item_count: number;
  items: Array<{
    title: string;
    variant_id: string;
    price: string | null;
  }>;
}

// API Functions

export async function getRecommendations(params?: {
  limit?: number;
  price_max?: number;
  style_filter?: string;
}): Promise<RecommendationsResponse> {
  const queryParams = new URLSearchParams();
  if (params?.limit) queryParams.set('limit', params.limit.toString());
  if (params?.price_max) queryParams.set('price_max', params.price_max.toString());
  if (params?.style_filter) queryParams.set('style_filter', params.style_filter);

  const query = queryParams.toString();
  const endpoint = '/recommendations/' + (query ? '?' + query : '');

  return apiFetch<RecommendationsResponse>(endpoint);
}

export async function getTasteProfile(): Promise<TasteProfileResponse> {
  return apiFetch<TasteProfileResponse>('/recommendations/profile/');
}

export async function getStyles(): Promise<{ styles: StyleOption[] }> {
  return apiFetch<{ styles: StyleOption[] }>('/recommendations/styles/');
}

// Untappd Profile

export async function getUntappdProfile(): Promise<{ untappd: UntappdProfile | null }> {
  return apiFetch<{ untappd: UntappdProfile | null }>('/recommendations/untappd/');
}

export async function linkUntappd(username: string): Promise<{
  success: boolean;
  untappd: UntappdProfile;
  message: string;
}> {
  return apiFetch('/recommendations/untappd/', {
    method: 'POST',
    body: JSON.stringify({ username }),
  });
}

export async function unlinkUntappd(): Promise<{ success: boolean; message: string }> {
  return apiFetch('/recommendations/untappd/', {
    method: 'DELETE',
  });
}

// Favorites

export async function getFavorites(): Promise<{ favorites: Favorite[] }> {
  return apiFetch<{ favorites: Favorite[] }>('/recommendations/favorites/');
}

export async function addFavorite(beer: {
  beer_id: string;
  variant_id?: string;
  title: string;
  vendor?: string;
  price?: number | null;
  image_url?: string;
  product_url?: string;
  untappd_rating?: number | null;
  abv?: number | null;
  style?: string;
}): Promise<{ success: boolean; favorite: Favorite }> {
  return apiFetch('/recommendations/favorites/', {
    method: 'POST',
    body: JSON.stringify(beer),
  });
}

export async function removeFavorite(favoriteId: number): Promise<{ success: boolean }> {
  return apiFetch(`/recommendations/favorites/${favoriteId}/`, {
    method: 'DELETE',
  });
}

export async function getCartLink(): Promise<CartLinkResponse> {
  return apiFetch<CartLinkResponse>('/recommendations/favorites/cart/');
}

export async function getSelectedCartLink(favoriteIds: number[]): Promise<CartLinkResponse> {
  return apiFetch<CartLinkResponse>('/recommendations/favorites/cart/selected/', {
    method: 'POST',
    body: JSON.stringify({ favorite_ids: favoriteIds }),
  });
}
