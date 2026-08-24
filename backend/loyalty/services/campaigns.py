"""Campaign engine: cumulative condition evaluation, qualification actions,
raffle entries and the shop-wide backfill scan.

Campaigns sit alongside the PointsRule engine and never modify its behavior.
Order flow: the points sync calls apply_order_to_campaigns() for every paid
order; run_backfill() feeds a shop-wide window scan through the same
per-order logic (or simulates it for a Studio preview).
"""
import logging
import secrets
import string
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# matcher_qty key used when a campaign has no product matchers
# (every item in every window order counts).
ANY_PRODUCT_KEY = '*'

DUTCH_MONTHS = [
    'januari', 'februari', 'maart', 'april', 'mei', 'juni',
    'juli', 'augustus', 'september', 'oktober', 'november', 'december',
]

# The three counting thresholds a "near miss" can be exactly 1 short on.
NEAR_MISS_CONDITIONS = ('min_distinct_products', 'min_total_quantity', 'min_order_count')


def _parse_order_date(order: Dict[str, Any]) -> Optional[datetime]:
    """Parse the Shopify order's created_at into an aware datetime."""
    raw = order.get('created_at')
    if not raw:
        return None
    if isinstance(raw, datetime):
        parsed = raw
    else:
        try:
            parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        except ValueError:
            return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt_timezone.utc)
    return parsed


# ============ Rule sentence ============

def _nl_date(dt) -> str:
    local = timezone.localtime(dt)
    return f"{local.day} {DUTCH_MONTHS[local.month - 1]}"


def _nl_period(start, end) -> str:
    start_local = timezone.localtime(start)
    end_local = timezone.localtime(end)
    if (start_local.year, start_local.month) == (end_local.year, end_local.month):
        return f"tussen {start_local.day} en {end_local.day} {DUTCH_MONTHS[start_local.month - 1]}"
    return f"tussen {_nl_date(start)} en {_nl_date(end)}"


def _nl_amount(value) -> str:
    amount = Decimal(value)
    if amount == int(amount):
        return f"€{int(amount)}"
    return f"€{amount}"


def _action_clause(campaign) -> str:
    """Third-person-singular action clause ('krijgt 50 punten')."""
    if campaign.action_type == 'points' and campaign.points_amount:
        if campaign.points_mode == 'per_item':
            return f"krijgt {campaign.points_amount} punten per gekocht item"
        return f"krijgt {campaign.points_amount} punten"
    if campaign.action_type == 'discount_code':
        if campaign.discount_type == 'percentage' and campaign.discount_value:
            pct = campaign.discount_value
            pct_text = str(int(pct)) if pct == int(pct) else str(pct)
            return f"ontvangt een kortingscode van {pct_text}%"
        if campaign.discount_type == 'fixed_amount' and campaign.discount_value:
            return f"ontvangt een kortingscode van {_nl_amount(campaign.discount_value)}"
        if campaign.discount_type == 'free_shipping':
            return "ontvangt gratis verzending"
        if campaign.discount_type == 'free_product':
            return "ontvangt een gratis product"
        return "ontvangt een kortingscode"
    if campaign.action_type == 'raffle':
        action = "doet mee in de loting"
        raffle = campaign.raffle if hasattr(campaign, 'raffle') else None
        if raffle:
            if raffle.prize_name:
                action += f" voor {raffle.prize_name}"
            if campaign.audience_mode != 'audience':
                if raffle.entry_mode == 'per_item':
                    action += " (1 lot per gekocht item)"
                elif raffle.entry_mode == 'per_order':
                    action += " (1 lot per bestelling)"
        return action
    return "doet mee"


