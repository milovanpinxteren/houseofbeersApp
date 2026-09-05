"""Campagne Studio: staff-only admin pages for building, previewing and
monitoring loyalty campaigns & raffles.

Registered under /admin/campaign-studio/ (single include in config/urls.py).
Mirrors the analytics dashboard pattern: staff gating via the admin login,
async work dispatched to Celery with graceful degradation when no broker is
running (local dev falls back to a synchronous run), status polled
client-side.

Integration notes:
- Agent B's tasks (draw_campaign_raffle, check_winner_redemptions) are looked
  up with getattr on loyalty.tasks so this module imports cleanly before they
  exist; the buttons show a clear NL error until then.
- The Shopify product search goes through ShopifyService.search_products().
"""
import csv
import json
import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from loyalty import tasks as loyalty_tasks
from loyalty.models import (
    Campaign, CampaignAward, CampaignPreview, CampaignProgress,
    CampaignRaffle, CampaignRafflePrize, CampaignRaffleWinner, RaffleEntry,
)
from loyalty.services.campaigns import (
    _default_qualify_body, _default_qualify_title, build_rule_sentence,
)
from loyalty.tasks import campaign_backfill

logger = logging.getLogger(__name__)

MATCHER_TYPES = ('sku', 'product_id', 'title', 'tag', 'collection')

# (value, label) for the birthday-month audience filter; values are strings
# because they round-trip through the form.
MONTH_CHOICES = [
    ('1', 'januari'), ('2', 'februari'), ('3', 'maart'), ('4', 'april'),
    ('5', 'mei'), ('6', 'juni'), ('7', 'juli'), ('8', 'augustus'),
    ('9', 'september'), ('10', 'oktober'), ('11', 'november'), ('12', 'december'),
]


def _extract_product_id(value):
    """Pull the numeric Shopify product id out of whatever an admin pastes.

    Accepts a plain number, a gid://shopify/Product/... GID, or an admin/shop
    URL containing /products/<id>. Returns the id as a string, or None when
    the value doesn't look like a product reference at all.
    """
    value = (value or '').strip()
    if value.isdigit():
        return value
    match = re.match(r'^gid://shopify/Product/(\d+)$', value)
    if match:
        return match.group(1)
    match = re.search(r'/products/(\d+)(?:[/?#]|$)', value)
    if match:
        return match.group(1)
    return None

MATCHER_TYPE_LABELS = {
    'sku': 'SKU',
    'product_id': 'Product-ID',
    'title': 'Titel bevat',
    'tag': 'Tag',
    'collection': 'Collectie',
}

STATUS_LABELS = {
    'draft': 'Concept',
    'previewed': 'Preview klaar',
    'active': 'Actief',
    'completed': 'Afgerond',
    'archived': 'Gearchiveerd',
}

ACTION_LABELS = {
    'points': 'Punten',
    'discount_code': 'Kortingscode',
    'raffle': 'Loting',
}

# ============ Small helpers ============

def _raffle_or_none(campaign):
    try:
        return campaign.raffle
    except CampaignRaffle.DoesNotExist:
        return None


def _dispatch_task(task, *args, **kwargs):
    """
    Celery dispatch with a synchronous fallback when the broker is
    unreachable (local development without Redis), mirroring how the
    analytics dashboard degrades instead of breaking the page.
    Returns 'queued', 'sync', or 'failed' (the sync run raised — e.g.
    Shopify down); a failed run must show an NL message, never a 500.
    """
    try:
        task.delay(*args, **kwargs)
        return 'queued'
    except Exception as e:
        logger.warning(
            f"Celery unavailable ({e}); running {getattr(task, 'name', task)} synchronously"
        )
    try:
        task(*args, **kwargs)
        return 'sync'
    except Exception as e:
        logger.error(
            f"Synchronous run of {getattr(task, 'name', task)} failed: {e}",
            exc_info=True,
        )
        return 'failed'


def _parse_dt(value):
    """datetime-local input value -> aware datetime, or None."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _dt_input(value):
    """Aware datetime -> value for a datetime-local input."""
    if not value:
        return ''
    return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M')


# ============ Form parsing & validation ============

def _parse_prize_rows(raw, fulfillment_type, errors, fallback=None):
    """
    Parse the builder's hidden raffle_prizes JSON into CampaignRafflePrize
    field dicts — same idiom as product_matchers. Submitted order IS the draw
    order, so `ordering` is just the row index.

    A row may leave any part of its discount config blank and inherit the
    campaign's, so what gets validated is the EFFECTIVE config: the row's own
    fields merged over `fallback` exactly the way services/raffles.py
    `_discount_config()` merges them at draw time. Validating the row's raw
    fields instead would reject the most natural way to set up tiers — three
    different free products, each with its own product ID, all leaving the
    type on "Zelfde als campagne" — and would demand a campaign-level product
    ID that the draw would never read.

    A prize code that Shopify refuses only surfaces after the draw, when it is
    too late to fix, so this is the last line of defence.
    """
    fallback = fallback or {}
    try:
        parsed = json.loads(raw or '[]')
        if not isinstance(parsed, list):
            raise ValueError
    except ValueError:
        errors.append('De prijzen van de loting konden niet gelezen worden.')
        return []

    rows = []
    for index, row in enumerate(parsed):
        if not isinstance(row, dict):
            errors.append('Elke prijs heeft een naam nodig.')
            continue
        name = str(row.get('name') or '').strip()[:200]
        if not name:
            errors.append('Elke prijs heeft een naam nodig.')
            continue

        try:
            quantity = int(row.get('quantity') or 1)
        except (TypeError, ValueError):
            quantity = 0
        if quantity < 1:
            errors.append(f"Het aantal van prijs '{name}' moet minstens 1 zijn.")
            quantity = 1

        discount_type = str(row.get('discount_type') or '').strip()
        if discount_type and discount_type not in dict(Campaign.DISCOUNT_TYPE_CHOICES):
            errors.append(f"Kies een geldig kortingstype voor prijs '{name}'.")
            discount_type = ''

        raw_value = str(row.get('discount_value') or '').strip().replace(',', '.')
        discount_value = None
        if raw_value:
            try:
                discount_value = Decimal(raw_value)
            except InvalidOperation:
                errors.append(f"De waarde van de prijscode voor '{name}' is geen geldig bedrag.")

        product_gid = str(row.get('discount_product_gid') or '').strip()
        if product_gid:
            product_id = _extract_product_id(product_gid)
            if product_id is None:
                errors.append(
                    f"'{product_gid}' is geen geldig product-ID of product-GID "
                    f"voor prijs '{name}'."
                )
                product_gid = ''
            else:
                product_gid = f'gid://shopify/Product/{product_id}'

        raw_validity = str(row.get('discount_validity_days') or '').strip()
        validity_days = None
        if raw_validity:
            try:
                validity_days = int(raw_validity)
            except ValueError:
                errors.append(f"De geldigheid van de prijscode voor '{name}' is geen geldig getal.")
            else:
                if validity_days < 1:
                    errors.append(
                        f"De geldigheid van de prijscode voor '{name}' moet minstens 1 dag zijn."
                    )
                    validity_days = None

        if fulfillment_type == 'shopify_code':
            # What this tier will actually mint, campaign fallback included.
            eff_type = discount_type or fallback.get('discount_type') or ''
            eff_value = (
                discount_value if discount_value is not None
                else fallback.get('discount_value')
            )
            eff_gid = product_gid or fallback.get('discount_product_gid') or ''

            if not eff_type:
                errors.append(
                    f"Kies een kortingstype voor prijs '{name}' (of vul de "
                    f"kortingscode-instellingen van de campagne in)."
                )
            elif eff_type in ('fixed_amount', 'percentage'):
                if not eff_value or eff_value <= 0:
                    errors.append(
                        f"Vul de waarde van de prijscode voor '{name}' in (groter dan 0)."
                    )
                elif eff_type == 'percentage' and eff_value > 100:
                    errors.append(
                        f"Een kortingspercentage kan niet groter zijn dan 100 (prijs '{name}')."
                    )
            elif eff_type == 'free_product' and not eff_gid:
                errors.append(
                    f"Vul het Shopify product-ID in voor het gratis product bij prijs '{name}'."
                )

        rows.append({
            'name': name,
            'description': str(row.get('description') or '').strip(),
            'image_url': str(row.get('image_url') or '').strip(),
            'quantity': quantity,
            'ordering': index,
            'discount_type': discount_type,
            'discount_value': discount_value,
            'discount_product_gid': product_gid,
            'discount_validity_days': validity_days,
        })
    return rows


def _split_prizes(raffle_data):
    """
    Prize rows travel inside raffle_data but are their own model rows, so
    they must never reach CampaignRaffle(**raffle_data).
    """
    if not raffle_data:
        return []
    return raffle_data.pop('prizes', [])


PRIZE_FIELDS = ('name', 'description', 'image_url', 'quantity', 'ordering',
                'discount_type', 'discount_product_gid')


def _prize_signature(rows):
    """Comparable shape of submitted prize rows (see the drawn-raffle guard)."""
    return [tuple(str(row.get(field) or '') for field in PRIZE_FIELDS) for row in rows]


def _stored_prize_signature(raffle):
    if raffle is None or not raffle.pk:
        return []
    return _prize_signature([
        {field: getattr(prize, field) for field in PRIZE_FIELDS}
        for prize in raffle.prizes.all()
    ])


def _prize_rows_json(raffle):
    """Stored prize tiers as the builder's hidden-field JSON."""
    if raffle is None or not raffle.pk:
        return '[]'
    return json.dumps([{
        'name': prize.name,
        'description': prize.description,
        'image_url': prize.image_url,
        'quantity': prize.quantity,
        'discount_type': prize.discount_type,
        'discount_value': (
            '' if prize.discount_value is None else str(prize.discount_value)
        ),
        'discount_product_gid': prize.discount_product_gid,
        'discount_validity_days': (
            '' if prize.discount_validity_days is None
            else str(prize.discount_validity_days)
        ),
    } for prize in raffle.prizes.all()])


