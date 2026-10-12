"""
Service-to-service events API, mounted at /api/service/events/.

Called by hob (houseofbeers_whatsapp) to push auction announcements into
a livestream event — the "Push naar app" button on hob's beer-announcements
run page. Same auth convention as /api/service/loyalty/: HMAC-SHA256 over
the raw body with the shared SERVICE_API_HMAC_SECRET (hob reuses its
existing LOYALTY_API_* credentials), all endpoints POST with a JSON body.

Contract (FROZEN — hob implements against exactly this):

POST upcoming-events/   {}            -> {'events': [{id, title, event_type,
                                          scheduled_at, status}]}
POST auction-items/upsert/            -> 201/200 {'id', 'created',
                                          'status', 'event_id'}
    Required: dedupe_key, event_id, title, starting_price (>= 0).
    Optional: description, brewery, size, untappd_rating, image_url,
    min_increment (int >= 1, default 5).
    409 when the item exists but is no longer 'pending' (auction already
    started or sold in the app — a re-push cannot rewrite history).
"""
import logging
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse

from loyalty.service_api import verify_service_hmac

from .models import AuctionItem, Event

logger = logging.getLogger(__name__)

# Keep pushed values inside the model's field sizes.
_MAX_LENGTHS = {
    'dedupe_key': 100,
    'title': 200,
    'brewery': 200,
    'size': 50,
    'image_url': 500,
}


@verify_service_hmac
def upcoming_events_view(request, payload):
    """Scheduled/live events, soonest first — the event picker in hob's
    push modal. Ended events are not valid push targets."""
    events = (
        Event.objects
        .filter(status__in=['scheduled', 'live'])
        .order_by('scheduled_at')
    )
    return JsonResponse({'events': [
        {
            'id': event.id,
            'title': event.title,
            'event_type': event.event_type,
            'scheduled_at': event.scheduled_at.isoformat(),
            'status': event.status,
        }
        for event in events
    ]})


def _clean_str(payload, key, required=False):
    """Trimmed string field or an error string."""
    value = payload.get(key)
    if value is None:
        value = ''
    if not isinstance(value, str):
        return None, f'{key} must be a string'
    value = value.strip()
    if required and not value:
        return None, f'{key} is required'
    max_length = _MAX_LENGTHS.get(key)
    if max_length and len(value) > max_length:
        value = value[:max_length]
    return value, None


@verify_service_hmac
def auction_item_upsert_view(request, payload):
    """
    Create or update an AuctionItem from a hob beer announcement,
    idempotent on dedupe_key. Updates (re-push after a correction) are
    only allowed while the item is still 'pending' — once the auction is
    active or sold the row is frozen and the caller gets a 409.
    """
    errors = []
    dedupe_key, err = _clean_str(payload, 'dedupe_key', required=True)
    if err:
        errors.append(err)
    title, err = _clean_str(payload, 'title', required=True)
    if err:
        errors.append(err)
    optional = {}
    for key in ('description', 'brewery', 'size', 'image_url'):
        optional[key], err = _clean_str(payload, key)
        if err:
            errors.append(err)

    try:
        starting_price = Decimal(str(payload.get('starting_price')))
        if starting_price < 0:  # NaN also lands here (signals InvalidOperation)
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        starting_price = None
        errors.append('starting_price must be a number >= 0')

    untappd_rating = payload.get('untappd_rating')
    if untappd_rating is not None:
        try:
            untappd_rating = Decimal(str(untappd_rating)).quantize(
                Decimal('0.01'))
            if not (0 <= untappd_rating <= 5):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            errors.append('untappd_rating must be a number between 0 and 5')

    try:
        min_increment = int(payload.get('min_increment', 5))
        if min_increment < 1:
            raise ValueError
    except (TypeError, ValueError):
        min_increment = None
        errors.append('min_increment must be an integer >= 1')

    event = None
    try:
        event = Event.objects.get(pk=int(payload.get('event_id')))
    except (TypeError, ValueError):
        errors.append('event_id is required')
    except Event.DoesNotExist:
        errors.append('Unknown event_id')
    if event is not None and event.status == 'ended':
        errors.append('Event is already ended')

    if errors:
        return JsonResponse({'error': '; '.join(errors)}, status=400)

    item = AuctionItem.objects.filter(source_key=dedupe_key).first()
    if item is not None and item.status != 'pending':
        return JsonResponse({
            'error': (
                f"Veilingitem '{item.title}' is al "
                f"{'actief' if item.status == 'active' else 'verkocht'} "
                'in de app en kan niet meer worden bijgewerkt.'
            ),
            'status': item.status,
            'id': item.id,
        }, status=409)

    fields = {
        'event': event,
        'title': title,
        'starting_price': starting_price,
        'min_increment': min_increment,
        'untappd_rating': untappd_rating,
        **optional,
    }
    created = item is None
    if created:
        item = AuctionItem.objects.create(source_key=dedupe_key, **fields)
    else:
        for key, value in fields.items():
            setattr(item, key, value)
        item.save()
    logger.info(
        f"Service auction upsert: {'created' if created else 'updated'} "
        f"item {item.id} ('{item.title}') on event {event.id} [{dedupe_key}]"
    )
    return JsonResponse({
        'id': item.id,
        'created': created,
        'status': item.status,
        'event_id': event.id,
    }, status=201 if created else 200)