def build_rule_sentence(campaign) -> str:
    """
    Plain-language NL summary of the campaign, e.g. "Iedereen die tussen 1 en
    30 september minstens 2 van deze 3 bieren koopt, doet mee in de loting
    (1 lot per gekocht item)." Audience-mode campaigns describe the selection
    instead of purchase conditions.
    """
    if campaign.audience_mode == 'audience':
        from loyalty.services.audience import describe_filters

        action = _action_clause(campaign)
        clauses = describe_filters(campaign)
        if clauses:
            return f"Ieder lid dat {' en '.join(clauses)}, {action} — automatisch."
        return f"Een geselecteerde groep leden {action} — automatisch."

    period = _nl_period(campaign.window_start, campaign.window_end)

    matchers = campaign.product_matchers or []
    clauses = []
    if matchers:
        n = len(matchers)
        if campaign.min_distinct_products > 1 and n > 1:
            clauses.append(
                f"minstens {campaign.min_distinct_products} van deze {n} bieren koopt"
            )
        elif campaign.min_total_quantity > 1:
            noun = 'dit bier' if n == 1 else 'deze bieren'
            clauses.append(f"minstens {campaign.min_total_quantity} keer {noun} koopt")
        else:
            clauses.append('dit bier koopt' if n == 1 else 'een van deze bieren koopt')
        if campaign.min_order_count and campaign.min_order_count > 1:
            clauses.append(f"verspreid over minstens {campaign.min_order_count} bestellingen")
    else:
        if campaign.min_order_count and campaign.min_order_count > 1:
            clauses.append(f"minstens {campaign.min_order_count} bestellingen plaatst")
        elif campaign.min_total_quantity > 1:
            clauses.append(f"minstens {campaign.min_total_quantity} items bestelt")
        else:
            clauses.append("een bestelling plaatst")

    if campaign.min_order_value is not None:
        clauses.append(f"met een bestelling van minstens {_nl_amount(campaign.min_order_value)}")
    if campaign.min_total_spend is not None:
        clauses.append(f"in totaal minstens {_nl_amount(campaign.min_total_spend)} besteedt")
    if campaign.first_order_only:
        clauses.append("als allereerste bestelling")
    if campaign.requires_untappd:
        clauses.append("met een gekoppeld Untappd-account")

    condition = ' en '.join(clauses)
    action = _action_clause(campaign)

    sentence = f"Iedereen die {period} {condition}, {action}."
    from loyalty.services.audience import describe_filters, has_audience
    if has_audience(campaign):
        # Orders mode with an audience gate: mention the restriction.
        parts = describe_filters(campaign)
        if parts:
            sentence += f" Alleen voor leden die {' en '.join(parts)}."
        else:
            sentence += " Alleen voor geselecteerde leden."
    return sentence


# ============ Matcher resolution ============

def resolve_product_matchers(campaign) -> Dict[str, list]:
    """
    Resolve tag/collection matchers to product id lists via Shopify and store
    the snapshot on the campaign. Safe no-op (no Shopify calls) when the
    campaign has no tag/collection matchers. A failed Shopify call keeps that
    matcher's previous snapshot instead of wiping it.
    """
    matchers = campaign.product_matchers or []
    dynamic = [
        (index, matcher) for index, matcher in enumerate(matchers)
        if matcher.get('type') in ('tag', 'collection')
    ]

    if not dynamic:
        campaign.resolved_product_ids = {}
        campaign.resolved_at = timezone.now()
        campaign.save(update_fields=['resolved_product_ids', 'resolved_at', 'updated_at'])
        return {}

    from users.services import ShopifyService

    service = ShopifyService()
    resolved = dict(campaign.resolved_product_ids or {})
    for index, matcher in dynamic:
        try:
            if matcher.get('type') == 'tag':
                ids = service.get_product_ids_by_tag(str(matcher.get('value', '')))
            else:
                ids = service.get_collection_product_ids(matcher.get('value'))
            resolved[str(index)] = ids
        except Exception as e:
            logger.error(
                f"Failed to resolve matcher {index} ({matcher}) for campaign "
                f"{campaign.id}, keeping previous snapshot: {e}"
            )

    campaign.resolved_product_ids = resolved
    campaign.resolved_at = timezone.now()
    campaign.save(update_fields=['resolved_product_ids', 'resolved_at', 'updated_at'])
    return resolved


# ============ Order matching & progress accumulation ============

def _item_matches(campaign, index: int, matcher: Dict[str, Any], item: Dict[str, Any]) -> bool:
    mtype = matcher.get('type')
    value = str(matcher.get('value', ''))
    if mtype == 'sku':
        return (item.get('sku') or '') == value
    if mtype == 'product_id':
        return str(item.get('product_id') or '') == value
    if mtype == 'title':
        return bool(value) and value.lower() in (item.get('title') or '').lower()
    if mtype in ('tag', 'collection'):
        resolved = (campaign.resolved_product_ids or {}).get(str(index)) or []
        return str(item.get('product_id') or '') in {str(pid) for pid in resolved}
    return False


