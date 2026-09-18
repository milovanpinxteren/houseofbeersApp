import { apiFetch } from './client';

// Pickup RSVP — members with pickup orders announce which store day they're
// coming (store: Prior van Millstraat 2, Uden; Fri 10:00–20:00, Sat 10:00–17:00).

export interface PickupDay {
  /** ISO date, e.g. '2026-09-25'. */
  date: string;
  /** 'HH:MM' */
  open_time: string;
  /** 'HH:MM' */
  close_time: string;
  /** Whether the current user has announced they're coming this day. */
  rsvp: boolean;
}

export interface PickupRsvpResult {
  date: string;
  rsvp: boolean;
}

/** The next ~2 weekends of open pickup days. */
export async function getPickupDays(): Promise<{ days: PickupDay[] }> {
  return apiFetch<{ days: PickupDay[] }>('/pickup/days/');
}

/** Announce you're coming on `date`. Returns `{ date, rsvp: true }`. */
export async function rsvpPickup(date: string): Promise<PickupRsvpResult> {
  return apiFetch<PickupRsvpResult>('/pickup/rsvp/', {
    method: 'POST',
    body: JSON.stringify({ date }),
  });
}

/** Withdraw an RSVP for `date`. Returns `{ date, rsvp: false }`. */
export async function cancelPickupRsvp(date: string): Promise<PickupRsvpResult> {
  return apiFetch<PickupRsvpResult>('/pickup/rsvp/cancel/', {
    method: 'POST',
    body: JSON.stringify({ date }),
  });
}