def _parse_campaign_form(post):
    """
    Parse builder POST data into (campaign field dict, raffle field dict or
    None, NL error list). All validation lives here so both the builder and
    the live-sentence endpoint share it.
    """
    errors = []

    def _int(name, label, default=None, minimum=None):
        raw = (post.get(name) or '').strip()
        if raw == '':
            return default
        try:
            value = int(raw)
        except ValueError:
            errors.append(f'{label} is geen geldig getal.')
            return default
        if minimum is not None and value < minimum:
            errors.append(f'{label} moet minstens {minimum} zijn.')
            return default
        return value

    def _dec(name, label):
        raw = (post.get(name) or '').strip().replace(',', '.')
        if raw == '':
            return None
        try:
            value = Decimal(raw)
        except InvalidOperation:
            errors.append(f'{label} is geen geldig bedrag.')
            return None
        if value < 0:
            errors.append(f'{label} kan niet negatief zijn.')
            return None
        return value

    name = (post.get('name') or '').strip()
    if not name:
        errors.append('Geef de campagne een naam.')

    window_start = _parse_dt(post.get('window_start'))
    window_end = _parse_dt(post.get('window_end'))
    if window_start is None:
        errors.append('Vul een geldige startdatum van de actieperiode in.')
    if window_end is None:
        errors.append('Vul een geldige einddatum van de actieperiode in.')
    if window_start and window_end and window_end <= window_start:
        errors.append('De einddatum moet na de startdatum liggen.')

    action_type = post.get('action_type')
    if action_type not in dict(Campaign.ACTION_TYPE_CHOICES):
        errors.append('Kies een actietype (punten, kortingscode of loting).')
        action_type = ''

    # --- Product matchers ---
    raw_matchers = post.get('product_matchers') or '[]'
    try:
        parsed_matchers = json.loads(raw_matchers)
        if not isinstance(parsed_matchers, list):
            raise ValueError
    except ValueError:
        parsed_matchers = []
        errors.append('De productvoorwaarden konden niet gelezen worden.')

    matchers = []
    for matcher in parsed_matchers:
        if not isinstance(matcher, dict):
            errors.append('Elke productregel heeft een geldig type en een waarde nodig.')
            continue
        mtype = matcher.get('type')
        value = str(matcher.get('value') or '').strip()
        if mtype not in MATCHER_TYPES or not value:
            errors.append('Elke productregel heeft een geldig type en een waarde nodig.')
            continue
        if mtype == 'product_id':
            # Order line items carry the numeric id, so a pasted GID or
            # product-URL must be reduced to that number or it never matches.
            product_id = _extract_product_id(value)
            if product_id is None:
                errors.append(
                    f"'{value}' is geen geldig product-ID (nummer, "
                    "gid://shopify/Product/… of product-URL)."
                )
                continue
            value = product_id
        row = {'type': mtype, 'value': value}
        # Display-only extra; the engine reads just type/value.
        label = str(matcher.get('label') or '').strip()
        if label:
            row['label'] = label[:200]
        matchers.append(row)

    min_distinct_products = _int(
        'min_distinct_products', 'Minimaal aantal verschillende producten',
        default=1, minimum=1,
    )
    min_total_quantity = _int(
        'min_total_quantity', 'Minimaal totaal aantal items', default=1, minimum=1,
    )
    if matchers and min_distinct_products and min_distinct_products > len(matchers):
        errors.append(
            f'Minimaal aantal verschillende producten ({min_distinct_products}) kan '
            f'niet groter zijn dan het aantal productregels ({len(matchers)}).'
        )

    min_order_value = _dec('min_order_value', 'Minimale bestelwaarde')
    min_total_spend = _dec('min_total_spend', 'Minimale totale besteding')
    min_order_count = _int('min_order_count', 'Minimaal aantal bestellingen', minimum=1)
    min_points_balance = _int('min_points_balance', 'Minimaal puntensaldo')
    registered_after = _parse_dt(post.get('registered_after'))

    # --- Audience (doelgroep) ---
    audience_mode = post.get('audience_mode') or 'orders'
    if audience_mode not in dict(Campaign.AUDIENCE_MODE_CHOICES):
        audience_mode = 'orders'

    audience_filters = {}
    aud_min_age = _int('aud_min_age', 'Minimale leeftijd (doelgroep)', minimum=1)
    if aud_min_age:
        audience_filters['min_age'] = aud_min_age
    aud_birthday_month = _int('aud_birthday_month', 'Verjaardagsmaand (doelgroep)')
    if aud_birthday_month:
        if 1 <= aud_birthday_month <= 12:
            audience_filters['birthday_month'] = aud_birthday_month
        else:
            errors.append('Kies een geldige verjaardagsmaand (1 t/m 12).')
    aud_min_app_age_days = _int(
        'aud_min_app_age_days', 'App-gebruiker sinds minstens (dagen)', minimum=1
    )
    if aud_min_app_age_days:
        audience_filters['min_app_age_days'] = aud_min_app_age_days
    aud_min_lifetime_orders = _int(
        'aud_min_lifetime_orders', 'Minimaal aantal bestellingen (doelgroep)', minimum=1
    )
    if aud_min_lifetime_orders:
        audience_filters['min_lifetime_orders'] = aud_min_lifetime_orders
    aud_active_within_days = _int(
        'aud_active_within_days', 'Actief in de afgelopen (dagen)', minimum=1
    )
    if aud_active_within_days:
        audience_filters['active_within_days'] = aud_active_within_days

    raw_manual = post.get('manual_users') or '[]'
    manual_user_ids = []
    try:
        parsed_manual = json.loads(raw_manual)
        if not isinstance(parsed_manual, list):
            raise ValueError
        for row in parsed_manual:
            user_id = row.get('id') if isinstance(row, dict) else row
            user_id = int(user_id)
            if user_id not in manual_user_ids:
                manual_user_ids.append(user_id)
    except (ValueError, TypeError):
        manual_user_ids = []
        errors.append('De geselecteerde klanten konden niet gelezen worden.')

    if audience_mode == 'audience' and not audience_filters and not manual_user_ids:
        errors.append(
            'Een doelgroep-campagne heeft minstens één doelgroepfilter of '
            'een handmatige klantselectie nodig.'
        )

    # --- Action config ---
    points_amount = _int('points_amount', 'Aantal punten', minimum=1)
    points_mode = post.get('points_mode') or 'fixed'
    if points_mode not in dict(Campaign.POINTS_MODE_CHOICES):
        points_mode = 'fixed'
    if audience_mode == 'audience':
        # No purchases involved: per-item points would compute to 0.
        points_mode = 'fixed'

    discount_type = post.get('discount_type') or ''
    if discount_type and discount_type not in dict(Campaign.DISCOUNT_TYPE_CHOICES):
        errors.append('Kies een geldig kortingstype.')
        discount_type = ''
    discount_value = _dec('discount_value', 'Kortingswaarde')
    discount_product_gid = (post.get('discount_product_gid') or '').strip()
    if discount_product_gid:
        # Accept a plain id, GID or product-URL; store the GID the Shopify
        # discount API expects.
        product_id = _extract_product_id(discount_product_gid)
        if product_id is not None:
            discount_product_gid = f'gid://shopify/Product/{product_id}'
        else:
            errors.append(
                f"'{discount_product_gid}' is geen geldig product-ID of "
                "product-GID voor het gratis product."
            )
            discount_product_gid = ''
    discount_validity_days = _int(
        'discount_validity_days', 'Geldigheid van de code (dagen)',
        default=30, minimum=1,
    )

    if action_type == 'points':
        if not points_amount:
            errors.append('Vul het aantal punten in (groter dan 0).')

    raffle_data = None
    if action_type == 'raffle':
        prize_name = (post.get('prize_name') or '').strip()
        if not prize_name:
            errors.append('Vul een prijsnaam in voor de loting.')
        elif len(prize_name) > 200:
            # CharField(max_length=200): without this the save blows up with a
            # DB-level DataError instead of a readable form error.
            errors.append('De prijsnaam mag maximaal 200 tekens lang zijn.')
            prize_name = prize_name[:200]
        num_winners = _int('num_winners', 'Aantal winnaars', default=1, minimum=1)
        entry_mode = post.get('entry_mode') or 'single'
        if entry_mode not in dict(CampaignRaffle.ENTRY_MODE_CHOICES):
            entry_mode = 'single'
        if audience_mode == 'audience':
            # Selection-based entry: everyone gets exactly one ticket.
            entry_mode = 'single'
        fulfillment_type = post.get('fulfillment_type') or 'manual'
        if fulfillment_type not in dict(CampaignRaffle.FULFILLMENT_TYPE_CHOICES):
            fulfillment_type = 'manual'
        prize_rows = _parse_prize_rows(
            post.get('raffle_prizes'), fulfillment_type, errors,
            fallback={
                'discount_type': discount_type,
                'discount_value': discount_value,
                'discount_product_gid': discount_product_gid,
            },
        )
        raffle_data = {
            'prize_name': prize_name,
            'prize_description': (post.get('prize_description') or '').strip(),
            'prize_image_url': (post.get('prize_image_url') or '').strip(),
            # With tiers the number of winners IS the number of prize slots;
            # keeping them in sync stops the rest of the UI from disagreeing
            # with the draw.
            'num_winners': (
                sum(row['quantity'] for row in prize_rows) if prize_rows
                else (num_winners or 1)
            ),
            'draw_at': _parse_dt(post.get('draw_at')),
            'entry_mode': entry_mode,
            'fulfillment_type': fulfillment_type,
            'send_reminder': bool(post.get('send_reminder')),
            'prizes': prize_rows,
        }

    # A discount config is required for the discount action, and for a raffle
    # whose prize is fulfilled with a Shopify code. Prize tiers are the
    # exception: every code then comes from a tier, and _parse_prize_rows has
    # already validated each tier's effective config (its own fields over the
    # campaign's). Re-checking the campaign level here would report a missing
    # product ID for a campaign-wide field the draw never reads.
    needs_discount = action_type == 'discount_code' or (
        raffle_data is not None
        and raffle_data['fulfillment_type'] == 'shopify_code'
        and not raffle_data['prizes']
    )
    if needs_discount:
        where = 'de kortingscode' if action_type == 'discount_code' else 'de prijscode van de loting'
        if not discount_type:
            errors.append(f'Kies een kortingstype voor {where}.')
        elif discount_type in ('fixed_amount', 'percentage'):
            if not discount_value or discount_value <= 0:
                errors.append(f'Vul de waarde van {where} in (groter dan 0).')
            elif discount_type == 'percentage' and discount_value > 100:
                errors.append('Een kortingspercentage kan niet groter zijn dan 100.')
        elif discount_type == 'free_product' and not discount_product_gid:
            errors.append(
                'Vul het Shopify product-ID in voor het gratis product '
                '(bijv. 123456 of gid://shopify/Product/123456).'
            )

    data = {
        'name': name,
        'description': (post.get('description') or '').strip(),
        'action_type': action_type,
        'window_start': window_start,
        'window_end': window_end,
        'product_matchers': matchers,
        'min_distinct_products': min_distinct_products or 1,
        'min_total_quantity': min_total_quantity or 1,
        'min_order_value': min_order_value,
        'min_total_spend': min_total_spend,
        'min_order_count': min_order_count,
        'first_order_only': bool(post.get('first_order_only')),
        'only_after_registration': bool(post.get('only_after_registration')),
        'requires_untappd': bool(post.get('requires_untappd')),
        'min_points_balance': min_points_balance,
        'registered_after': registered_after,
        'audience_mode': audience_mode,
        'audience_filters': audience_filters,
        'manual_user_ids': manual_user_ids,
        'points_amount': points_amount,
        'points_mode': points_mode,
        'discount_type': discount_type,
        'discount_value': discount_value,
        'discount_product_gid': discount_product_gid,
        'discount_validity_days': discount_validity_days or 30,
        'notify_on_qualify': bool(post.get('notify_on_qualify')),
        'qualify_email_fallback': bool(post.get('qualify_email_fallback')),
        'qualify_title': (post.get('qualify_title') or '').strip(),
        'qualify_body': (post.get('qualify_body') or '').strip(),
        'rule_sentence': (post.get('rule_sentence') or '').strip(),
    }
    return data, raffle_data, errors


