import { apiFetch } from './client';
import { PostAuthor } from './community';

// --- Types ---

export interface Event {
  id: number;
  title: string;
  description: string;
  event_type: 'livestream' | 'auction' | 'tasting' | 'release_review' | 'sale';
  scheduled_at: string;
  youtube_url: string;
  image_url: string;
  status: 'scheduled' | 'live' | 'ended';
  viewer_count: number;
  is_joined: boolean;
  active_viewer_count?: number;
  created_at: string;
}

export interface EventMessage {
  id: number;
  user: PostAuthor;
  message: string;
  is_system: boolean;
  created_at: string;
}

export interface RaffleWinner {
  id: number;
  prize_name: string;
  user: PostAuthor;
  drawn_at: string;
}

export interface AuctionItem {
  id: number;
  title: string;
  image_url: string;
  starting_price: string;
  final_price: string | null;
  winner_name: string | null;
  status: 'pending' | 'active' | 'sold';
  created_at: string;
}

// --- API Functions ---

export async function getEvents(status?: string): Promise<{ events: Event[] }> {
  const params = status ? `?status=${status}` : '';
  return apiFetch(`/events/${params}`);
}

export async function getEvent(eventId: number): Promise<Event> {
  return apiFetch(`/events/${eventId}/`);
}

export async function joinEvent(eventId: number): Promise<{ success: boolean; viewer_count: number }> {
  return apiFetch(`/events/${eventId}/join/`, { method: 'POST' });
}

export async function getEventChat(
  eventId: number,
  after?: string
): Promise<{ messages: EventMessage[]; active_viewer_count: number }> {
  const params = after ? `?after=${encodeURIComponent(after)}` : '';
  return apiFetch(`/events/${eventId}/chat/${params}`);
}

export async function sendEventMessage(
  eventId: number,
  message: string
): Promise<EventMessage> {
  return apiFetch(`/events/${eventId}/chat/`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  });
}

export async function getEventWinners(
  eventId: number
): Promise<{ winners: RaffleWinner[] }> {
  return apiFetch(`/events/${eventId}/raffle/winners/`);
}

export async function getActiveAuctionItem(
  eventId: number
): Promise<{ item: AuctionItem | null }> {
  return apiFetch(`/events/${eventId}/auction/active/`);
}

export async function getAuctionHistory(
  eventId: number
): Promise<{ items: AuctionItem[] }> {
  return apiFetch(`/events/${eventId}/auction/history/`);
}
