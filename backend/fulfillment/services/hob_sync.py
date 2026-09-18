"""
Outbound sync of pickup RSVPs to hob (the houseofbeers_whatsapp app).

hob uses the RSVP to set the customer's warehouse queue/priority. This is
the OUTBOUND mirror of the inbound service API in loyalty/service_api.py:
the same HMAC-SHA256 convention, but now we are the caller —

    X-Signature: sha256=<hexdigest of HMAC(secret, raw JSON body)>

Configuration is env-driven (`HOB_SERVICE_URL`, `HOB_SERVICE_HMAC_SECRET`);
either one empty disables the sync: the log row is marked 'skipped' and the
RSVP itself always succeeds regardless.
"""
import hashlib
import hmac
import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ENDPOINT_PATH = '/api/service/app/pickup-rsvp/'
TIMEOUT = 10
# Stored response bodies are capped so a misbehaving endpoint cannot bloat
# the log table.
MAX_RESPONSE_CHARS = 2000


def is_configured() -> bool:
    return bool(
        getattr(settings, 'HOB_SERVICE_URL', '')
        and getattr(settings, 'HOB_SERVICE_HMAC_SECRET', '')
    )


def build_payload(log) -> dict:
    """The exact JSON body hob expects for a PickupActionLog row."""
    user = log.user
    shopify_customer_id = None
    if user.shopify_customer_id:
        try:
            shopify_customer_id = int(user.shopify_customer_id)
        except (TypeError, ValueError):
            shopify_customer_id = None
    return {
        'action': log.action,
        'shopify_customer_id': shopify_customer_id,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'pickup_date': log.pickup_date.isoformat(),
    }


def sign_body(body: bytes) -> str:
    secret = getattr(settings, 'HOB_SERVICE_HMAC_SECRET', '')
    return 'sha256=' + hmac.new(
        secret.encode('utf-8'), body, hashlib.sha256
    ).hexdigest()


def push_pickup_action(log) -> tuple:
    """
    POST one action to hob. Returns (sync_status, response_text) where
    sync_status is 'success' | 'failed' | 'skipped'. Never raises: the
    caller (the Celery task) decides whether a failure is worth a retry.
    """
    if not is_configured():
        return 'skipped', 'hob sync not configured (HOB_SERVICE_URL / HOB_SERVICE_HMAC_SECRET)'

    url = settings.HOB_SERVICE_URL.rstrip('/') + ENDPOINT_PATH
    body = json.dumps(build_payload(log)).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'X-Signature': sign_body(body),
    }

    try:
        response = requests.post(url, data=body, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as e:
        logger.warning(f"hob pickup sync request failed for log {log.id}: {e}")
        return 'failed', f'Request error: {e}'[:MAX_RESPONSE_CHARS]

    snippet = (response.text or '')[:MAX_RESPONSE_CHARS]
    if 200 <= response.status_code < 300:
        try:
            data = response.json()
        except ValueError:
            return 'failed', f'HTTP {response.status_code}, non-JSON body: {snippet}'[:MAX_RESPONSE_CHARS]
        if isinstance(data, dict) and data.get('success') is True:
            return 'success', snippet
        return 'failed', f'HTTP {response.status_code}, success flag missing: {snippet}'[:MAX_RESPONSE_CHARS]

    return 'failed', f'HTTP {response.status_code}: {snippet}'[:MAX_RESPONSE_CHARS]