def _manual_users_json(campaign):
    """Hand-picked users as [{'id', 'label'}] JSON for the builder chips."""
    ids = campaign.manual_user_ids or []
    if not ids:
        return '[]'
    from users.models import User
    labels = {u.id: u.email for u in User.objects.filter(id__in=ids)}
    return json.dumps([
        {'id': user_id, 'label': labels.get(user_id, f'gebruiker #{user_id}')}
        for user_id in ids
    ])


def _form_values(campaign=None, raffle=None, post=None):
    """One flat dict of input-ready values for the builder template."""
    if post is not None:
        values = {key: post.get(key, '') for key in (
            'name', 'description', 'action_type', 'window_start', 'window_end',
            'product_matchers', 'min_distinct_products', 'min_total_quantity',
            'min_order_value', 'min_total_spend', 'min_order_count',
            'min_points_balance', 'registered_after', 'points_amount',
            'points_mode', 'discount_type', 'discount_value',
            'discount_product_gid', 'discount_validity_days', 'qualify_title',
            'qualify_body', 'rule_sentence', 'prize_name', 'prize_description',
            'prize_image_url', 'num_winners', 'draw_at', 'entry_mode',
            'fulfillment_type', 'raffle_prizes', 'aud_min_age',
            'aud_birthday_month', 'aud_min_app_age_days',
            'aud_min_lifetime_orders', 'aud_active_within_days',
        )}
        for checkbox in ('first_order_only', 'only_after_registration',
                         'requires_untappd', 'notify_on_qualify',
                         'qualify_email_fallback', 'send_reminder'):
            values[checkbox] = bool(post.get(checkbox))
        values['audience_mode'] = post.get('audience_mode') or 'orders'
        values['manual_users'] = post.get('manual_users') or '[]'
        values['raffle_prizes'] = post.get('raffle_prizes') or '[]'
        return values

    def _num(value):
        return '' if value is None else str(value)

    if campaign is None:
        return {
            'name': '', 'description': '', 'action_type': '',
            'window_start': '', 'window_end': '', 'product_matchers': '[]',
            'min_distinct_products': '1', 'min_total_quantity': '1',
            'min_order_value': '', 'min_total_spend': '', 'min_order_count': '',
            'min_points_balance': '', 'registered_after': '',
            'points_amount': '', 'points_mode': 'fixed', 'discount_type': '',
            'discount_value': '', 'discount_product_gid': '',
            'discount_validity_days': '30', 'qualify_title': '',
            'qualify_body': '', 'rule_sentence': '', 'prize_name': '',
            'prize_description': '', 'prize_image_url': '', 'num_winners': '1',
            'draw_at': '', 'entry_mode': 'single', 'fulfillment_type': 'manual',
            'raffle_prizes': '[]',
            'first_order_only': False, 'only_after_registration': False,
            'requires_untappd': False, 'notify_on_qualify': True,
            'qualify_email_fallback': False, 'send_reminder': True,
            'audience_mode': 'orders', 'aud_min_age': '',
            'aud_birthday_month': '', 'aud_min_app_age_days': '',
            'aud_min_lifetime_orders': '', 'aud_active_within_days': '',
            'manual_users': '[]',
        }

    values = {
        'name': campaign.name,
        'description': campaign.description,
        'action_type': campaign.action_type,
        'window_start': _dt_input(campaign.window_start),
        'window_end': _dt_input(campaign.window_end),
        'product_matchers': json.dumps(campaign.product_matchers or []),
        'min_distinct_products': _num(campaign.min_distinct_products),
        'min_total_quantity': _num(campaign.min_total_quantity),
        'min_order_value': _num(campaign.min_order_value),
        'min_total_spend': _num(campaign.min_total_spend),
        'min_order_count': _num(campaign.min_order_count),
        'min_points_balance': _num(campaign.min_points_balance),
        'registered_after': _dt_input(campaign.registered_after),
        'points_amount': _num(campaign.points_amount),
        'points_mode': campaign.points_mode,
        'discount_type': campaign.discount_type,
        'discount_value': _num(campaign.discount_value),
        'discount_product_gid': campaign.discount_product_gid,
        'discount_validity_days': _num(campaign.discount_validity_days),
        'qualify_title': campaign.qualify_title,
        'qualify_body': campaign.qualify_body,
        'rule_sentence': campaign.rule_sentence,
        'first_order_only': campaign.first_order_only,
        'only_after_registration': campaign.only_after_registration,
        'requires_untappd': campaign.requires_untappd,
        'notify_on_qualify': campaign.notify_on_qualify,
        'qualify_email_fallback': campaign.qualify_email_fallback,
        'audience_mode': campaign.audience_mode,
        'aud_min_age': _num((campaign.audience_filters or {}).get('min_age')),
        'aud_birthday_month': _num((campaign.audience_filters or {}).get('birthday_month')),
        'aud_min_app_age_days': _num((campaign.audience_filters or {}).get('min_app_age_days')),
        'aud_min_lifetime_orders': _num((campaign.audience_filters or {}).get('min_lifetime_orders')),
        'aud_active_within_days': _num((campaign.audience_filters or {}).get('active_within_days')),
        'manual_users': _manual_users_json(campaign),
        'prize_name': raffle.prize_name if raffle else '',
        'prize_description': raffle.prize_description if raffle else '',
        'prize_image_url': raffle.prize_image_url if raffle else '',
        'num_winners': _num(raffle.num_winners) if raffle else '1',
        'draw_at': _dt_input(raffle.draw_at) if raffle else '',
        'entry_mode': raffle.entry_mode if raffle else 'single',
        'fulfillment_type': raffle.fulfillment_type if raffle else 'manual',
        'send_reminder': raffle.send_reminder if raffle else True,
        'raffle_prizes': _prize_rows_json(raffle),
    }
    return values


