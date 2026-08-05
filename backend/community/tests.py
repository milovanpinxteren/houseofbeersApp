from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from .models import (
    CachedBeerCheckin, Conversation, Group, GroupMembership, GroupMessage,
    Message, Post, PostComment, Suggestion, SuggestionComment, SuggestionVote,
)

User = get_user_model()


def make_user(tag, visible=True, display_name=''):
    """Create a user; the post_save signal auto-creates a CommunityProfile."""
    user = User.objects.create_user(
        username=f'user_{tag}',
        email=f'{tag}@example.com',
        password='test-pass-123',
        first_name=tag.capitalize(),
    )
    profile = user.community_profile
    if not visible or display_name:
        profile.is_visible = visible
        profile.display_name = display_name
        profile.save()
    return user


def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def make_staff(tag):
    user = make_user(tag)
    user.is_staff = True
    user.save(update_fields=['is_staff'])
    return user


class MessageOrderingTests(APITestCase):
    """Page 1 must return the NEWEST 30 messages (the pre-fix behavior returned
    the oldest 30, freezing chats past 30 messages)."""

    def setUp(self):
        self.a = make_user('alice')
        self.b = make_user('bob')
        self.client = auth_client(self.a)

    def _spread_timestamps(self, model, objs):
        """Give each message a distinct, increasing created_at (auto_now_add
        can collide within one test run)."""
        base = timezone.now() - timedelta(hours=1)
        for i, obj in enumerate(objs):
            model.objects.filter(id=obj.id).update(created_at=base + timedelta(seconds=i))

    def test_dm_messages_page1_is_newest_30(self):
        conv, _ = Conversation.objects.get_or_create_between(self.a, self.b)
        msgs = [
            Message.objects.create(conversation=conv, sender=self.a, content=f'msg-{i}')
            for i in range(1, 36)
        ]
        self._spread_timestamps(Message, msgs)

        page1 = self.client.get(f'/api/community/conversations/{conv.id}/messages/')
        self.assertEqual(page1.status_code, 200)
        results = page1.data['results']
        self.assertEqual(len(results), 30)
        self.assertEqual(results[0]['content'], 'msg-35')  # newest first
        self.assertEqual(results[-1]['content'], 'msg-6')

        page2 = self.client.get(f'/api/community/conversations/{conv.id}/messages/?page=2')
        self.assertEqual(page2.status_code, 200)
        self.assertEqual(
            [m['content'] for m in page2.data['results']],
            ['msg-5', 'msg-4', 'msg-3', 'msg-2', 'msg-1'],
        )

    def test_group_messages_page1_is_newest_30(self):
        group = Group.objects.create(name='Stout Lovers')
        GroupMembership.objects.create(group=group, user=self.a)
        msgs = [
            GroupMessage.objects.create(group=group, sender=self.a, content=f'gmsg-{i}')
            for i in range(1, 36)
        ]
        self._spread_timestamps(GroupMessage, msgs)

        page1 = self.client.get(f'/api/community/groups/{group.id}/messages/')
        self.assertEqual(page1.status_code, 200)
        results = page1.data['results']
        self.assertEqual(len(results), 30)
        self.assertEqual(results[0]['content'], 'gmsg-35')
        self.assertEqual(results[-1]['content'], 'gmsg-6')

        page2 = self.client.get(f'/api/community/groups/{group.id}/messages/?page=2')
        self.assertEqual(
            [m['content'] for m in page2.data['results']],
            ['gmsg-5', 'gmsg-4', 'gmsg-3', 'gmsg-2', 'gmsg-1'],
        )