def _match_order(campaign, order: Dict[str, Any]) -> Tuple[Dict[str, int], int, List[str], bool]:
    """
    Match one order against the campaign's matchers.
    Returns (per-matcher qty deltas, total matched qty, matched item titles,
    whether the order matched at all).
    """
    line_items = order.get('line_items') or []
    matchers = campaign.product_matchers or []

    if not matchers:
        total = sum(item.get('quantity', 1) for item in line_items)
        titles = [item.get('title') for item in line_items if item.get('title')]
        deltas = {ANY_PRODUCT_KEY: total} if total else {}
        return deltas, total, titles, True

    deltas: Dict[str, int] = {}
    titles: List[str] = []
    total = 0
    for index, matcher in enumerate(matchers):
        qty = 0
        for item in line_items:
            if _item_matches(campaign, index, matcher, item):
                qty += item.get('quantity', 1)
                title = item.get('title')
                if title and title not in titles:
                    titles.append(title)
        if qty:
            deltas[str(index)] = qty
            total += qty
    return deltas, total, titles, bool(deltas)


def _empty_data() -> Dict[str, Any]:
    return {
        'spend': '0',
        'order_count': 0,
        'matcher_qty': {},
        'matched_order_ids': [],
        'processed_order_ids': [],
        'matched_products': [],
    }


def _accumulate_order(campaign, user, data: Dict[str, Any], order: Dict[str, Any],
                      order_date: datetime) -> bool:
    """
    Fold one order into a progress data dict. Returns False when the order was
    already processed or does not count (only_after_registration); mutates
    `data` in place either way (the idempotency guard is always recorded).
    """
    order_id = str(order.get('id'))
    processed = data.setdefault('processed_order_ids', [])
    if order_id in processed:
        return False
    processed.append(order_id)

    if campaign.only_after_registration and order_date < user.date_joined:
        return False

    order_total = Decimal(str(order.get('total_price', 0)))
    data['spend'] = str(Decimal(data.get('spend', '0')) + order_total)
    data['order_count'] = data.get('order_count', 0) + 1

    deltas, _matched_qty, matched_titles, matched = _match_order(campaign, order)
    matcher_qty = data.setdefault('matcher_qty', {})
    for key, qty in deltas.items():
        matcher_qty[key] = matcher_qty.get(key, 0) + qty

    if matched:
        data.setdefault('matched_order_ids', []).append(order_id)
        products = data.setdefault('matched_products', [])
        for title in matched_titles:
            if title not in products:
                products.append(title)
        if order_total > Decimal(data.get('max_order_value', '0')):
            data['max_order_value'] = str(order_total)

    if campaign.first_order_only and not data.get('first_order_ok'):
        # Mirrors the first_order PointsRule: "first ever" is judged against
        # the orders the app has processed (pre-app history is invisible).
        from loyalty.models import ProcessedOrder
        has_earlier = ProcessedOrder.objects.filter(user=user).exclude(
            shopify_order_id=order_id
        ).exists()
        if not has_earlier:
            data['first_order_ok'] = True

    return True


# ============ Condition evaluation ============