def _condition_rows(campaign):
    """Readable NL list of the configured conditions, for preview/monitor."""
    from loyalty.services.audience import describe_filters, has_audience

    rows = []

    if campaign.audience_mode == 'audience':
        rows.append(('Doelgroep', 'Geselecteerde leden — geen aankoop nodig'))
        for description in describe_filters(campaign):
            rows.append(('Doelgroepfilter', f'Ieder lid dat {description}'))
        if campaign.manual_user_ids:
            rows.append((
                'Handmatig geselecteerd',
                f'{len(campaign.manual_user_ids)} klanten',
            ))
        return rows

    if has_audience(campaign):
        for description in describe_filters(campaign):
            rows.append(('Doelgroepfilter', f'Alleen leden die {description}'))
        if campaign.manual_user_ids:
            rows.append((
                'Doelgroep',
                f'Plus {len(campaign.manual_user_ids)} handmatig geselecteerde klanten',
            ))
    for matcher in campaign.product_matchers or []:
        label = MATCHER_TYPE_LABELS.get(matcher.get('type'), matcher.get('type'))
        display = matcher.get('label') or matcher.get('value')
        rows.append(('Product', f"{label}: {display}"))
    if campaign.product_matchers and campaign.min_distinct_products > 1:
        rows.append(('Minimaal verschillende producten', str(campaign.min_distinct_products)))
    if campaign.min_total_quantity > 1:
        rows.append(('Minimaal totaal aantal items', str(campaign.min_total_quantity)))
    if campaign.min_order_value is not None:
        rows.append(('Minimale bestelwaarde', f'€{campaign.min_order_value}'))
    if campaign.min_total_spend is not None:
        rows.append(('Minimale totale besteding', f'€{campaign.min_total_spend}'))
    if campaign.min_order_count:
        rows.append(('Minimaal aantal bestellingen', str(campaign.min_order_count)))
    if campaign.first_order_only:
        rows.append(('Eerste bestelling', 'Alleen allereerste bestelling telt'))
    if campaign.only_after_registration:
        rows.append(('Registratie', 'Alleen bestellingen na app-registratie'))
    if campaign.requires_untappd:
        rows.append(('Untappd', 'Gekoppeld Untappd-account vereist'))
    if campaign.min_points_balance is not None:
        rows.append(('Minimaal puntensaldo', str(campaign.min_points_balance)))
    if campaign.registered_after:
        rows.append(('Geregistreerd na', _dt_input(campaign.registered_after).replace('T', ' ')))
    if not rows:
        rows.append(('Voorwaarden', 'Elke betaalde bestelling in de periode telt'))
    return rows


