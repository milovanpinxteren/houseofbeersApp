"""Shared helpers for message reactions (DM, group, and livestream chat).

Both the community views and the events poll/chat views go through these two
functions, so the aggregation shape ({emoji: count} + the caller's own list)
is defined exactly once.
"""
from django.db import IntegrityError
from django.db.models import Count

from .models import ALLOWED_REACTIONS, MessageReaction


def reaction_map(fk_name, message_ids, user):
    """Reactions for a window of messages in two grouped queries (no N+1).

    Returns ``{message_id: {'reactions': {emoji: count}, 'mine': [emoji]}}``
    containing ONLY messages that have at least one reaction. ``fk_name`` is
    one of ``dm_message`` / ``group_message`` / ``event_message``.
    """
    message_ids = list(message_ids)
    if not message_ids:
        return {}

    qs = MessageReaction.objects.filter(**{f'{fk_name}__in': message_ids})

    result = {}
    for row in qs.values(fk_name, 'emoji').annotate(n=Count('id')):
        entry = result.setdefault(row[fk_name], {'reactions': {}, 'mine': []})
        entry['reactions'][row['emoji']] = row['n']

    # The caller's own reactions are a subset of all reactions: when the
    # counts query found nothing, skip the second query entirely (keeps the
    # common nobody-reacted page at ONE extra query).
    if result:
        for mid, emoji in qs.filter(user=user).values_list(fk_name, 'emoji'):
            result.setdefault(mid, {'reactions': {}, 'mine': []})['mine'].append(emoji)

    return result


def toggle_reaction(fk_name, message, user, emoji):
    """Toggle one emoji for one user on one message (PostLikeView idiom).

    Returns ``(reacted, reactions, mine)`` where ``reactions``/``mine`` are the
    FRESH state for that message — the toggle response is the client's
    reconciliation source, so unlike the list serializers these are included
    even when empty. Caller must have validated the emoji and permissions.
    """
    kwargs = {fk_name: message, 'user': user, 'emoji': emoji}
    try:
        reaction, created = MessageReaction.objects.get_or_create(**kwargs)
    except IntegrityError:
        # Lost a race with an identical toggle — the row exists now.
        reaction, created = MessageReaction.objects.get(**kwargs), False
    if not created:
        reaction.delete()

    state = reaction_map(fk_name, [message.id], user).get(
        message.id, {'reactions': {}, 'mine': []}
    )
    return created, state['reactions'], state['mine']
