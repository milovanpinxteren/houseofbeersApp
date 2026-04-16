import { apiFetch } from './client';

export interface LoyaltySummary {
  balance: number;
  lifetime_earned: number;
  lifetime_spent: number;
  pending_redemptions: number;
  available_rewards_count: number;
}

export interface PointsTransaction {
  id: number;
  transaction_type: string;
  transaction_type_display: string;
  points: number;
  balance_after: number;
  description: string;
  shopify_order_name: string;
  created_at: string;
}

export interface Reward {
  id: number;
  name: string;
  description: string;
  reward_type: string;
  reward_type_display: string;
  points_cost: number;
  discount_amount: string | null;
  discount_percentage: string | null;
  minimum_order_value: string | null;
  is_active: boolean;
  can_redeem: boolean;
}

export interface Redemption {
  id: number;
  reward: number;
  reward_name: string;
  points_spent: number;
  status: string;
  status_display: string;
  discount_code: string;
  discount_code_used: boolean;
  created_at: string;
  expires_at: string | null;
}

export interface RedeemResult {
  success: boolean;
  error?: string;
  redemption_id?: number;
  reward_name?: string;
  points_spent?: number;
  new_balance?: number;
  discount_code?: string;
  expires_at?: string;
}

export interface SyncResult {
  success: boolean;
  error?: string;
  points_awarded: number;
  orders_processed: number;
  orders_skipped: number;
  new_balance: number;
}

export async function getLoyaltySummary(): Promise<LoyaltySummary> {
  return apiFetch<LoyaltySummary>('/loyalty/summary/');
}

export async function getTransactions(): Promise<PointsTransaction[]> {
  const response = await apiFetch<{ transactions: PointsTransaction[] }>('/loyalty/transactions/');
  return response.transactions;
}

export async function getRewards(): Promise<Reward[]> {
  const response = await apiFetch<{ rewards: Reward[] }>('/loyalty/rewards/');
  return response.rewards;
}

export async function getRedemptions(): Promise<Redemption[]> {
  const response = await apiFetch<{ redemptions: Redemption[] }>('/loyalty/redemptions/');
  return response.redemptions;
}

export async function redeemReward(rewardId: number): Promise<RedeemResult> {
  return apiFetch<RedeemResult>('/loyalty/redeem/', {
    method: 'POST',
    body: JSON.stringify({ reward_id: rewardId }),
  });
}

export async function syncPoints(): Promise<SyncResult> {
  return apiFetch<SyncResult>('/loyalty/sync/', {
    method: 'POST',
  });
}
