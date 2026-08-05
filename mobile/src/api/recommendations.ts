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
  profile_summary: ProfileSummary | null;
  recommendations: ScoredBeer[];
  discovery_picks: ScoredBeer[];
  tried_beers: ScoredBeer[];
  profile_source: 'untappd' | 'shopify';
  profile_identifier: string;
  message?: string;
}

// Returned when the recommender is still building the user's taste profile.
// The client should poll getRecommendationStatus(task_id) and then refetch.
export interface PendingRecommendationsResponse {
  status: 'pending';
  task_id: string;
  profile_source: 'untappd' | 'shopify';
  profile_identifier: string;
}

export type RecommendationsResult = RecommendationsResponse | PendingRecommendationsResponse;

export function isPendingRecommendations(
  result: RecommendationsResult
): result is PendingRecommendationsResponse {
  return 'status' in result && result.status === 'pending';
}

export interface RecommendationStatusResponse {
  status: 'pending' | 'completed' | 'failed';
  result?: RecommendationsResponse;
  error?: string;
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
  username?: string;
  total_checkins: number;
  unique_beers: number;
  radar_chart: RadarChartData | null;
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
  } | null;
  rating_profile: {
    average: number;
    category: string;
  } | null;
  top_breweries: Array<{
    brewery: string;
    count: number;
    avg_rating: number;
  }>;
  profile_source: 'untappd' | 'shopify';
  profile_identifier: string;
  message?: string;
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

export interface RandomBeer {
  id: number;
  title: string;
  product_type: string;
  tags: string[];
  price: string | null;
  image_url: string;
  handle: string;
  shop_url: string;
}

export interface RandomBeerResponse {
  found: boolean;
  beer?: RandomBeer;
  styles: string[];
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
}): Promise<RecommendationsResult> {
  const queryParams = new URLSearchParams();
  if (params?.limit && params.limit > 0) {
    queryParams.set('limit', params.limit.toString());
  }
  if (params?.price_max && params.price_max > 0) {
    queryParams.set('price_max', params.price_max.toFixed(2));
  }
  if (params?.style_filter) {
    queryParams.set('style_filter', params.style_filter);
  }

  const query = queryParams.toString();
  const endpoint = '/recommendations/' + (query ? '?' + query : '');

  return apiFetch<RecommendationsResult>(endpoint);
}

export async function getRecommendationStatus(
  taskId: string
): Promise<RecommendationStatusResponse> {
  return apiFetch<RecommendationStatusResponse>(
    `/recommendations/status/${encodeURIComponent(taskId)}/`
  );
}

export async function getTasteProfile(): Promise<TasteProfileResponse> {
  return apiFetch<TasteProfileResponse>('/recommendations/profile/');
}

export async function getStyles(): Promise<{ styles: StyleOption[] }> {
  return apiFetch<{ styles: StyleOption[] }>('/recommendations/styles/');
}

export async function getRandomBeer(params?: {
  style?: string;
  max_price?: number;
}): Promise<RandomBeerResponse> {
  const queryParams = new URLSearchParams();
  if (params?.style) {
    queryParams.set('style', params.style);
  }
  if (params?.max_price && params.max_price > 0) {
    queryParams.set('max_price', params.max_price.toFixed(2));
  }

  const query = queryParams.toString();
  return apiFetch<RandomBeerResponse>(
    '/recommendations/random-beer/' + (query ? '?' + query : '')
  );
}

// Lightweight prefetch of the style filter chips — no beer is picked.
export async function getRandomBeerStyles(): Promise<{ styles: string[] }> {
  return apiFetch<{ styles: string[] }>('/recommendations/random-beer/?styles_only=1');
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
