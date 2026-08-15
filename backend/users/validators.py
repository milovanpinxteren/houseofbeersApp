"""
Shared birthdate validation.

Used by both the profile birthdate endpoint and registration so that an
under-18 date is rejected identically wherever it arrives. We sell alcohol,
so an under-18 birthdate is a hard rejection, not merely "ineligible for a
birthday gift".
"""
from datetime import date

from django.utils import timezone
from rest_framework import serializers

# Legal drinking age in NL. Deliberately a constant, not an admin-tunable
# setting: nothing in the admin should be able to lower who may register.
MINIMUM_AGE = 18

# Plausibility ceiling.
MAXIMUM_AGE = 120


def calculate_age(birthdate: date, today: date = None) -> int:
    """Whole years between birthdate and today."""
    today = today or timezone.localdate()
    return (
        today.year
        - birthdate.year
        - ((today.month, today.day) < (birthdate.month, birthdate.day))
    )


def validate_birthdate(value):
    """
    Validate a birthdate for any caller.

    Raises serializers.ValidationError with a clear reason - never silently
    ignores a bad value.
    """
    if value is None:
        return value

    today = timezone.localdate()

    if value > today:
        raise serializers.ValidationError('Birthdate cannot be in the future.')

    age = calculate_age(value, today)

    if age < MINIMUM_AGE:
        raise serializers.ValidationError(
            f'You must be at least {MINIMUM_AGE} years old to use House of Beers.'
        )

    if age > MAXIMUM_AGE:
        raise serializers.ValidationError(
            f'Please enter a valid birthdate (age over {MAXIMUM_AGE} is not accepted).'
        )

    return value