def _condition_checks(campaign, user, data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Evaluate every configured condition. Returns {name: {'ok': bool, and for
    the counting thresholds 'actual'/'threshold'}} so the near-miss check can
    see how close a user got.
    """
    matchers = campaign.product_matchers or []
    matcher_qty = data.get('matcher_qty') or {}
    total_matched = sum(matcher_qty.values())
    order_count = data.get('order_count', 0)

    checks: Dict[str, Dict[str, Any]] = {}

    if matchers:
        distinct = sum(
            1 for key, qty in matcher_qty.items()
            if key != ANY_PRODUCT_KEY and qty > 0
        )
        threshold = campaign.min_distinct_products
    else:
        # No matchers = any order counts; the distinct condition reduces to
        # "at least one order".
        distinct = min(order_count, 1)
        threshold = 1
    checks['min_distinct_products'] = {
        'ok': distinct >= threshold, 'actual': distinct, 'threshold': threshold,
    }

    checks['min_total_quantity'] = {
        'ok': total_matched >= campaign.min_total_quantity,
        'actual': total_matched, 'threshold': campaign.min_total_quantity,
    }

    if campaign.min_order_count:
        checks['min_order_count'] = {
            'ok': order_count >= campaign.min_order_count,
            'actual': order_count, 'threshold': campaign.min_order_count,
        }
    if campaign.min_order_value is not None:
        max_order_value = Decimal(data.get('max_order_value', '0'))
        checks['min_order_value'] = {'ok': max_order_value >= campaign.min_order_value}
    if campaign.min_total_spend is not None:
        spend = Decimal(data.get('spend', '0'))
        checks['min_total_spend'] = {'ok': spend >= campaign.min_total_spend}
    if campaign.first_order_only:
        checks['first_order_only'] = {'ok': bool(data.get('first_order_ok'))}
    if campaign.requires_untappd:
        from recommendations.models import UntappdProfile
        checks['requires_untappd'] = {
            'ok': UntappdProfile.objects.filter(user=user).exists()
        }
    if campaign.min_points_balance is not None:
        from loyalty.models import PointsBalance
        balance = PointsBalance.objects.filter(user=user).values_list(
            'balance', flat=True
        ).first() or 0
        checks['min_points_balance'] = {'ok': balance >= campaign.min_points_balance}
    if campaign.registered_after:
        checks['registered_after'] = {'ok': user.date_joined >= campaign.registered_after}

    from loyalty.services.audience import has_audience, user_in_audience
    if has_audience(campaign):
        # In orders mode a configured audience is an extra gate; an audience
        # miss is never a near-miss (you can't buy your way into a birthday
        # month).
        checks['audience'] = {'ok': user_in_audience(campaign, user)}

    return checks


def _conditions_met(campaign, user, data: Dict[str, Any]) -> bool:
    return all(check['ok'] for check in _condition_checks(campaign, user, data).values())


def _is_near_miss(checks: Dict[str, Dict[str, Any]]) -> bool:
    """Everything satisfied except exactly 1 short on one counting threshold."""
    fails = [name for name, check in checks.items() if not check['ok']]
    if len(fails) != 1 or fails[0] not in NEAR_MISS_CONDITIONS:
        return False
    check = checks[fails[0]]
    return check.get('actual') == check.get('threshold', 0) - 1


def _compute_tickets(campaign, data: Dict[str, Any]) -> int:
    raffle = campaign.raffle if hasattr(campaign, 'raffle') else None
    mode = raffle.entry_mode if raffle else 'single'
    if mode == 'per_item':
        return max(1, sum((data.get('matcher_qty') or {}).values()))
    if mode == 'per_order':
        if campaign.product_matchers:
            return max(1, len(data.get('matched_order_ids') or []))
        return max(1, data.get('order_count', 0))
    return 1


# ============ Per-order application ============

def apply_order_to_campaigns(user, order: Dict[str, Any]):
    """
    Called from the sync pipeline for EVERY paid order (even 0-point ones).
    Applies the order to each active campaign whose window contains its
    created_at. Atomic per campaign+user; one campaign's failure never
    affects another.
    """
    if order.get('financial_status') != 'paid':
        return

    order_date = _parse_order_date(order)
    if order_date is None:
        return

    from loyalty.models import Campaign

    campaigns = Campaign.objects.filter(
        status='active',
        # Audience-mode campaigns qualify by selection, not by orders.
        audience_mode='orders',
        window_start__lte=order_date,
        window_end__gte=order_date,
    )
    for campaign in campaigns:
        try:
            with transaction.atomic():
                _apply_order_to_campaign(campaign, user, order, order_date)
        except Exception as e:
            logger.error(
                f"Campaign {campaign.id} ({campaign.name}) failed for order "
                f"{order.get('name')}: {e}",
                exc_info=True,
            )


def _apply_order_to_campaign(campaign, user, order: Dict[str, Any], order_date: datetime):
    """Idempotently fold one order into one campaign's per-user progress."""
    from loyalty.models import CampaignProgress

    progress, _ = CampaignProgress.objects.select_for_update().get_or_create(
        campaign=campaign, user=user
    )
    data = progress.data or _empty_data()

    qty_before = sum((data.get('matcher_qty') or {}).values())
    counted = _accumulate_order(campaign, user, data, order, order_date)
    progress.data = data
    progress.save(update_fields=['data', 'updated_at'])
    if not counted:
        return

    if progress.qualified_at is None:
        if _conditions_met(campaign, user, data):
            progress.qualified_at = timezone.now()
            progress.save(update_fields=['qualified_at', 'updated_at'])
            fire_qualification(campaign, user, progress)
    else:
        _update_after_qualification(campaign, user, progress, qty_before)


def _update_after_qualification(campaign, user, progress, qty_before: int):
    """
    A later qualifying order arrived after the action already fired:
    per_item points award incrementally; raffle tickets get recomputed.
    """
    from loyalty.models import CampaignAward, RaffleEntry

    data = progress.data or {}

    if (campaign.action_type == 'points' and campaign.points_mode == 'per_item'
            and campaign.points_amount):
        qty_now = sum((data.get('matcher_qty') or {}).values())
        new_items = qty_now - qty_before
        if new_items > 0:
            award = CampaignAward.objects.filter(campaign=campaign, user=user).first()
            if award:
                points = campaign.points_amount * new_items
                txn = _award_campaign_points(campaign, user, points)
                award.points_awarded += points
                award.points_transaction = txn
                award.save(update_fields=['points_awarded', 'points_transaction'])

    elif campaign.action_type == 'raffle' and hasattr(campaign, 'raffle'):
        raffle = campaign.raffle
        if raffle.status != 'open':
            return
        entry = RaffleEntry.objects.filter(raffle=raffle, user=user).first()
        if entry:
            entry.ticket_count = _compute_tickets(campaign, data)
            entry.matched_products = data.get('matched_products') or []
            entry.save(update_fields=['ticket_count', 'matched_products'])


# ============ Qualification action ============

def _generate_campaign_code() -> str:
    # HOB- prefix keeps the code inside ShopifyService.APP_CODE_PREFIXES
    # attribution (loyalty), same as reward redemptions.
    chars = string.ascii_uppercase + string.digits
    return 'HOB-' + ''.join(secrets.choice(chars) for _ in range(8))


def _award_campaign_points(campaign, user, points: int):
    """Earned transaction with a campaign breakdown; rule stays None."""
    from loyalty.models import PointsBalance, PointsTransaction

    balance, _ = PointsBalance.objects.get_or_create(user=user)
    balance.balance += points
    balance.lifetime_earned += points
    balance.save()

    return PointsTransaction.objects.create(
        user=user,
        transaction_type='earned',
        points=points,
        balance_after=balance.balance,
        description=campaign.name,
        breakdown=[{
            'campaign_id': campaign.id,
            'campaign_name': campaign.name,
            'points': points,
        }],
    )


def fire_qualification(campaign, user, progress):
    """
    Fire the campaign action exactly once (CampaignAward's unique constraint
    is the guard) and send the qualify notification. Returns the award.
    """
    from loyalty.models import CampaignAward, RaffleEntry

    award, created = CampaignAward.objects.get_or_create(campaign=campaign, user=user)
    if not created:
        return award

    data = progress.data or {}
    url = '/loyalty'

    if campaign.action_type == 'points' and campaign.points_amount:
        if campaign.points_mode == 'per_item':
            amount = campaign.points_amount * sum((data.get('matcher_qty') or {}).values())
        else:
            amount = campaign.points_amount
        if amount > 0:
            txn = _award_campaign_points(campaign, user, amount)
            award.points_awarded = amount
            award.points_transaction = txn

    elif campaign.action_type == 'discount_code':
        from loyalty.services.discounts import create_discount_code
        code = _generate_campaign_code()
        result = create_discount_code(user, campaign, code)
        if result:
            award.discount_code = code
            award.shopify_discount_id = str(result.get('discount_id', ''))

    elif campaign.action_type == 'raffle' and hasattr(campaign, 'raffle'):
        raffle = campaign.raffle
        RaffleEntry.objects.get_or_create(
            raffle=raffle,
            user=user,
            defaults={
                'ticket_count': _compute_tickets(campaign, data),
                'matched_products': data.get('matched_products') or [],
            },
        )
        url = f'/raffle/{raffle.id}'

    award.save()

    if campaign.notify_on_qualify:
        _send_qualify_notification(campaign, user, award, url)

    return award


def _default_qualify_title(campaign) -> str:
    if campaign.action_type == 'raffle':
        return 'Je doet mee met de loting!'
    if campaign.action_type == 'points':
        return 'Je hebt bonuspunten verdiend!'
    if campaign.action_type == 'discount_code':
        return 'Je hebt een kortingscode verdiend!'
    return campaign.name


def _default_qualify_body(campaign, award) -> str:
    if campaign.action_type == 'raffle' and hasattr(campaign, 'raffle'):
        base = f'Je loot mee voor: {campaign.raffle.prize_name}.'
    elif campaign.action_type == 'points' and award.points_awarded:
        base = f'Je hebt {award.points_awarded} punten verdiend met {campaign.name}.'
    elif campaign.action_type == 'discount_code' and award.discount_code:
        base = f'Gebruik code {award.discount_code} bij je volgende bestelling.'
    else:
        base = campaign.name
    if campaign.rule_sentence:
        return f'{base} {campaign.rule_sentence}'
    return base


def _send_qualify_notification(campaign, user, award, url: str):
    """Qualify notification via the notifications outbox; never raises."""
    title = campaign.qualify_title or _default_qualify_title(campaign)
    body = campaign.qualify_body or _default_qualify_body(campaign, award)
    kind = 'raffle' if campaign.action_type == 'raffle' else 'announcement'

    try:
        # Imported here, not at module level, so loyalty does not hard-depend
        # on the notifications app at import time.
        from notifications.services import send_notification

        # A member without any active push subscription gets a push SKIP,
        # which the kind's fallback policy does not treat as a failure — so
        # they would receive nothing at all. When the campaign opts in,
        # email exactly those members instead.
        email_policy = None
        if campaign.qualify_email_fallback:
            from notifications.models import PushSubscription
            has_push = PushSubscription.objects.filter(
                user=user, is_active=True
            ).exists()
            if not has_push:
                email_policy = 'always'

        delivery = send_notification(
            user,
            kind=kind,
            title=title,
            body=body,
            data={'url': url},
            dedupe_key=f'campaign:{campaign.id}:{user.id}:qualified',
            email_policy=email_policy,
        )
        delivery_id = getattr(delivery, 'id', None)
        if delivery_id:
            award.notified_delivery_id = delivery_id
            award.save(update_fields=['notified_delivery_id'])
    except Exception as e:
        logger.error(
            f"Qualify notification failed for campaign {campaign.id}, "
            f"user {user.email}: {e}",
            exc_info=True,
        )


# ============ Backfill ============

def run_backfill(campaign, dry_run: bool) -> Dict[str, Any]:
    """
    ONE shop-wide paginated order scan over the campaign window. Only orders
    of app users (matched on shopify_customer_id) count.

    dry_run returns the CampaignPreview.result shape without writing progress;
    a live run feeds each order through the same per-order application logic
    as the sync hook.

    Audience-mode campaigns take the selection path instead: no Shopify scan,
    the audience IS the qualified set.
    """
    if campaign.audience_mode == 'audience':
        return run_audience_backfill(campaign, dry_run)

    from users.models import User
    from users.services import ShopifyService

    resolve_product_matchers(campaign)

    shopify_service = ShopifyService()
    orders = shopify_service.get_shop_orders_in_window(
        campaign.window_start, campaign.window_end
    )
    orders_scanned = len(orders)

    users_by_customer = {
        str(u.shopify_customer_id): u
        for u in User.objects.exclude(
            shopify_customer_id__isnull=True
        ).exclude(shopify_customer_id='')
    }

    def _relevant(order):
        """(user, order_date) for an order that counts, else None."""
        if order.get('financial_status') != 'paid':
            return None
        customer_id = str((order.get('customer') or {}).get('id') or '')
        user = users_by_customer.get(customer_id)
        if user is None:
            return None
        order_date = _parse_order_date(order)
        if order_date is None:
            return None
        if not (campaign.window_start <= order_date <= campaign.window_end):
            return None
        return user, order_date

    # Shopify returns newest-first; apply oldest-first so cumulative progress
    # and the qualification moment are chronological.
    ordered = list(reversed(orders))

    if dry_run:
        per_user: Dict[int, Tuple[Any, Dict[str, Any]]] = {}
        for order in ordered:
            relevant = _relevant(order)
            if relevant is None:
                continue
            user, order_date = relevant
            _, data = per_user.setdefault(user.id, (user, _empty_data()))
            _accumulate_order(campaign, user, data, order, order_date)

        qualified = []
        near_misses = []
        for user, data in per_user.values():
            checks = _condition_checks(campaign, user, data)
            row = {
                'user_id': user.id,
                'email': user.email,
                'first_name': user.first_name or user.email.split('@')[0],
                'tickets': _compute_tickets(campaign, data),
                'matched': data.get('matched_products') or [],
            }
            if all(check['ok'] for check in checks.values()):
                qualified.append(row)
            elif _is_near_miss(checks):
                near_misses.append(row)

        return {
            'qualified_count': len(qualified),
            'users': qualified,
            'near_miss_count': len(near_misses),
            'near_miss_users': near_misses,
            'orders_scanned': orders_scanned,
        }

    for order in ordered:
        relevant = _relevant(order)
        if relevant is None:
            continue
        user, order_date = relevant
        try:
            with transaction.atomic():
                _apply_order_to_campaign(campaign, user, order, order_date)
        except Exception as e:
            logger.error(
                f"Backfill: campaign {campaign.id} failed for order "
                f"{order.get('name')}: {e}",
                exc_info=True,
            )

    from loyalty.models import CampaignProgress

    qualified_count = CampaignProgress.objects.filter(
        campaign=campaign, qualified_at__isnull=False
    ).count()
    logger.info(
        f"Backfill for campaign {campaign.id} ({campaign.name}): "
        f"{orders_scanned} orders scanned, {qualified_count} qualified"
    )
    return {
        'qualified_count': qualified_count,
        'orders_scanned': orders_scanned,
    }


# ============ Audience backfill (audience_mode='audience') ============

def run_audience_backfill(campaign, dry_run: bool) -> Dict[str, Any]:
    """
    Qualify the campaign's audience directly — no orders involved. DB-only,
    so it is cheap enough to re-run nightly for active campaigns (new filter
    matches get added); already-qualified members are skipped.
    """
    from users.models import User

    from loyalty.services.audience import audience_user_ids

    ids = audience_user_ids(campaign) or set()
    users = list(User.objects.filter(id__in=ids).order_by('id'))

    if dry_run:
        rows = [{
            'user_id': user.id,
            'email': user.email,
            'first_name': user.first_name or user.email.split('@')[0],
            'tickets': 1,
            'matched': [],
        } for user in users]
        return {
            'qualified_count': len(rows),
            'users': rows,
            'near_miss_count': 0,
            'near_miss_users': [],
            'orders_scanned': 0,
            'mode': 'audience',
        }

    newly_qualified = 0
    for user in users:
        try:
            with transaction.atomic():
                if _qualify_audience_member(campaign, user):
                    newly_qualified += 1
        except Exception as e:
            logger.error(
                f"Audience backfill: campaign {campaign.id} failed for "
                f"user {user.email}: {e}",
                exc_info=True,
            )

    from loyalty.models import CampaignProgress

    qualified_count = CampaignProgress.objects.filter(
        campaign=campaign, qualified_at__isnull=False
    ).count()
    logger.info(
        f"Audience backfill for campaign {campaign.id} ({campaign.name}): "
        f"{len(users)} in audience, {newly_qualified} newly qualified, "
        f"{qualified_count} total"
    )
    return {
        'qualified_count': qualified_count,
        'orders_scanned': 0,
        'newly_qualified': newly_qualified,
    }


def _qualify_audience_member(campaign, user) -> bool:
    """Idempotently qualify one audience member. True if newly qualified."""
    from loyalty.models import CampaignProgress

    progress, _ = CampaignProgress.objects.select_for_update().get_or_create(
        campaign=campaign, user=user
    )
    if progress.qualified_at is not None:
        return False
    if not progress.data:
        progress.data = _empty_data()
    progress.qualified_at = timezone.now()
    progress.save(update_fields=['data', 'qualified_at', 'updated_at'])
    fire_qualification(campaign, user, progress)
    return True
