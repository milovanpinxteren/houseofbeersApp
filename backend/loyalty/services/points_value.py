"""What one loyalty point is worth in euros.

Staff need this to sanity-check a manual award ("100 punten, is dat veel?"),
so the number must not be a magic constant that quietly drifts away from
reality: the shop can reprice its rewards in the admin at any time. The rate
is therefore DERIVED from what the shop actually sells points for — an active
`fixed_discount` reward prices points at `discount_amount / points_cost`
(today: €5,00 for 100 punten = €0,05 per punt).

Only fixed-amount rewards can price a point: a percentage discount, free
shipping or a free product has no fixed euro value attached to a point count.

When several fixed-amount rewards exist their rates can differ. We pick the
MEDIAN rate — and deliberately an existing reward's rate, never an average —
so one oddly-priced reward cannot move the number, and whatever is shown on
screen always corresponds to a real reward staff can point at.

With no such reward configured at all we fall back to €0,05, the rate the shop
has used since the programme started; a tool that refuses to show a euro value
is worse than one showing the historical rate clearly labelled as a fallback.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

# The rate the loyalty programme has priced points at since day one. Used only
# when no active fixed-amount reward exists to derive it from.
FALLBACK_EURO_PER_POINT = Decimal('0.05')


def _rate_candidates():
    """[(rate, reward)] for every currently active fixed-amount reward, cheapest
    rate first. Validity window matches `LoyaltyService.get_active_rules`."""
    from loyalty.models import Reward

    now = timezone.now()
    rewards = Reward.objects.filter(
        is_active=True,
        reward_type='fixed_discount',
        discount_amount__isnull=False,
        points_cost__gt=0,
    ).filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=now)
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=now)
    )

    candidates = []
    for reward in rewards:
        if reward.discount_amount is None or reward.discount_amount <= 0:
            continue
        rate = Decimal(reward.discount_amount) / Decimal(reward.points_cost)
        candidates.append((rate, reward))
    candidates.sort(key=lambda pair: pair[0])
    return candidates


def rate_info():
    """
    The euro value of one point plus a NL explanation of where it came from.

    Returns {'rate': Decimal, 'label': str, 'derived': bool}. The label is
    shown on the tool so staff can see which reward the tool is pricing
    against — a silent rate is a rate nobody checks.
    """
    candidates = _rate_candidates()
    if not candidates:
        return {
            'rate': FALLBACK_EURO_PER_POINT,
            'label': (
                f'{format_euro(FALLBACK_EURO_PER_POINT)} per punt — '
                'standaardtarief (geen actieve beloning met een vast '
                'kortingsbedrag gevonden)'
            ),
            'derived': False,
        }

    rate, reward = candidates[len(candidates) // 2]
    return {
        'rate': rate,
        'label': (
            f'{format_euro(reward.discount_amount)} voor {reward.points_cost} '
            f'punten ("{reward.name}")'
        ),
        'derived': True,
    }


def euro_per_point():
    """Euro value of one point (see module docstring)."""
    return rate_info()['rate']


def points_to_euro(points, rate=None):
    """Points -> euro amount, rounded to cents."""
    rate = euro_per_point() if rate is None else rate
    return (Decimal(points) * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def euro_to_points(amount, rate=None):
    """Euro amount -> whole points (rounded to the nearest point)."""
    rate = euro_per_point() if rate is None else rate
    if rate <= 0:  # pragma: no cover - a reward with a 0 rate is filtered out
        return 0
    return int((Decimal(amount) / rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def format_euro(value):
    """Decimal -> '€5,00' (NL decimal comma; the whole UI is Dutch)."""
    return f'€{Decimal(value):.2f}'.replace('.', ',')