# ============ Campaign list ============

@staff_member_required
def campaign_list(request):
    qualified = dict(
        CampaignProgress.objects.filter(qualified_at__isnull=False)
        .values_list('campaign')
        .annotate(n=Count('id'))
    )
    entries = dict(
        RaffleEntry.objects.values_list('raffle__campaign')
        .annotate(n=Count('id'))
    )
    winners = dict(
        CampaignRaffleWinner.objects.values_list('raffle__campaign')
        .annotate(n=Count('id'))
    )

    rows = []
    for campaign in Campaign.objects.all():
        raffle = _raffle_or_none(campaign)
        rows.append({
            'campaign': campaign,
            'raffle': raffle,
            'status_label': STATUS_LABELS.get(campaign.status, campaign.status),
            'action_label': ACTION_LABELS.get(campaign.action_type, campaign.action_type),
            'qualified': qualified.get(campaign.id, 0),
            'entries': entries.get(campaign.id, 0),
            'winners': winners.get(campaign.id, 0),
            'editable': campaign.status not in ('completed', 'archived'),
        })

    return render(request, 'loyalty/studio/list.html', {
        'title': 'Campagne Studio',
        'rows': rows,
    })


# ============ Builder ============

@staff_member_required
def campaign_builder(request, pk=None):
    campaign = get_object_or_404(Campaign, pk=pk) if pk is not None else None
    raffle = _raffle_or_none(campaign) if campaign else None

    if campaign and campaign.status in ('completed', 'archived'):
        state = 'afgerond' if campaign.status == 'completed' else 'gearchiveerd'
        messages.error(
            request,
            f'"{campaign.name}" is {state} en kan niet meer bewerkt worden. '
            f'Maak een nieuwe campagne om iets vergelijkbaars te starten.'
        )
        return redirect('studio:campaign_monitor', pk=campaign.pk)

    errors = []
    if request.method == 'POST':
        data, raffle_data, errors = _parse_campaign_form(request.POST)
        prize_rows = _split_prizes(raffle_data)

        if (campaign and campaign.action_type == 'raffle'
                and data['action_type'] != 'raffle'
                and raffle and raffle.entries.exists()):
            errors.append(
                'Het actietype kan niet meer gewijzigd worden: er zijn al loten uitgedeeld.'
            )

        # A drawn raffle's prizes are already handed out; editing the rows
        # would rewrite what winners were told they won. (Normally
        # unreachable: a draw completes the campaign and completed campaigns
        # are not editable at all.)
        if (raffle and raffle.status == 'drawn'
                and _prize_signature(prize_rows) != _stored_prize_signature(raffle)):
            errors.append(
                'De prijzen kunnen niet meer gewijzigd worden: de loting is al getrokken.'
            )

        if not errors:
            is_new = campaign is None
            if campaign is None:
                campaign = Campaign()
            for field, value in data.items():
                setattr(campaign, field, value)
            campaign.save()  # marks preview_stale on condition edits (model logic)

            if raffle_data is not None:
                raffle, _ = CampaignRaffle.objects.update_or_create(
                    campaign=campaign, defaults=raffle_data
                )
                if raffle.status != 'drawn':
                    # Full replace, like product_matchers: the rows carry no
                    # id and only a not-yet-drawn raffle can be reshuffled
                    # (winners keep their prize via SET_NULL either way).
                    raffle.prizes.all().delete()
                    for row in prize_rows:
                        CampaignRafflePrize.objects.create(raffle=raffle, **row)
            elif raffle is not None:
                # Action changed away from raffle; safe because the entries
                # check above already blocked the risky case.
                raffle.delete()
                raffle = None

            if not data['rule_sentence']:
                sentence = build_rule_sentence(campaign)
                # .update() so this bookkeeping write can't re-trip the
                # preview_stale logic in Campaign.save().
                Campaign.objects.filter(pk=campaign.pk).update(rule_sentence=sentence)
                campaign.rule_sentence = sentence

            messages.success(
                request,
                'Campagne aangemaakt. Draai nu een preview om te zien wie er kwalificeert.'
                if is_new else 'Campagne opgeslagen.'
            )
            return redirect('studio:campaign_preview', pk=campaign.pk)

        form = _form_values(post=request.POST)
    else:
        form = _form_values(campaign=campaign, raffle=raffle)

    return render(request, 'loyalty/studio/builder.html', {
        'title': f'{campaign.name} bewerken' if campaign else 'Nieuwe campagne',
        'campaign': campaign,
        'raffle': raffle,
        'form': form,
        'errors': errors,
        'matcher_type_labels': MATCHER_TYPE_LABELS,
        'is_active_campaign': bool(campaign and campaign.status == 'active'),
        'discount_type_choices': Campaign.DISCOUNT_TYPE_CHOICES,
        'points_mode_choices': Campaign.POINTS_MODE_CHOICES,
        'entry_mode_choices': CampaignRaffle.ENTRY_MODE_CHOICES,
        'fulfillment_type_choices': CampaignRaffle.FULFILLMENT_TYPE_CHOICES,
        'month_choices': MONTH_CHOICES,
    })


@staff_member_required
@require_POST
def rule_sentence_preview(request):
    """Live NL rule sentence for the (unsaved) builder form values."""
    data, raffle_data, _errors = _parse_campaign_form(request.POST)
    prize_rows = _split_prizes(raffle_data)
    if not data['window_start'] or not data['window_end']:
        return JsonResponse({'sentence': '', 'error': 'Vul eerst de actieperiode in.'})
    if not data['action_type']:
        return JsonResponse({'sentence': '', 'error': 'Kies eerst een actietype.'})

    campaign = Campaign(**{k: v for k, v in data.items()})
    if raffle_data is not None:
        try:
            raffle = CampaignRaffle(**raffle_data)
            # Unsaved parent: no reverse manager, so the sentence builder
            # reads the tiers off _preview_prizes instead.
            raffle._preview_prizes = [
                CampaignRafflePrize(**row) for row in prize_rows
            ]
            campaign.raffle = raffle
        except Exception:  # pragma: no cover - descriptor quirks only
            pass
    try:
        sentence = build_rule_sentence(campaign)
    except Exception as e:
        logger.warning(f"Rule sentence preview failed: {e}")
        return JsonResponse({'sentence': '', 'error': 'De zin kon nog niet gemaakt worden.'})
    return JsonResponse({'sentence': sentence})


