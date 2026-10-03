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
  // Omitted by the serializer when empty
  reactions?: Record<string, number>;
  mine?: string[];
}

export interface RaffleWinner {
  id: number;
  raffle_id: number;
  prize_name: string;
  user: PostAuthor;
  drawn_at: string;
}

export interface AuctionItem {
  id: number;
  title: string;
  description: string;
  brewery: string;
  size: string;
  untappd_rating: string | null;
  image_url: string;
  starting_price: string;
  min_increment: number;
  current_bid: number | null;
  bid_count: number;
  leader_name: string | null;
  final_price: string | null;
  winner_name: string | null;
  status: 'pending' | 'active' | 'sold';
  created_at: string;
}

export interface EventViewerName {
  display_name: string;
}

// Live event fields the poll always carries so a corrected stream URL or
// status flip reaches viewers who already have the screen open.
export interface PollEventInfo {
  status: Event['status'];
  youtube_url: string;
}

// Reaction digest entry: snapshot of one message's reactions. Within the
// window the client requested, a held message ABSENT from the digest has
// zero reactions (that's how un-reacts propagate).
export interface ReactionUpdate {
  m: number;
  r: Record<string, number>;
  mine: string[];
}

export interface PollResponse {
  messages: EventMessage[];
  winner_count: number;
  reaction_rev: number;
  reaction_updates?: ReactionUpdate[];
  event?: PollEventInfo;
  active_viewer_count?: number;
  winners?: RaffleWinner[];
  viewer_names?: EventViewerName[];
  auction_item?: AuctionItem | null;
}

export interface BidResponse {
  ok: boolean;
  current_bid: number;
  leader_name: string;
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

export async function pollEvent(
  eventId: number,
  after?: string,
  heartbeat?: boolean,
  knownWinnerCount?: number,
  knownReactionRev?: number,
  oldestMessageId?: number,
): Promise<PollResponse> {
  const params = new URLSearchParams();
  if (after) params.set('after', after);
  if (heartbeat) params.set('heartbeat', '1');
  if (knownWinnerCount !== undefined) params.set('known_winner_count', String(knownWinnerCount));
  if (knownReactionRev !== undefined) params.set('known_reaction_rev', String(knownReactionRev));
  if (oldestMessageId !== undefined) params.set('oldest_message_id', String(oldestMessageId));
  const query = params.toString();
  return apiFetch(`/events/${eventId}/poll/${query ? `?${query}` : ''}`);
}

export interface EventReactionResponse {
  reacted: boolean;
  reactions: Record<string, number>;
  mine: string[];
}

export async function reactEventMessage(
  eventId: number,
  messageId: number,
  emoji: string
): Promise<EventReactionResponse> {
  return apiFetch(`/events/${eventId}/chat/${messageId}/react/`, {
    method: 'POST',
    body: JSON.stringify({ emoji }),
  });
}

export async function getEventViewers(
  eventId: number
): Promise<{ viewers: EventViewerName[] }> {
  return apiFetch(`/events/${eventId}/viewers/`);
}

export async function placeBid(
  eventId: number,
  amount: number
): Promise<BidResponse> {
  return apiFetch(`/events/${eventId}/auction/bid/`, {
    method: 'POST',
    body: JSON.stringify({ amount }),
  });
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
