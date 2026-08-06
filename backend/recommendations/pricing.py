"""
Charm pricing for the personalized sixpack.

The discount is whatever it takes to land the pack on a "nice" price
(ending in .49 or .99), kept close to 5% and clamped to 3-8%.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

TWO_PLACES = Decimal('0.01')
MIN_DISCOUNT_PCT = Decimal('0.03')
MAX_DISCOUNT_PCT = Decimal('0.08')
TARGET_PCT = Decimal('0.05')
CHARM_ENDINGS = (Decimal('0.49'), Decimal('0.99'))


def charm_price(value) -> dict:
    """
    Compute the charm price for a pack value.

    Returns {value, price, discount, discount_pct, charm} with Decimals.
    When no charm candidate fits the 3-8% clamp, falls back to a plain 5%
    discount with charm=False. Zero/invalid values yield a zero discount.
    """
    try:
        value = Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        value = None

    if value is None or value <= 0:
        zero = Decimal('0.00')
        return {
            'value': value or zero,
            'price': value or zero,
            'discount': zero,
            'discount_pct': zero,
            'charm': False,
        }

    target = value * (Decimal('1') - TARGET_PCT)

    # Candidate charm prices below the value, within the discount clamp.
    max_discount = value * MAX_DISCOUNT_PCT
    lowest_base = int(value - max_discount) - 1
    candidates = []
    for base in range(max(lowest_base, 0), int(value) + 1):
        for ending in CHARM_ENDINGS:
            candidate = Decimal(base) + ending
            if candidate >= value:
                continue
            pct = (value - candidate) / value
            if MIN_DISCOUNT_PCT <= pct <= MAX_DISCOUNT_PCT:
                candidates.append(candidate)

    if candidates:
        # Nearest to the 5% target; on a tie prefer the lower price.
        price = min(candidates, key=lambda c: (abs(c - target), c))
        charm = True
    else:
        discount = (value * TARGET_PCT).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        price = value - discount
        charm = False

    discount = (value - price).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    pct = (discount / value * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

    return {
        'value': value,
        'price': price,
        'discount': discount,
        'discount_pct': pct,
        'charm': charm,
    }