@staff_member_required
@require_GET
def product_search(request):
    """Live Shopify product search for the matcher picker.

    A query that consists purely of product references (numeric ids, GIDs
    or product-URLs, separated by whitespace/commas) is resolved as an id
    lookup instead of a title search, so admins can paste ids straight into
    the search bar. The response then carries id_lookup=true plus the ids
    Shopify didn't recognize.
    """
    query = (request.GET.get('q') or '').strip()
    if len(query) < 2:
        return JsonResponse({'products': []})

    from users.services import ShopifyService

    tokens = [t for t in re.split(r'[\s,;]+', query) if t]
    ids = [_extract_product_id(t) for t in tokens]
    if tokens and all(pid is not None for pid in ids):
        ids = list(dict.fromkeys(ids))[:25]
        products = ShopifyService().get_products_by_ids(ids)
        if products is None:
            return JsonResponse(
                {'products': [], 'error': 'Shopify-zoekopdracht mislukt.'}, status=502
            )
        found = {p['id'] for p in products}
        missing = [pid for pid in ids if pid not in found]
        return JsonResponse(
            {'products': products, 'id_lookup': True, 'missing': missing}
        )

    products = ShopifyService().search_products(query, limit=15)
    if products is None:
        return JsonResponse(
            {'products': [], 'error': 'Shopify-zoekopdracht mislukt.'}, status=502
        )
    return JsonResponse({'products': products})


@staff_member_required
@require_GET
def user_search(request):
    """Live app-user search for the audience picker (email or name)."""
    query = (request.GET.get('q') or '').strip()
    if len(query) < 2:
        return JsonResponse({'users': []})

    from django.db.models import Q

    from users.models import User

    users = User.objects.filter(is_active=True).filter(
        Q(email__icontains=query)
        | Q(first_name__icontains=query)
        | Q(last_name__icontains=query)
    ).order_by('email')[:15]
    return JsonResponse({'users': [
        {
            'id': user.id,
            'email': user.email,
            'name': f'{user.first_name} {user.last_name}'.strip(),
        }
        for user in users
    ]})


@staff_member_required
@require_POST
def audience_count(request):
    """Live audience size for the builder's Doelgroep section."""
    data, _raffle_data, _errors = _parse_campaign_form(request.POST)

    from loyalty.services.audience import audience_user_ids

    probe = Campaign(
        audience_mode=data['audience_mode'],
        audience_filters=data['audience_filters'],
        manual_user_ids=data['manual_user_ids'],
    )
    ids = audience_user_ids(probe)
    return JsonResponse({
        'restricted': ids is not None,
        'count': None if ids is None else len(ids),
    })


# ============ Preview & activation ============