class MessageDeleteTests(APITestCase):
    def setUp(self):
        self.a = make_user('alice')
        self.b = make_user('bob')
        self.outsider = make_user('carol')
        self.conv, _ = Conversation.objects.get_or_create_between(self.a, self.b)
        self.group = Group.objects.create(name='IPA Fans')
        GroupMembership.objects.create(group=self.group, user=self.a)
        GroupMembership.objects.create(group=self.group, user=self.b)

    def test_delete_own_dm_message(self):
        msg = Message.objects.create(conversation=self.conv, sender=self.a, content='mine')
        resp = auth_client(self.a).delete(
            f'/api/community/conversations/{self.conv.id}/messages/{msg.id}/'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Message.objects.filter(id=msg.id).exists())

    def test_cannot_delete_other_users_dm_message(self):
        msg = Message.objects.create(conversation=self.conv, sender=self.b, content='bobs')
        resp = auth_client(self.a).delete(
            f'/api/community/conversations/{self.conv.id}/messages/{msg.id}/'
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Message.objects.filter(id=msg.id).exists())

    def test_non_participant_gets_404_for_dm_message(self):
        msg = Message.objects.create(conversation=self.conv, sender=self.a, content='hi')
        resp = auth_client(self.outsider).delete(
            f'/api/community/conversations/{self.conv.id}/messages/{msg.id}/'
        )
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Message.objects.filter(id=msg.id).exists())

    def test_delete_own_group_message(self):
        msg = GroupMessage.objects.create(group=self.group, sender=self.a, content='mine')
        resp = auth_client(self.a).delete(
            f'/api/community/groups/{self.group.id}/messages/{msg.id}/'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(GroupMessage.objects.filter(id=msg.id).exists())

    def test_cannot_delete_other_members_group_message(self):
        msg = GroupMessage.objects.create(group=self.group, sender=self.b, content='bobs')
        resp = auth_client(self.a).delete(
            f'/api/community/groups/{self.group.id}/messages/{msg.id}/'
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(GroupMessage.objects.filter(id=msg.id).exists())

    def test_non_member_cannot_delete_group_message(self):
        msg = GroupMessage.objects.create(group=self.group, sender=self.a, content='hi')
        resp = auth_client(self.outsider).delete(
            f'/api/community/groups/{self.group.id}/messages/{msg.id}/'
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(GroupMessage.objects.filter(id=msg.id).exists())


class GroupUnreadCountTests(APITestCase):
    def setUp(self):
        self.a = make_user('alice')
        self.b = make_user('bob')
        self.group = Group.objects.create(name='Lambic Lounge')
        GroupMembership.objects.create(group=self.group, user=self.a)
        GroupMembership.objects.create(group=self.group, user=self.b)
        # auto_now_add timestamps can collide on coarse clocks (Windows ~1ms),
        # so make join-before-message ordering explicit.
        GroupMembership.objects.update(joined_at=timezone.now() - timedelta(minutes=10))
        base = timezone.now() - timedelta(minutes=5)
        for i in range(3):
            msg = GroupMessage.objects.create(group=self.group, sender=self.a, content=f'm{i}')
            GroupMessage.objects.filter(id=msg.id).update(created_at=base + timedelta(seconds=i))

    def _group_chat(self, user):
        resp = auth_client(user).get('/api/community/chats/')
        self.assertEqual(resp.status_code, 200)
        groups = [c for c in resp.data['chats'] if c['type'] == 'group']
        self.assertEqual(len(groups), 1)
        return groups[0]

    def test_never_read_member_counts_since_joined(self):
        # B has last_read_at=None → falls back to joined_at → all 3 unread
        self.assertIsNone(GroupMembership.objects.get(user=self.b).last_read_at)
        self.assertEqual(self._group_chat(self.b)['unread_count'], 3)

    def test_own_messages_never_count_as_unread(self):
        self.assertEqual(self._group_chat(self.a)['unread_count'], 0)

    def test_mark_read_resets_unread(self):
        resp = auth_client(self.b).post(f'/api/community/groups/{self.group.id}/read/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(GroupMembership.objects.get(user=self.b).last_read_at)
        self.assertEqual(self._group_chat(self.b)['unread_count'], 0)

        # A new message after reading becomes unread again (created_at pushed
        # past last_read_at so a coarse clock cannot make them collide)
        msg = GroupMessage.objects.create(group=self.group, sender=self.a, content='new')
        GroupMessage.objects.filter(id=msg.id).update(
            created_at=timezone.now() + timedelta(seconds=10),
        )
        self.assertEqual(self._group_chat(self.b)['unread_count'], 1)

    def test_messages_before_join_do_not_count(self):
        late = make_user('dave')
        GroupMembership.objects.create(group=self.group, user=late)  # joins after the 3 messages
        self.assertEqual(self._group_chat(late)['unread_count'], 0)

    def test_mark_read_requires_membership(self):
        outsider = make_user('carol')
        resp = auth_client(outsider).post(f'/api/community/groups/{self.group.id}/read/')
        self.assertEqual(resp.status_code, 403)


class CheckinPrivacyTests(APITestCase):
    def setUp(self):
        self.viewer = make_user('viewer')
        self.hidden = make_user('hidden', visible=False)
        self.visible = make_user('shown')
        for user in (self.hidden, self.visible):
            CachedBeerCheckin.objects.create(user=user, beer_title='Westvleteren 12')
        self.client = auth_client(self.viewer)

    def test_hidden_user_checkins_404(self):
        resp = self.client.get(f'/api/community/members/{self.hidden.id}/checkins/')
        self.assertEqual(resp.status_code, 404)

    def test_visible_user_checkins_200(self):
        resp = self.client.get(f'/api/community/members/{self.visible.id}/checkins/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['checkins']), 1)
        self.assertEqual(resp.data['checkins'][0]['beer_title'], 'Westvleteren 12')


class MemberSearchPrivacyTests(APITestCase):
    def setUp(self):
        self.viewer = make_user('viewer')
        # Email contains a unique token that appears nowhere in the names
        self.target = User.objects.create_user(
            username='user_target',
            email='zq7xtoken@example.com',
            password='test-pass-123',
            first_name='Frank',
        )
        profile = self.target.community_profile
        profile.display_name = 'HopHead'
        profile.save()
        self.client = auth_client(self.viewer)

    def _search_ids(self, term):
        resp = self.client.get(f'/api/community/members/?search={term}')
        self.assertEqual(resp.status_code, 200)
        return [m['user_id'] for m in resp.data['results']]

    def test_search_does_not_match_email(self):
        self.assertNotIn(self.target.id, self._search_ids('zq7xtoken'))

    def test_search_matches_display_name(self):
        self.assertIn(self.target.id, self._search_ids('HopHead'))

    def test_search_matches_first_name(self):
        self.assertIn(self.target.id, self._search_ids('Frank'))


class ConversationCreateTests(APITestCase):
    def setUp(self):
        self.a = make_user('alice')
        self.hidden = make_user('hidden', visible=False)
        self.visible = make_user('bob')
        self.client = auth_client(self.a)

    def test_non_int_user_id_is_400_not_500(self):
        resp = self.client.post('/api/community/conversations/create/', {'user_id': 'abc'})
        self.assertEqual(resp.status_code, 400)

    def test_missing_user_id_is_400(self):
        resp = self.client.post('/api/community/conversations/create/', {})
        self.assertEqual(resp.status_code, 400)

    def test_hidden_user_is_404(self):
        resp = self.client.post(
            '/api/community/conversations/create/', {'user_id': self.hidden.id},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Conversation.objects.count(), 0)

    def test_visible_user_creates_conversation(self):
        resp = self.client.post(
            '/api/community/conversations/create/', {'user_id': self.visible.id},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(resp.data['other_user']['user_id'], self.visible.id)


class SuggestionDetailTests(APITestCase):
    def setUp(self):
        self.a = make_user('alice')
        self.b = make_user('bob')
        self.suggestion = Suggestion.objects.create(
            author=self.a, title='More sours', content='Please stock more sours',
        )
        SuggestionVote.objects.create(suggestion=self.suggestion, user=self.b)
        SuggestionComment.objects.create(
            suggestion=self.suggestion, author=self.b, content='Yes please',
        )

    def test_detail_returns_annotated_suggestion(self):
        resp = auth_client(self.b).get(
            f'/api/community/suggestions/{self.suggestion.id}/detail/'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['id'], self.suggestion.id)
        self.assertEqual(resp.data['title'], 'More sours')
        self.assertEqual(resp.data['vote_count'], 1)
        self.assertEqual(resp.data['comment_count'], 1)
        self.assertTrue(resp.data['is_voted'])  # B voted

    def test_detail_is_voted_false_for_non_voter(self):
        resp = auth_client(self.a).get(
            f'/api/community/suggestions/{self.suggestion.id}/detail/'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['is_voted'])

    def test_unknown_id_is_404(self):
        resp = auth_client(self.a).get('/api/community/suggestions/999999/detail/')
        self.assertEqual(resp.status_code, 404)


class GroupJoinIdempotencyTests(APITestCase):
    def setUp(self):
        self.a = make_user('alice')
        self.group = Group.objects.create(name='Quadrupel Quorum')
        self.client = auth_client(self.a)

    def test_joining_twice_succeeds_with_one_membership(self):
        first = self.client.post(f'/api/community/groups/{self.group.id}/join/')
        self.assertIn(first.status_code, (200, 201))

        second = self.client.post(f'/api/community/groups/{self.group.id}/join/')
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data.get('success'))

        self.assertEqual(
            GroupMembership.objects.filter(group=self.group, user=self.a).count(), 1,
        )


class PostValidationTests(APITestCase):
    def setUp(self):
        self.a = make_user('alice')
        self.client = auth_client(self.a)

    def test_beer_rating_above_5_rejected(self):
        resp = self.client.post('/api/community/posts/', {
            'post_type': 'review', 'content': 'Amazing', 'beer_rating': '9.99',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Post.objects.count(), 0)

    def test_beer_rating_valid_accepted(self):
        resp = self.client.post('/api/community/posts/', {
            'post_type': 'review', 'content': 'Amazing', 'beer_rating': '4.5',
        })
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(float(Post.objects.get().beer_rating), 4.5)


class CommentsNotFoundTests(APITestCase):
    def setUp(self):
        self.a = make_user('alice')
        self.client = auth_client(self.a)

    def test_comments_on_nonexistent_post_404(self):
        resp = self.client.get('/api/community/posts/999999/comments/')
        self.assertEqual(resp.status_code, 404)

    def test_comments_on_nonexistent_suggestion_404(self):
        resp = self.client.get('/api/community/suggestions/999999/comments/')
        self.assertEqual(resp.status_code, 404)

    def test_comments_on_existing_post_200(self):
        post = Post.objects.create(author=self.a, content='hello')
        resp = self.client.get(f'/api/community/posts/{post.id}/comments/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['comments'], [])


class StaffModerationTests(APITestCase):
    """Staff (is_staff) may delete ALL community content; regular users only their own."""

    def setUp(self):
        self.author = make_user('alice')
        self.other = make_user('bob')
        self.staff = make_staff('moderator')
        self.post = Post.objects.create(author=self.author, content='my post')
        self.comment = PostComment.objects.create(
            post=self.post, author=self.author, content='my comment',
        )
        self.suggestion = Suggestion.objects.create(
            author=self.author, title='More stouts', content='Please',
        )
        self.sugg_comment = SuggestionComment.objects.create(
            suggestion=self.suggestion, author=self.author, content='agree',
        )
        self.conv, _ = Conversation.objects.get_or_create_between(self.author, self.other)
        self.dm = Message.objects.create(conversation=self.conv, sender=self.author, content='hi')
        self.group = Group.objects.create(name='Tripel Trouble')
        GroupMembership.objects.create(group=self.group, user=self.author)
        self.gmsg = GroupMessage.objects.create(group=self.group, sender=self.author, content='hi')

    # --- Staff can delete others' content ---

    def test_staff_can_delete_others_post(self):
        resp = auth_client(self.staff).delete(f'/api/community/posts/{self.post.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Post.objects.filter(id=self.post.id).exists())

    def test_staff_can_delete_others_comment(self):
        resp = auth_client(self.staff).delete(f'/api/community/comments/{self.comment.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(PostComment.objects.filter(id=self.comment.id).exists())

    def test_staff_can_delete_dm_message_without_being_participant(self):
        resp = auth_client(self.staff).delete(
            f'/api/community/conversations/{self.conv.id}/messages/{self.dm.id}/'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Message.objects.filter(id=self.dm.id).exists())

    def test_staff_can_delete_group_message_without_being_member(self):
        resp = auth_client(self.staff).delete(
            f'/api/community/groups/{self.group.id}/messages/{self.gmsg.id}/'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(GroupMessage.objects.filter(id=self.gmsg.id).exists())

    def test_staff_can_delete_others_suggestion(self):
        resp = auth_client(self.staff).delete(f'/api/community/suggestions/{self.suggestion.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Suggestion.objects.filter(id=self.suggestion.id).exists())

    def test_staff_can_delete_others_suggestion_comment(self):
        resp = auth_client(self.staff).delete(
            f'/api/community/suggestions/comments/{self.sugg_comment.id}/'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(SuggestionComment.objects.filter(id=self.sugg_comment.id).exists())

    # --- Regular users cannot delete others' content (403, object survives) ---

    def test_non_staff_cannot_delete_others_post(self):
        resp = auth_client(self.other).delete(f'/api/community/posts/{self.post.id}/')
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Post.objects.filter(id=self.post.id).exists())

    def test_non_staff_cannot_delete_others_comment(self):
        resp = auth_client(self.other).delete(f'/api/community/comments/{self.comment.id}/')
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(PostComment.objects.filter(id=self.comment.id).exists())

    def test_non_staff_cannot_delete_others_dm_message(self):
        resp = auth_client(self.other).delete(
            f'/api/community/conversations/{self.conv.id}/messages/{self.dm.id}/'
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Message.objects.filter(id=self.dm.id).exists())

    def test_non_staff_cannot_delete_others_suggestion(self):
        resp = auth_client(self.other).delete(f'/api/community/suggestions/{self.suggestion.id}/')
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Suggestion.objects.filter(id=self.suggestion.id).exists())

    def test_delete_nonexistent_post_is_404(self):
        resp = auth_client(self.staff).delete('/api/community/posts/999999/')
        self.assertEqual(resp.status_code, 404)

    def test_me_endpoint_exposes_is_staff(self):
        resp = auth_client(self.staff).get('/api/users/me/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['is_staff'])

        resp = auth_client(self.other).get('/api/users/me/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['is_staff'])


class EditEndpointTests(APITestCase):
    """PATCH edit endpoints: author or staff, edited_at gets set, others get 403."""

    def setUp(self):
        self.author = make_user('alice')
        self.other = make_user('bob')
        self.staff = make_staff('moderator')
        self.post = Post.objects.create(author=self.author, content='original')
        self.comment = PostComment.objects.create(
            post=self.post, author=self.author, content='original comment',
        )
        self.suggestion = Suggestion.objects.create(
            author=self.author, title='Old title', content='Old content',
        )
        self.sugg_comment = SuggestionComment.objects.create(
            suggestion=self.suggestion, author=self.author, content='original',
        )

    def test_author_can_edit_own_post(self):
        resp = auth_client(self.author).patch(
            f'/api/community/posts/{self.post.id}/', {'content': 'updated'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['content'], 'updated')
        self.assertIsNotNone(resp.data['edited_at'])
        self.post.refresh_from_db()
        self.assertEqual(self.post.content, 'updated')
        self.assertIsNotNone(self.post.edited_at)

    def test_staff_can_edit_others_post(self):
        resp = auth_client(self.staff).patch(
            f'/api/community/posts/{self.post.id}/', {'content': 'moderated'},
        )
        self.assertEqual(resp.status_code, 200)
        self.post.refresh_from_db()
        self.assertEqual(self.post.content, 'moderated')

    def test_non_author_non_staff_cannot_edit_post(self):
        resp = auth_client(self.other).patch(
            f'/api/community/posts/{self.post.id}/', {'content': 'hacked'},
        )
        self.assertEqual(resp.status_code, 403)
        self.post.refresh_from_db()
        self.assertEqual(self.post.content, 'original')
        self.assertIsNone(self.post.edited_at)

    def test_edit_post_empty_content_is_400(self):
        resp = auth_client(self.author).patch(
            f'/api/community/posts/{self.post.id}/', {'content': '   '},
        )
        self.assertEqual(resp.status_code, 400)

    def test_edit_post_too_long_is_400(self):
        resp = auth_client(self.author).patch(
            f'/api/community/posts/{self.post.id}/', {'content': 'x' * 1001},
        )
        self.assertEqual(resp.status_code, 400)

    def test_edit_nonexistent_post_is_404(self):
        resp = auth_client(self.author).patch(
            '/api/community/posts/999999/', {'content': 'x'},
        )
        self.assertEqual(resp.status_code, 404)

    def test_author_can_edit_own_comment_sets_edited_at(self):
        resp = auth_client(self.author).patch(
            f'/api/community/comments/{self.comment.id}/', {'content': 'edited comment'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['content'], 'edited comment')
        self.assertIsNotNone(resp.data['edited_at'])

    def test_non_author_cannot_edit_comment(self):
        resp = auth_client(self.other).patch(
            f'/api/community/comments/{self.comment.id}/', {'content': 'nope'},
        )
        self.assertEqual(resp.status_code, 403)

    def test_edit_comment_truncates_at_500(self):
        resp = auth_client(self.author).patch(
            f'/api/community/comments/{self.comment.id}/', {'content': 'y' * 600},
        )
        self.assertEqual(resp.status_code, 200)
        self.comment.refresh_from_db()
        self.assertEqual(len(self.comment.content), 500)

    def test_author_can_edit_suggestion_title_and_content(self):
        resp = auth_client(self.author).patch(
            f'/api/community/suggestions/{self.suggestion.id}/',
            {'title': 'New title', 'content': 'New content'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['title'], 'New title')
        self.assertEqual(resp.data['content'], 'New content')
        self.assertIsNotNone(resp.data['edited_at'])

    def test_edit_suggestion_title_only(self):
        resp = auth_client(self.author).patch(
            f'/api/community/suggestions/{self.suggestion.id}/', {'title': 'Only title'},
        )
        self.assertEqual(resp.status_code, 200)
        self.suggestion.refresh_from_db()
        self.assertEqual(self.suggestion.title, 'Only title')
        self.assertEqual(self.suggestion.content, 'Old content')

    def test_edit_suggestion_without_fields_is_400(self):
        resp = auth_client(self.author).patch(
            f'/api/community/suggestions/{self.suggestion.id}/', {},
        )
        self.assertEqual(resp.status_code, 400)

    def test_staff_can_edit_others_suggestion(self):
        resp = auth_client(self.staff).patch(
            f'/api/community/suggestions/{self.suggestion.id}/', {'content': 'moderated'},
        )
        self.assertEqual(resp.status_code, 200)

    def test_non_author_cannot_edit_suggestion(self):
        resp = auth_client(self.other).patch(
            f'/api/community/suggestions/{self.suggestion.id}/', {'content': 'nope'},
        )
        self.assertEqual(resp.status_code, 403)

    def test_author_can_edit_suggestion_comment(self):
        resp = auth_client(self.author).patch(
            f'/api/community/suggestions/comments/{self.sugg_comment.id}/',
            {'content': 'edited'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['content'], 'edited')
        self.assertIsNotNone(resp.data['edited_at'])

    def test_non_author_cannot_edit_suggestion_comment(self):
        resp = auth_client(self.other).patch(
            f'/api/community/suggestions/comments/{self.sugg_comment.id}/',
            {'content': 'nope'},
        )
        self.assertEqual(resp.status_code, 403)

    def test_chat_messages_have_no_edit_endpoint(self):
        conv, _ = Conversation.objects.get_or_create_between(self.author, self.other)
        msg = Message.objects.create(conversation=conv, sender=self.author, content='hi')
        resp = auth_client(self.author).patch(
            f'/api/community/conversations/{conv.id}/messages/{msg.id}/', {'content': 'x'},
        )
        self.assertEqual(resp.status_code, 405)

        group = Group.objects.create(name='No Edit Club')
        GroupMembership.objects.create(group=group, user=self.author)
        gmsg = GroupMessage.objects.create(group=group, sender=self.author, content='hi')
        resp = auth_client(self.author).patch(
            f'/api/community/groups/{group.id}/messages/{gmsg.id}/', {'content': 'x'},
        )
        self.assertEqual(resp.status_code, 405)


class QueryCountRegressionTests(APITestCase):
    """The query count of the list endpoints must not scale with row count —
    this is the guard for the N+1 fixes at ~1000 users."""

    def setUp(self):
        self.user = make_user('main')

    def _seed_conversations_and_group(self, tag, n_conversations):
        for i in range(n_conversations):
            other = make_user(f'{tag}peer{i}')
            conv, _ = Conversation.objects.get_or_create_between(self.user, other)
            Message.objects.create(conversation=conv, sender=other, content=f'hi {i}')
        group = Group.objects.create(name=f'Group {tag}')
        GroupMembership.objects.create(group=group, user=self.user)
        other = make_user(f'{tag}gsender')
        GroupMembership.objects.create(group=group, user=other)
        GroupMessage.objects.create(group=group, sender=other, content='hello group')

    def _count_queries(self, path):
        client = auth_client(self.user)
        with CaptureQueriesContext(connection) as ctx:
            resp = client.get(path)
        self.assertEqual(resp.status_code, 200)
        return len(ctx), resp

    def test_chats_query_count_is_constant(self):
        self._seed_conversations_and_group('a', 5)
        small_count, small_resp = self._count_queries('/api/community/chats/')
        self.assertEqual(len(small_resp.data['chats']), 6)  # 5 DMs + 1 group

        self._seed_conversations_and_group('b', 10)
        large_count, large_resp = self._count_queries('/api/community/chats/')
        self.assertEqual(len(large_resp.data['chats']), 17)  # 15 DMs + 2 groups

        self.assertEqual(
            small_count, large_count,
            f'/chats/ query count scales with rows ({small_count} -> {large_count})',
        )
        self.assertLessEqual(large_count, 8)

    def test_members_query_count_is_constant(self):
        for i in range(5):
            make_user(f'ma{i}')
        small_count, small_resp = self._count_queries('/api/community/members/')
        self.assertEqual(len(small_resp.data['results']), 6)  # 5 + self

        for i in range(10):
            make_user(f'mb{i}')
        large_count, large_resp = self._count_queries('/api/community/members/')
        self.assertEqual(len(large_resp.data['results']), 16)

        self.assertEqual(
            small_count, large_count,
            f'/members/ query count scales with rows ({small_count} -> {large_count})',
        )
        self.assertLessEqual(large_count, 5)
