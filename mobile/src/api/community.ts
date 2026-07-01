import { apiFetch } from './client';

// --- Types ---

export interface CommunityProfile {
  user_id: number;
  display_name: string;
  display_name_resolved: string;
  bio: string;
  is_visible: boolean;
  first_name: string;
  has_untappd: boolean;
  untappd_username: string | null;
  created_at: string;
  favorite_count?: number;
  checkin_count?: number;
}

export interface PostAuthor {
  user_id: number;
  display_name: string;
  first_name: string;
  has_untappd: boolean;
}

export interface Post {
  id: number;
  author: PostAuthor;
  post_type: 'review' | 'share' | 'text';
  content: string;
  beer_id: string;
  beer_title: string;
  beer_vendor: string;
  beer_image_url: string;
  beer_style: string;
  beer_rating: number | null;
  like_count: number;
  comment_count: number;
  is_liked: boolean;
  created_at: string;
}

export interface Comment {
  id: number;
  author: PostAuthor;
  content: string;
  parent_id: number | null;
  replies?: Comment[];
  created_at: string;
}

export interface ConversationSummary {
  id: number;
  other_user: PostAuthor;
  last_message: {
    content: string;
    sender_id: number;
    created_at: string;
    has_beer: boolean;
  } | null;
  unread_count: number;
  updated_at: string;
}

export interface Message {
  id: number;
  sender_id: number;
  content: string;
  beer_id: string;
  beer_title: string;
  beer_image_url: string;
  beer_style: string;
  is_read: boolean;
  created_at: string;
}

export interface CachedCheckin {
  beer_title: string;
  beer_vendor: string;
  beer_style: string;
  beer_abv: number | null;
  user_rating: number | null;
  checkin_date: string | null;
}

export interface PaginatedResponse<T> {
  results: T[];
  next: string | null;
  previous: string | null;
  count?: number;
}

export interface MemberFavorite {
  id: number;
  beer_id: string;
  title: string;
  vendor: string;
  price: string | null;
  image_url: string;
  untappd_rating: number | null;
  abv: number | null;
  style: string;
}

export interface MemberProfileResponse {
  profile: CommunityProfile;
  posts: Post[];
  checkins: CachedCheckin[];
  favorites: MemberFavorite[];
}

// --- Group Types ---

export interface Group {
  id: number;
  name: string;
  description: string;
  image_url: string;
  member_count: number;
  is_member: boolean;
  created_at: string;
}

export interface GroupDetail extends Group {
  members: GroupMember[];
}

export interface GroupMember {
  user_id: number;
  display_name: string;
  role: 'member' | 'admin';
  joined_at: string;
}

export interface GroupMessage {
  id: number;
  sender_id: number;
  sender_name: string;
  content: string;
  beer_id: string;
  beer_title: string;
  beer_image_url: string;
  beer_style: string;
  created_at: string;
}

export interface ChatItem {
  type: 'dm' | 'group';
  id: number;
  name: string;
  image_url: string | null;
  last_message: {
    content: string;
    sender_id: number;
    created_at: string;
    has_beer: boolean;
  } | null;
  unread_count: number;
  updated_at: string;
  other_user_id?: number | null;
  member_count?: number | null;
}

// --- Profile ---

export async function getMyProfile(): Promise<CommunityProfile> {
  return apiFetch<CommunityProfile>('/community/profile/');
}

