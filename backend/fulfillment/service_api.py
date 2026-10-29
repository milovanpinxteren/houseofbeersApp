"""
Service-to-service fulfillment API, mounted at /api/service/fulfillment/.

Called by hob (houseofbeers_whatsapp) to push missed-items snapshots: per
(sale, customer), the beers someone ordered in a WhatsApp sale but did not
(fully) receive because they were too late. Same auth convention as
/api/service/loyalty/: HMAC-SHA256 over the raw body with the shared
SERVICE_API_HMAC_SECRET, all endpoints POST with a JSON body.

Contract:

POST missed/  (see fulfillment/services/missed.py for the full payload)
    -> 201 {'status': 'created', 'record_status': ...} on first push,
       200 {'status': 'updated', 'record_status': ...} on a re-push
       (UPSERT by dedupe_key: lines and draft/order ids are REPLACED).
    lines == [] clears the record (record_status 'cleared'): the customer
    no longer misses anything, the row stays as the idempotency guard.
    400 on invalid payload — never 500 on bad input.
"""
import logging

from django.http import JsonResponse

from loyalty.service_api import verify_service_hmac

from .services import missed as missed_service

logger = logging.getLogger(__name__)


@verify_service_hmac
def missed_upsert_view(request, payload):
    try:
        record, created = missed_service.upsert_missed(payload)
    except missed_service.MissedItemsError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception:
        logger.exception("Missed-items upsert failed")
        return JsonResponse({'error': 'Internal error'}, status=500)

    return JsonResponse(
        {
            'status': 'created' if created else 'updated',
            'record_status': record.status,
        },
        status=201 if created else 200,
    )
