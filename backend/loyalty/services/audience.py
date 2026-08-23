"""Audience selection for campaigns.

An audience is (users matching ALL configured filters) UNION (hand-picked
manual_user_ids). How it is used depends on Campaign.audience_mode:

- 'orders': the audience is an extra GATE on top of the purchase conditions —
  a user outside the audience can never qualify. No audience configured =
  everyone is eligible (the pre-audience behavior).
- 'audience': the audience itself qualifies, no purchase needed. Members are
  qualified by the activation backfill; new filter matches are added by the
  nightly refresh task while the campaign is active.

Filters live in Campaign.audience_filters (JSON dict); unknown keys are
ignored so old campaigns keep working if a filter is ever removed.
"""
import logging
from datetime import date, timedelta
from typing import Optional, Set

from django.utils import timezone

logger = logging.getLogger(__name__)

# The supported filter keys — also the whitelist for the Studio form parser.
FILTER_KEYS = (
    'min_age',            # birthdate at least N years ago
    'birthday_month',     # birthdate month == N (1-12)
    'min_app_age_days',   # registered at least N days ago
    'min_lifetime_orders',  # at least N ProcessedOrders (orders synced to the app)
    'active_within_days',   # last_active_at within the last N days
)

DUTCH_MONTHS = [
    'januari', 'februari', 'maart', 'april', 'mei', 'juni',
    'juli', 'augustus', 'september', 'oktober', 'november', 'december',
]


def _years_ago(years: int) -> date:
    """Today minus N years; Feb 29 falls back to Feb 28."""
    today = timezone.localdate()
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(year=today.year - years, day=28)


def has_audience(campaign) -> bool:
    """True when the campaign restricts who can participate at all."""
    filters = campaign.audience_filters or {}
    if any(filters.get(key) for key in FILTER_KEYS):
        return True
    return bool(campaign.manual_user_ids)


def filter_queryset(filters):
    """
    QuerySet of active users matching ALL configured filters, or None when no
    filter is configured (meaning: filters place no restriction).

    Users without a birthdate never match age/birthday filters — we can only
    select on what we know.
    """
    filters = filters or {}
    if not any(filters.get(key) for key in FILTER_KEYS):
        return None

    from django.db.models import Count

    from users.models import User

    now = timezone.now()
    qs = User.objects.filter(is_active=True)

    if filters.get('min_age'):
        qs = qs.filter(birthdate__lte=_years_ago(int(filters['min_age'])))
    if filters.get('birthday_month'):
        qs = qs.filter(birthdate__month=int(filters['birthday_month']))
    if filters.get('min_app_age_days'):
        cutoff = now - timedelta(days=int(filters['min_app_age_days']))
        qs = qs.filter(date_joined__lte=cutoff)
    if filters.get('min_lifetime_orders'):
        qs = qs.annotate(_audience_order_count=Count('processed_orders')).filter(
            _audience_order_count__gte=int(filters['min_lifetime_orders'])
        )
    if filters.get('active_within_days'):
        cutoff = now - timedelta(days=int(filters['active_within_days']))
        qs = qs.filter(last_active_at__gte=cutoff)

    return qs


def audience_user_ids(campaign) -> Optional[Set[int]]:
    """
    The full audience as a set of user ids, or None when the campaign has no
    audience configured (= unrestricted).
    """
    if not has_audience(campaign):
        return None

    from users.models import User

    ids: Set[int] = set()
    qs = filter_queryset(campaign.audience_filters)
    if qs is not None:
        ids.update(qs.values_list('id', flat=True))

    manual = campaign.manual_user_ids or []
    if manual:
        ids.update(
            User.objects.filter(id__in=manual, is_active=True)
            .values_list('id', flat=True)
        )
    return ids


def user_in_audience(campaign, user) -> bool:
    """Cheap single-user membership check (used by the per-order sync hook)."""
    if not has_audience(campaign):
        return True
    if user.id in (campaign.manual_user_ids or []):
        return user.is_active
    qs = filter_queryset(campaign.audience_filters)
    if qs is None:
        return False  # manual-only audience and the user is not on the list
    return qs.filter(pk=user.pk).exists()


def describe_filters(campaign) -> list:
    """NL relative clauses per configured filter ('minstens 21 jaar oud is')."""
    filters = campaign.audience_filters or {}
    parts = []
    if filters.get('min_age'):
        parts.append(f"minstens {int(filters['min_age'])} jaar oud is")
    if filters.get('birthday_month'):
        month = DUTCH_MONTHS[int(filters['birthday_month']) - 1]
        parts.append(f"in {month} jarig is")
    if filters.get('min_app_age_days'):
        parts.append(f"de app al minstens {int(filters['min_app_age_days'])} dagen gebruikt")
    if filters.get('min_lifetime_orders'):
        n = int(filters['min_lifetime_orders'])
        noun = 'bestelling' if n == 1 else 'bestellingen'
        parts.append(f"minstens {n} {noun} heeft geplaatst")
    if filters.get('active_within_days'):
        parts.append(f"de afgelopen {int(filters['active_within_days'])} dagen actief was")
    return parts