export async function updateMyProfile(data: Partial<CommunityProfile>): Promise<CommunityProfile> {
  return apiFetch<CommunityProfile>('/community/profile/', {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

// --- Members ---

export async function getMembers(page = 1, search = ''): Promise<PaginatedResponse<CommunityProfile>> {
  const params = new URLSearchParams({ page: String(page) });
  if (search) params.set('search', search);
  return apiFetch<PaginatedResponse<CommunityProfile>>(`/community/members/?${params}`);
}

export async function getMemberProfile(userId: number): Promise<MemberProfileResponse> {
  return apiFetch<MemberProfileResponse>(`/community/members/${userId}/`);
}

// --- Feed ---

export async function getFeed(cursor?: string): Promise<PaginatedResponse<Post>> {
  if (cursor) {
    // DRF CursorPagination returns full URLs — extract the query string
    try {
      const parsed = new URL(cursor);
      return apiFetch<PaginatedResponse<Post>>(`/community/feed/${parsed.search}`);
    } catch {
      return apiFetch<PaginatedResponse<Post>>(`/community/feed/?cursor=${cursor}`);
    }
  }
  return apiFetch<PaginatedResponse<Post>>('/community/feed/');
}

export async function createPost(data: {
  post_type: string;
  content: string;
  beer_id?: string;
  beer_title?: string;
  beer_vendor?: string;
  beer_image_url?: string;
  beer_style?: string;
  beer_rating?: number;
}): Promise<Post> {
  return apiFetch<Post>('/community/posts/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function deletePost(postId: number): Promise<void> {
  await apiFetch(`/community/posts/${postId}/`, { method: 'DELETE' });
}

export async function toggleLike(postId: number): Promise<{ liked: boolean; like_count: number }> {
  return apiFetch(`/community/posts/${postId}/like/`, { method: 'POST' });
}

export async function getComments(postId: number): Promise<{ comments: Comment[] }> {
  return apiFetch(`/community/posts/${postId}/comments/`);
}

export async function addComment(postId: number, content: string, parentId?: number): Promise<Comment> {
  return apiFetch(`/community/posts/${postId}/comments/`, {
    method: 'POST',
    body: JSON.stringify({ content, ...(parentId ? { parent_id: parentId } : {}) }),
  });
}

export async function deleteComment(commentId: number): Promise<void> {
  await apiFetch(`/community/comments/${commentId}/`, { method: 'DELETE' });
}

// --- Conversations (DMs) ---

export async function getConversations(): Promise<{ conversations: ConversationSummary[] }> {
  return apiFetch('/community/conversations/');
}

export async function getOrCreateConversation(userId: number): Promise<ConversationSummary> {
  return apiFetch('/community/conversations/create/', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });
}

export async function getMessages(conversationId: number, page = 1): Promise<PaginatedResponse<Message>> {
  return apiFetch(`/community/conversations/${conversationId}/messages/?page=${page}`);
}

export async function sendMessage(conversationId: number, data: {
  content: string;
  beer_id?: string;
  beer_title?: string;
  beer_image_url?: string;
  beer_style?: string;
}): Promise<Message> {
  return apiFetch(`/community/conversations/${conversationId}/messages/send/`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function markConversationRead(conversationId: number): Promise<void> {
  await apiFetch(`/community/conversations/${conversationId}/read/`, { method: 'POST' });
}

export async function getUnreadCount(): Promise<{ unread_count: number }> {
  return apiFetch('/community/unread-count/');
}

// --- Groups ---

export async function getGroups(): Promise<{ groups: Group[] }> {
  return apiFetch('/community/groups/');
}

export async function getAvailableGroups(): Promise<{ groups: Group[] }> {
  return apiFetch('/community/groups/available/');
}

export async function getGroupDetail(groupId: number): Promise<GroupDetail> {
  return apiFetch(`/community/groups/${groupId}/`);
}

export async function joinGroup(groupId: number): Promise<void> {
  await apiFetch(`/community/groups/${groupId}/join/`, { method: 'POST' });
}

export async function leaveGroup(groupId: number): Promise<void> {
  await apiFetch(`/community/groups/${groupId}/leave/`, { method: 'POST' });
}

export async function getGroupMessages(groupId: number, page = 1): Promise<PaginatedResponse<GroupMessage>> {
  return apiFetch(`/community/groups/${groupId}/messages/?page=${page}`);
}

export async function sendGroupMessage(groupId: number, data: {
  content: string;
  beer_id?: string;
  beer_title?: string;
  beer_image_url?: string;
  beer_style?: string;
}): Promise<GroupMessage> {
  return apiFetch(`/community/groups/${groupId}/messages/send/`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

// --- Unified Chats ---

export async function getChats(): Promise<{ chats: ChatItem[] }> {
  return apiFetch('/community/chats/');
}

// --- Suggestions (Forum) ---

export interface Suggestion {
  id: number;
  author: PostAuthor;
  title: string;
  content: string;
  tag: string;
  status: 'open' | 'planned' | 'done' | 'declined';
  vote_count: number;
  comment_count: number;
  is_voted: boolean;
  created_at: string;
}

export interface SuggestionComment {
  id: number;
  author: PostAuthor;
  content: string;
  vote_count: number;
  is_voted: boolean;
  created_at: string;
}

export async function getSuggestions(page = 1, sort: 'top' | 'new' = 'top'): Promise<PaginatedResponse<Suggestion>> {
  return apiFetch(`/community/suggestions/?page=${page}&sort=${sort}`);
}

export async function createSuggestion(data: {
  title: string;
  content: string;
  tag?: string;
}): Promise<Suggestion> {
  return apiFetch('/community/suggestions/create/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function deleteSuggestion(id: number): Promise<void> {
  await apiFetch(`/community/suggestions/${id}/`, { method: 'DELETE' });
}

export async function toggleSuggestionVote(id: number): Promise<{ voted: boolean; vote_count: number }> {
  return apiFetch(`/community/suggestions/${id}/vote/`, { method: 'POST' });
}

export async function getSuggestionComments(id: number): Promise<{ comments: SuggestionComment[] }> {
  return apiFetch(`/community/suggestions/${id}/comments/`);
}

export async function addSuggestionComment(id: number, content: string): Promise<SuggestionComment> {
  return apiFetch(`/community/suggestions/${id}/comments/`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}

export async function deleteSuggestionComment(commentId: number): Promise<void> {
  await apiFetch(`/community/suggestions/comments/${commentId}/`, { method: 'DELETE' });
}

export async function toggleSuggestionCommentVote(commentId: number): Promise<{ voted: boolean; vote_count: number }> {
  return apiFetch(`/community/suggestions/comments/${commentId}/vote/`, { method: 'POST' });
}
