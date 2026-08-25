"""
Service-to-service loyalty API, mounted at /api/service/loyalty/.

Called by trusted backend systems (the houseofbeers_whatsapp app, "hob") —
never by the mobile app. Auth is an HMAC-SHA256 signature over the raw
request body with a shared secret (`SERVICE_API_HMAC_SECRET`), the same
convention hob already uses with its wa-bot sidecar:

    X-Signature: sha256=<hexdigest of HMAC(secret, body)>

All endpoints are POST with a JSON body (uniform signing, no query strings).
Plain Django views, not DRF: the project's DRF defaults (JWT + IsAuthenticated)
have no business on a server-to-server surface. An empty/unset secret
disables the whole API (503).
"""
import hashlib
import hmac
import json
import logging
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from loyalty.services import grants as grant_service

logger = logging.getLogger(__name__)


def verify_service_hmac(view_func):
    @csrf_exempt
    @require_POST
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        secret = getattr(settings, 'SERVICE_API_HMAC_SECRET', '')
        if not secret:
            return JsonResponse(
                {'error': 'Service API is not configured'}, status=503
            )

        provided = request.headers.get('X-Signature', '')
        expected = 'sha256=' + hmac.new(
            secret.encode('utf-8'), request.body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(provided, expected):
            logger.warning("Service API request with invalid signature rejected")
            return JsonResponse({'error': 'Invalid signature'}, status=403)

        try:
            payload = json.loads(request.body.decode('utf-8')) if request.body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({'error': 'Invalid JSON body'}, status=400)
        if not isinstance(payload, dict):
            return JsonResponse({'error': 'Body must be a JSON object'}, status=400)

        return view_func(request, payload, *args, **kwargs)

    return wrapper


def _grant_payload(grant):
    data = {
        'grant_id': grant.id,
        'dedupe_key': grant.dedupe_key,
        'source': grant.source,
        'status': grant.status,
        'points': grant.points,
        'reason': grant.reason,
        'shopify_customer_id': grant.shopify_customer_id,
        'email': grant.email,
        'phone': grant.phone,
        'created_at': grant.created_at.isoformat() if grant.created_at else None,
        'granted_at': grant.granted_at.isoformat() if grant.granted_at else None,
        'revoked_at': grant.revoked_at.isoformat() if grant.revoked_at else None,
        'user': None,
    }
    if grant.user:
        data['user'] = {'email': grant.user.email}
    return data


@verify_service_hmac
def grant_view(request, payload):
    """
    Award points to a person, identified by shopify_customer_id / email /
    phone. Idempotent on dedupe_key. Non-members get a pending grant that is
    claimed automatically when they join.
    """
    try:
        grant, created = grant_service.create_grant(
            dedupe_key=payload.get('dedupe_key', ''),
            points=payload.get('points'),
            reason=payload.get('reason', ''),
            source=payload.get('source', 'hob'),
            shopify_customer_id=str(payload.get('shopify_customer_id') or ''),
            email=payload.get('email') or '',
            phone=payload.get('phone') or '',
            context=payload.get('context'),
            notify=bool(payload.get('notify', True)),
        )
    except grant_service.GrantError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception:
        logger.exception("Service grant failed")
        return JsonResponse({'error': 'Internal error'}, status=500)

    data = _grant_payload(grant)
    data['created'] = created
    if grant.user:
        balance = getattr(grant.user, 'points_balance', None)
        if balance:
            data['user']['balance'] = balance.balance
    return JsonResponse(data, status=201 if created else 200)


@verify_service_hmac
def lookup_view(request, payload):
    """
    Membership check: is this person an app member? Lets the caller decide
    e.g. whether to send an install invite. Also reports pending points
    parked for this identity.
    """
    from loyalty.models import PointsBalance, ServiceGrant

    shopify_customer_id = str(payload.get('shopify_customer_id') or '')
    email = payload.get('email') or ''
    phone = payload.get('phone') or ''
    if not (shopify_customer_id or email or phone):
        return JsonResponse(
            {'error': 'at least one of shopify_customer_id, email, phone '
                      'is required'},
            status=400,
        )

    try:
        user = grant_service.resolve_user(
            shopify_customer_id=shopify_customer_id, email=email
        )
    except grant_service.GrantError as e:
        return JsonResponse({'error': str(e)}, status=400)

    from django.db.models import Q
    identity = Q()
    if shopify_customer_id:
        identity |= Q(shopify_customer_id=shopify_customer_id)
    if email:
        identity |= Q(email__iexact=email)
    if phone:
        identity |= Q(phone=phone)
    pending = ServiceGrant.objects.filter(identity, status='pending')
    pending_points = sum(pending.values_list('points', flat=True))

    result = {
        'found': user is not None,
        'pending_grants': pending.count(),
        'pending_points': pending_points,
        'user': None,
    }
    if user:
        balance = PointsBalance.objects.filter(user=user).first()
        result['user'] = {
            'email': user.email,
            'shopify_customer_id': user.shopify_customer_id or '',
            'member_since': user.date_joined.isoformat(),
            'balance': balance.balance if balance else 0,
        }
    # Phone can never match a member directly (User has no phone field);
    # tell the caller so it can resolve phone -> shopify_customer_id itself.
    if not user and phone and not (shopify_customer_id or email):
        result['note'] = (
            'phone alone cannot match a member; supply shopify_customer_id '
            'or email for a definitive answer'
        )
    return JsonResponse(result)


@verify_service_hmac
def status_view(request, payload):
    """
    Grant status: a single grant by dedupe_key, or a filtered list
    (source / status, newest first, max 100).
    """
    from loyalty.models import ServiceGrant

    dedupe_key = payload.get('dedupe_key')
    if dedupe_key:
        grant = ServiceGrant.objects.filter(dedupe_key=dedupe_key).first()
        if not grant:
            return JsonResponse({'error': 'Unknown dedupe_key'}, status=404)
        return JsonResponse(_grant_payload(grant))

    qs = ServiceGrant.objects.all()
    if payload.get('source'):
        qs = qs.filter(source=payload['source'])
    if payload.get('status'):
        qs = qs.filter(status=payload['status'])
    try:
        limit = min(int(payload.get('limit', 25)), 100)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'limit must be an integer'}, status=400)
    return JsonResponse({
        'grants': [_grant_payload(g) for g in qs[:limit]],
    })


@verify_service_hmac
def revoke_view(request, payload):
    """Undo a grant (compensating transaction for granted ones). Idempotent."""
    dedupe_key = payload.get('dedupe_key', '')
    if not dedupe_key:
        return JsonResponse({'error': 'dedupe_key is required'}, status=400)
    try:
        grant = grant_service.revoke_grant(
            dedupe_key, reason=payload.get('reason', '')
        )
    except grant_service.GrantError as e:
        return JsonResponse({'error': str(e)}, status=404)
    except Exception:
        logger.exception("Service grant revoke failed")
        return JsonResponse({'error': 'Internal error'}, status=500)
    return JsonResponse(_grant_payload(grant))
