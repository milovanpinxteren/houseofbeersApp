"""Tests for livestream chat emoji reactions.

Covers:
- Toggle endpoint (on/off, multi-emoji, invalid emoji, system messages,
  cross-event 404, throttle configuration)
- Event.reactions_rev bumping on react AND unreact
- The poll's rev-gated reaction digest (only on rev change, window scoping
  via oldest_message_id, newest-300 cap, snapshot semantics for un-reacts)
- Reactions inline on the poll's initial message fetch, keys omitted when
  empty
"""
from django.core.cache import cache
from rest_framework.test import APITestCase

from community.models import ALLOWED_REACTIONS, MessageReaction
from .models import Event, EventMessage
from .tests import make_event, make_user
from .views import ChatReactionRateThrottle, EventChatReactView


BEER = ALLOWED_REACTIONS[0]   # 🍺
FIRE = ALLOWED_REACTIONS[1]   # 🔥


def react_url(event, message):
    return f'/api/events/{event.id}/chat/{message.id}/react/'


class EventReactionToggleTests(APITestCase):
    def setUp(self):
        cache.clear()  # throttle state
        self.user = make_user(0)
        self.other = make_user(1)
        self.event = make_event()
        self.msg = EventMessage.objects.create(
            event=self.event, user=self.other, message='proost',
        )
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        cache.clear()

    def test_toggle_on_then_off(self):
        response = self.client.post(react_url(self.event, self.msg), {'emoji': BEER}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['reacted'])
        self.assertEqual(response.data['reactions'], {BEER: 1})
        self.assertEqual(response.data['mine'], [BEER])

        response = self.client.post(react_url(self.event, self.msg), {'emoji': BEER}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['reacted'])
        # Toggle response is the reconciliation source: empty but present.
        self.assertEqual(response.data['reactions'], {})
        self.assertEqual(response.data['mine'], [])
        self.assertEqual(MessageReaction.objects.count(), 0)

    def test_user_may_hold_multiple_distinct_emoji(self):
        self.client.post(react_url(self.event, self.msg), {'emoji': BEER}, format='json')
        response = self.client.post(react_url(self.event, self.msg), {'emoji': FIRE}, format='json')
        self.assertEqual(response.data['reactions'], {BEER: 1, FIRE: 1})
        self.assertEqual(sorted(response.data['mine']), sorted([BEER, FIRE]))

    def test_counts_aggregate_across_users(self):
        self.client.post(react_url(self.event, self.msg), {'emoji': BEER}, format='json')
        other_client = self.client_class()
        other_client.force_authenticate(user=self.other)
        response = other_client.post(react_url(self.event, self.msg), {'emoji': BEER}, format='json')
        self.assertEqual(response.data['reactions'], {BEER: 2})
        self.assertEqual(response.data['mine'], [BEER])  # the OTHER user's own list

    def test_invalid_emoji_rejected(self):
        for bad in ['💀', 'beer', '', None]:
            payload = {} if bad is None else {'emoji': bad}
            response = self.client.post(react_url(self.event, self.msg), payload, format='json')
            self.assertEqual(response.status_code, 400, f'{bad!r} should be rejected')
        self.assertEqual(MessageReaction.objects.count(), 0)

    def test_system_message_rejected(self):
        system = EventMessage.objects.create(
            event=self.event, user=self.other, message='draw!', is_system=True,
        )
        response = self.client.post(react_url(self.event, system), {'emoji': BEER}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_message_of_other_event_is_404(self):
        other_event = make_event(title='Other')
        response = self.client.post(react_url(other_event, self.msg), {'emoji': BEER}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_rev_bumps_on_react_and_unreact(self):
        self.assertEqual(Event.objects.get(pk=self.event.pk).reactions_rev, 0)
        self.client.post(react_url(self.event, self.msg), {'emoji': BEER}, format='json')
        self.assertEqual(Event.objects.get(pk=self.event.pk).reactions_rev, 1)
        self.client.post(react_url(self.event, self.msg), {'emoji': BEER}, format='json')
        self.assertEqual(Event.objects.get(pk=self.event.pk).reactions_rev, 2)

    def test_throttle_configured(self):
        self.assertEqual(EventChatReactView.throttle_classes, [ChatReactionRateThrottle])
        self.assertEqual(ChatReactionRateThrottle.rate, '60/min')
        self.assertEqual(ChatReactionRateThrottle.scope, 'event_chat_react')


class PollReactionDigestTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user(0)
        self.other = make_user(1)
        self.event = make_event()
        self.messages = [
            EventMessage.objects.create(event=self.event, user=self.other, message=f'm{i}')
            for i in range(3)
        ]
        self.client.force_authenticate(user=self.user)
        self.poll_url = f'/api/events/{self.event.id}/poll/'

    def tearDown(self):
        cache.clear()

    def _react(self, message, emoji=BEER, user=None):
        client = self.client_class()
        client.force_authenticate(user=user or self.other)
        response = client.post(react_url(self.event, message), {'emoji': emoji}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_poll_always_includes_reaction_rev(self):
        response = self.client.get(self.poll_url)
        self.assertEqual(response.data['reaction_rev'], 0)
        self._react(self.messages[0])
        response = self.client.get(self.poll_url)
        self.assertEqual(response.data['reaction_rev'], 1)

    def test_no_digest_without_known_rev_param(self):
        self._react(self.messages[0])
        response = self.client.get(self.poll_url)
        self.assertNotIn('reaction_updates', response.data)

    def test_no_digest_when_rev_matches(self):
        self._react(self.messages[0])
        response = self.client.get(f'{self.poll_url}?known_reaction_rev=1')
        self.assertNotIn('reaction_updates', response.data)

    def test_digest_when_rev_differs(self):
        self._react(self.messages[0])
        self._react(self.messages[2], emoji=FIRE, user=self.user)
        response = self.client.get(f'{self.poll_url}?known_reaction_rev=0')
        updates = response.data['reaction_updates']
        self.assertEqual([u['m'] for u in updates],
                         [self.messages[0].id, self.messages[2].id])  # sorted by id
        self.assertEqual(updates[0]['r'], {BEER: 1})
        self.assertEqual(updates[0]['mine'], [])          # not the caller's
        self.assertEqual(updates[1]['r'], {FIRE: 1})
        self.assertEqual(updates[1]['mine'], [FIRE])      # the caller's own

    def test_digest_scoped_by_oldest_message_id(self):
        self._react(self.messages[0])
        self._react(self.messages[2])
        response = self.client.get(
            f'{self.poll_url}?known_reaction_rev=0&oldest_message_id={self.messages[1].id}'
        )
        updates = response.data['reaction_updates']
        self.assertEqual([u['m'] for u in updates], [self.messages[2].id])

    def test_digest_capped_at_newest_300_messages(self):
        EventMessage.objects.bulk_create([
            EventMessage(event=self.event, user=self.other, message=f'bulk{i}')
            for i in range(310)
        ])
        oldest = self.messages[0]       # now far outside the newest-300 window
        newest = EventMessage.objects.filter(event=self.event).order_by('-id').first()
        self._react(oldest)
        self._react(newest)
        response = self.client.get(f'{self.poll_url}?known_reaction_rev=0')
        updates = response.data['reaction_updates']
        self.assertEqual([u['m'] for u in updates], [newest.id])

    def test_unreact_propagates_as_snapshot(self):
        # React (rev 1), client syncs, then unreact (rev 2): the digest is a
        # snapshot of reacted messages, so the message simply disappears from
        # it — the client clears reactions for held messages absent from the
        # list.
        self._react(self.messages[0])
        self._react(self.messages[0])   # toggle off again -> rev 2
        response = self.client.get(f'{self.poll_url}?known_reaction_rev=1')
        self.assertEqual(response.data['reaction_updates'], [])

    def test_initial_messages_carry_reactions_inline_and_omit_when_empty(self):
        self._react(self.messages[0], user=self.user)
        response = self.client.get(self.poll_url)   # no after param: last 100
        by_id = {m['id']: m for m in response.data['messages']}
        reacted = by_id[self.messages[0].id]
        self.assertEqual(reacted['reactions'], {BEER: 1})
        self.assertEqual(reacted['mine'], [BEER])
        untouched = by_id[self.messages[1].id]
        self.assertNotIn('reactions', untouched)
        self.assertNotIn('mine', untouched)
