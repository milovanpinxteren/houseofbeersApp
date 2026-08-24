import { apiFetch } from './client';

// Shapes produced by serialize_campaign in backend/loyalty/serializers.py.

export type CampaignActionType = 'points' | 'discount_code';

export interface AppCampaign {
  id: number;
  name: string;
  rule_sentence: string;
  action_type: CampaignActionType;
  status: string;
  window_start: string;
  window_end: string;
  qualified: boolean;
  qualified_at: string | null;
  points_awarded: number;
  discount_code: string | null;
  discount_expires_at: string | null;
}

export async function getCampaigns(): Promise<{ campaigns: AppCampaign[] }> {
  return apiFetch<{ campaigns: AppCampaign[] }>('/loyalty/campaigns/');
}