@staff_member_required
def campaign_preview_page(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    raffle = _raffle_or_none(campaign)

    latest = campaign.previews.first()
    latest_done = campaign.previews.filter(status='done').first()
    running = bool(latest and latest.status in ('pending', 'running'))

    activation_blockers = []
    if campaign.status == 'draft':
        activation_blockers.append('Draai eerst een geslaagde preview.')
    elif campaign.status != 'previewed':
        activation_blockers.append(
            f'Alleen een campagne met status "Preview klaar" kan geactiveerd worden '
            f'(nu: {STATUS_LABELS.get(campaign.status, campaign.status)}).'
        )
    if campaign.preview_stale and campaign.status in ('draft', 'previewed'):
        activation_blockers.append(
            'De voorwaarden zijn gewijzigd na de laatste preview. '
            'Draai een nieuwe preview om te activeren.'
        )
    if campaign.action_type == 'raffle' and raffle is None:
        activation_blockers.append('Deze lotingscampagne heeft nog geen prijsconfiguratie.')
    if campaign.window_end < timezone.now():
        activation_blockers.append(
            'De actieperiode is al voorbij. Verleng de einddatum om deze '
            'campagne te kunnen activeren.'
        )

    return render(request, 'loyalty/studio/preview.html', {
        'title': f'Preview — {campaign.name}',
        'campaign': campaign,
        'raffle': raffle,
        'status_label': STATUS_LABELS.get(campaign.status, campaign.status),
        'action_label': ACTION_LABELS.get(campaign.action_type, campaign.action_type),
        'condition_rows': _condition_rows(campaign),
        'latest_preview': latest,
        'latest_done_preview': latest_done,
        'preview_running': running,
        'can_activate': not activation_blockers,
        'activation_blockers': activation_blockers,
        'stale': campaign.preview_stale,
    })


@staff_member_required
@require_POST
def run_preview(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if campaign.status in ('completed', 'archived'):
        messages.error(request, 'Deze campagne is afgerond; een preview heeft geen zin meer.')
        return redirect('studio:campaign_preview', pk=pk)

    recent_cutoff = timezone.now() - timedelta(minutes=10)
    if campaign.previews.filter(
        status__in=('pending', 'running'), created_at__gte=recent_cutoff
    ).exists():
        messages.warning(request, 'Er draait al een preview voor deze campagne.')
        return redirect('studio:campaign_preview', pk=pk)

    preview = CampaignPreview.objects.create(campaign=campaign, status='pending')
    try:
        mode = _dispatch_task(campaign_backfill, campaign.id, preview_id=preview.id)
    except Exception as e:
        preview.status = 'failed'
        preview.error = str(e)
        preview.finished_at = timezone.now()
        preview.save(update_fields=['status', 'error', 'finished_at'])
        messages.error(request, f'Preview kon niet gestart worden: {e}')
        return redirect('studio:campaign_preview', pk=pk)

    if mode == 'failed':
        # The task marks the preview failed itself in its normal error path;
        # this covers a crash before it got that far.
        if CampaignPreview.objects.filter(pk=preview.pk, status='pending').exists():
            preview.status = 'failed'
            preview.error = 'Preview kon niet uitgevoerd worden.'
            preview.finished_at = timezone.now()
            preview.save(update_fields=['status', 'error', 'finished_at'])
        messages.error(request, 'Preview mislukt — probeer het opnieuw.')
    elif mode == 'queued':
        messages.info(request, 'Preview gestart — dit kan even duren, de pagina ververst vanzelf.')
    else:
        messages.info(request, 'Preview direct uitgevoerd (geen Celery-worker actief).')
    return redirect('studio:campaign_preview', pk=pk)


@staff_member_required
@require_GET
def preview_status(request, pk):
    """Poll endpoint for the preview page."""
    campaign = get_object_or_404(Campaign, pk=pk)
    preview_id = request.GET.get('preview_id')
    if preview_id:
        preview = campaign.previews.filter(id=preview_id).first()
    else:
        preview = campaign.previews.first()
    if preview is None:
        return JsonResponse({'status': 'none'})
    return JsonResponse({
        'id': preview.id,
        'status': preview.status,
        'error': preview.error,
        'finished_at': preview.finished_at.isoformat() if preview.finished_at else None,
        'campaign_status': campaign.status,
        'preview_stale': campaign.preview_stale,
    })


@staff_member_required
@require_POST
def send_test_notification(request, pk):
    """Send the qualify notification to the logged-in admin only."""
    campaign = get_object_or_404(Campaign, pk=pk)
    preview = campaign.previews.filter(status='done').first()
    if preview is None:
        messages.error(
            request, 'Draai eerst een geslaagde preview voordat je een test stuurt.'
        )
        return redirect('studio:campaign_preview', pk=pk)

    raffle = _raffle_or_none(campaign)
    title = campaign.qualify_title or _default_qualify_title(campaign)
    transient_award = CampaignAward(
        campaign=campaign, user=request.user,
        points_awarded=campaign.points_amount or 0,
    )
    body = campaign.qualify_body or _default_qualify_body(campaign, transient_award)
    url = f'/raffle/{raffle.id}' if raffle else '/loyalty'
    kind = 'raffle' if campaign.action_type == 'raffle' else 'announcement'

    try:
        from notifications.services import send_notification

        send_notification(
            request.user,
            kind=kind,
            title=title,
            body=body,
            data={'url': url},
            dedupe_key=f'campaign:{campaign.id}:test:{request.user.id}:{preview.id}',
        )
        messages.success(request, f'Testnotificatie verstuurd naar {request.user.email}.')
    except Exception as e:
        logger.error(f"Test notification failed for campaign {pk}: {e}", exc_info=True)
        messages.error(request, f'Testnotificatie mislukt: {e}')
    return redirect('studio:campaign_preview', pk=pk)


@staff_member_required
@require_POST
def activate_campaign(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)

    if campaign.status != 'previewed':
        messages.error(
            request,
            'Alleen een campagne met een geslaagde preview kan geactiveerd worden.'
        )
        return redirect('studio:campaign_preview', pk=pk)
    if campaign.preview_stale:
        messages.error(
            request,
            'De voorwaarden zijn gewijzigd na de laatste preview. '
            'Draai eerst een nieuwe preview.'
        )
        return redirect('studio:campaign_preview', pk=pk)
    if campaign.action_type == 'raffle' and _raffle_or_none(campaign) is None:
        messages.error(request, 'Deze lotingscampagne heeft nog geen prijsconfiguratie.')
        return redirect('studio:campaign_preview', pk=pk)
    if campaign.window_end < timezone.now():
        # An ended window would qualify people (the audience backfill does
        # not consult the window) and then be auto-completed the same night.
        messages.error(
            request,
            'De actieperiode is al voorbij. Verleng de einddatum om deze '
            'campagne te kunnen activeren.'
        )
        return redirect('studio:campaign_preview', pk=pk)

    campaign.status = 'active'
    campaign.save(update_fields=['status', 'updated_at'])

    mode = _dispatch_task(campaign_backfill, campaign.id)
    if mode == 'failed':
        messages.warning(
            request,
            'Campagne geactiveerd, maar de backfill is mislukt (Shopify niet '
            'bereikbaar?). Nieuwe bestellingen tellen gewoon mee; draai de '
            'backfill later opnieuw via een preview + activering of de CLI.'
        )
        return redirect('studio:campaign_monitor', pk=pk)
    suffix = (
        'De backfill draait op de achtergrond.' if mode == 'queued'
        else 'De backfill is direct uitgevoerd (geen Celery-worker actief).'
    )
    messages.success(
        request,
        f'Campagne geactiveerd. {suffix} Gebruikers die voldoen ontvangen nu '
        f'echte notificaties.'
    )
    return redirect('studio:campaign_monitor', pk=pk)


@staff_member_required
@require_POST
def deactivate_campaign(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if campaign.status != 'active':
        messages.error(request, 'Alleen een actieve campagne kan gedeactiveerd worden.')
        return redirect('studio:campaign_monitor', pk=pk)
    campaign.status = 'completed'
    campaign.save(update_fields=['status', 'updated_at'])
    messages.success(
        request,
        'Campagne gedeactiveerd (afgerond). Er komen geen nieuwe kwalificaties meer bij.'
    )
    return redirect('studio:campaign_monitor', pk=pk)


@staff_member_required
@require_POST
def archive_campaign(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if campaign.status == 'archived':
        messages.warning(request, 'Deze campagne is al gearchiveerd.')
    else:
        campaign.status = 'archived'
        campaign.save(update_fields=['status', 'updated_at'])
        messages.success(request, f'"{campaign.name}" gearchiveerd.')
    return redirect('studio:campaign_list')


# ============ Monitor ============

def _campaign_deliveries(campaign):
    """
    Notification deliveries for this campaign (test sends excluded). Returns
    (queryset, importable) — importable False when the notifications app is
    unavailable, so the monitor still renders.
    """
    try:
        from notifications.models import NotificationDelivery
    except Exception:  # pragma: no cover - notifications app always present
        return None, False
    qs = NotificationDelivery.objects.filter(
        dedupe_key__startswith=f'campaign:{campaign.id}:'
    ).exclude(dedupe_key__contains=':test:')
    return qs, True


def _monitor_data(campaign):
    """Funnel stages + per-user rows for the monitor page and CSV export."""
    raffle = _raffle_or_none(campaign)
    deliveries, has_notifications = _campaign_deliveries(campaign)

    push_sent_users = set()
    email_sent_users = set()
    qualify_by_user = {}
    if has_notifications:
        for delivery in deliveries:
            if delivery.push_status == 'sent':
                push_sent_users.add(delivery.user_id)
            if delivery.email_status == 'sent':
                email_sent_users.add(delivery.user_id)
            if delivery.dedupe_key.endswith(':qualified'):
                qualify_by_user[delivery.user_id] = delivery
    notified_users = push_sent_users | email_sent_users

    winners_by_user = {}
    winners = []
    if raffle:
        winners = list(
            raffle.winners.select_related('user', 'prize').order_by('drawn_at', 'id')
        )
        winners_by_user = {w.user_id: w for w in winners}

    rows = []
    if raffle:
        entries = raffle.entries.select_related('user').order_by('-ticket_count', 'created_at')
        for entry in entries:
            winner = winners_by_user.get(entry.user_id)
            qualify = qualify_by_user.get(entry.user_id)
            rows.append({
                'user': entry.user,
                'email': entry.user.email,
                'first_name': entry.user.first_name or entry.user.email.split('@')[0],
                'tickets': entry.ticket_count,
                'matched': entry.matched_products or [],
                'notified_push': entry.user_id in push_sent_users,
                'notified_email': entry.user_id in email_sent_users,
                'qualify_delivery': qualify,
                'seen': entry.seen_at,
                'result_seen': entry.result_seen_at,
                'winner': winner,
            })
        entered = len(rows)
        opened = sum(1 for r in rows if r['seen'])
        watched = sum(1 for r in rows if r['result_seen'])
    else:
        progress_rows = CampaignProgress.objects.filter(
            campaign=campaign, qualified_at__isnull=False
        ).select_related('user').order_by('qualified_at')
        awards = {
            a.user_id: a
            for a in CampaignAward.objects.filter(campaign=campaign)
        }
        for progress in progress_rows:
            award = awards.get(progress.user_id)
            qualify = qualify_by_user.get(progress.user_id)
            rows.append({
                'user': progress.user,
                'email': progress.user.email,
                'first_name': progress.user.first_name or progress.user.email.split('@')[0],
                'tickets': None,
                'matched': (progress.data or {}).get('matched_products') or [],
                'notified_push': progress.user_id in push_sent_users,
                'notified_email': progress.user_id in email_sent_users,
                'qualify_delivery': qualify,
                'qualified_at': progress.qualified_at,
                'award': award,
                'seen': None,
                'result_seen': None,
                'winner': None,
            })
        entered = len(rows)
        opened = watched = None

    redeemed = None
    if raffle:
        redeemed = sum(
            1 for w in winners
            if w.redeemed_at or w.fulfillment_status == 'fulfilled'
        )

    funnel = [{
        'key': 'entered',
        'label': 'Ingeloot' if raffle else 'Gekwalificeerd',
        'count': entered,
        'sub': '',
    }, {
        'key': 'notified',
        'label': 'Genotificeerd',
        'count': len(notified_users) if has_notifications else 0,
        'sub': f'{len(push_sent_users)} push · {len(email_sent_users)} e-mail'
               if has_notifications else 'notificaties onbekend',
    }]
    if raffle:
        funnel.append({'key': 'opened', 'label': 'Kaart geopend', 'count': opened, 'sub': ''})
        funnel.append({'key': 'watched', 'label': 'Trekking bekeken', 'count': watched, 'sub': ''})
        funnel.append({
            'key': 'redeemed', 'label': 'Verzilverd / afgehandeld',
            'count': redeemed, 'sub': f'van {len(winners)} winnaars',
        })

    return {
        'raffle': raffle,
        'funnel': funnel,
        'rows': rows,
        'winners': winners,
    }


@staff_member_required
def campaign_monitor(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    data = _monitor_data(campaign)
    raffle = data['raffle']

    draw_available = getattr(loyalty_tasks, 'draw_campaign_raffle', None) is not None
    redemptions_available = getattr(loyalty_tasks, 'check_winner_redemptions', None) is not None

    return render(request, 'loyalty/studio/monitor.html', {
        'title': f'Monitor — {campaign.name}',
        'campaign': campaign,
        'raffle': raffle,
        'status_label': STATUS_LABELS.get(campaign.status, campaign.status),
        'action_label': ACTION_LABELS.get(campaign.action_type, campaign.action_type),
        'condition_rows': _condition_rows(campaign),
        'funnel': data['funnel'],
        'rows': data['rows'],
        'winners': data['winners'],
        'can_draw': bool(raffle and raffle.status == 'open' and campaign.status == 'active'),
        'draw_available': draw_available,
        'redemptions_available': redemptions_available,
        'editable': campaign.status not in ('completed', 'archived'),
    })


@staff_member_required
@require_POST
def draw_now(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    raffle = _raffle_or_none(campaign)
    if raffle is None or raffle.status != 'open':
        messages.error(request, 'Deze loting is al getrokken of bestaat niet.')
        return redirect('studio:campaign_monitor', pk=pk)
    if campaign.status != 'active':
        messages.error(request, 'Alleen een actieve campagne kan getrokken worden.')
        return redirect('studio:campaign_monitor', pk=pk)

    task = getattr(loyalty_tasks, 'draw_campaign_raffle', None)
    if task is None:
        messages.error(
            request,
            'De trekkings-taak (draw_campaign_raffle) is nog niet beschikbaar.'
        )
        return redirect('studio:campaign_monitor', pk=pk)

    mode = _dispatch_task(task, raffle.id)
    if mode == 'queued':
        messages.success(request, 'Trekking gestart — ververs de pagina voor het resultaat.')
    elif mode == 'failed':
        messages.error(request, 'De trekking is mislukt — probeer het opnieuw.')
    else:
        messages.success(request, 'Trekking direct uitgevoerd.')
    return redirect('studio:campaign_monitor', pk=pk)


@staff_member_required
@require_POST
def check_redemptions(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    task = getattr(loyalty_tasks, 'check_winner_redemptions', None)
    if task is None:
        messages.error(
            request,
            'De verzilver-check (check_winner_redemptions) is nog niet beschikbaar.'
        )
        return redirect('studio:campaign_monitor', pk=pk)

    mode = _dispatch_task(task)
    if mode == 'queued':
        messages.success(request, 'Verzilver-check gestart — ververs de pagina zo voor het resultaat.')
    elif mode == 'failed':
        messages.error(request, 'De verzilver-check is mislukt — probeer het later opnieuw.')
    else:
        messages.success(request, 'Verzilver-check direct uitgevoerd.')
    return redirect('studio:campaign_monitor', pk=pk)


@staff_member_required
@require_POST
def toggle_winner_fulfilled(request, pk, winner_id):
    campaign = get_object_or_404(Campaign, pk=pk)
    winner = get_object_or_404(
        CampaignRaffleWinner, pk=winner_id, raffle__campaign=campaign
    )
    if winner.fulfillment_status == 'fulfilled':
        winner.fulfillment_status = 'code_issued' if winner.prize_code else 'manual_pending'
        winner.fulfilled_at = None
        messages.success(request, f'Prijs van {winner.user.email} weer open gezet.')
    else:
        winner.fulfillment_status = 'fulfilled'
        winner.fulfilled_at = timezone.now()
        messages.success(request, f'Prijs van {winner.user.email} afgehandeld.')
    winner.save(update_fields=['fulfillment_status', 'fulfilled_at'])
    return redirect('studio:campaign_monitor', pk=pk)


@staff_member_required
def export_entrants_csv(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    data = _monitor_data(campaign)

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = (
        f'attachment; filename="campagne-{campaign.pk}-deelnemers.csv"'
    )
    writer = csv.writer(response)

    if data['raffle']:
        raffle = data['raffle']
        writer.writerow([
            'email', 'voornaam', 'loten', 'producten', 'push', 'email_verstuurd',
            'kaart_geopend', 'trekking_bekeken', 'gewonnen', 'prijs', 'prijscode',
            'prijs_status', 'verzilverd_op',
        ])
        for row in data['rows']:
            winner = row['winner']
            # Which of the prizes they won; without tiers that is the
            # raffle's single prize.
            prize = ''
            if winner:
                prize = winner.prize.name if winner.prize_id else raffle.prize_name
            writer.writerow([
                row['email'],
                row['first_name'],
                row['tickets'],
                '; '.join(row['matched']),
                'ja' if row['notified_push'] else 'nee',
                'ja' if row['notified_email'] else 'nee',
                row['seen'].isoformat() if row['seen'] else '',
                row['result_seen'].isoformat() if row['result_seen'] else '',
                'ja' if winner else 'nee',
                prize,
                winner.prize_code if winner else '',
                winner.get_fulfillment_status_display() if winner else '',
                winner.redeemed_at.isoformat() if winner and winner.redeemed_at else '',
            ])
    else:
        writer.writerow([
            'email', 'voornaam', 'gekwalificeerd_op', 'producten', 'push',
            'email_verstuurd', 'punten', 'kortingscode',
        ])
        for row in data['rows']:
            award = row.get('award')
            writer.writerow([
                row['email'],
                row['first_name'],
                row['qualified_at'].isoformat() if row.get('qualified_at') else '',
                '; '.join(row['matched']),
                'ja' if row['notified_push'] else 'nee',
                'ja' if row['notified_email'] else 'nee',
                award.points_awarded if award else '',
                award.discount_code if award else '',
            ])
    return response
