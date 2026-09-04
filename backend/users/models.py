from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.utils import timezone

# last_active_at is written at most once per this window per user, so a chatty
# session costs one UPDATE rather than one per request. The field is used for
# audience segmentation ("nobody who has visited in 90 days"), where
# quarter-hour precision is far more than enough.
LAST_ACTIVE_THROTTLE = timedelta(minutes=15)


class UserManager(DjangoUserManager):
    def get_by_natural_key(self, username):
        """
        Case-insensitive email lookup, exact match first.

        Exact-first matters: a handful of legacy accounts exist in
        case-duplicate pairs (e.g. Foo@x.com and foo@x.com are different
        users), and both must stay reachable with the casing they registered.
        """
        try:
            return self.get(**{self.model.USERNAME_FIELD: username})
        except self.model.DoesNotExist:
            matches = self.filter(
                **{f"{self.model.USERNAME_FIELD}__iexact": username}
            )
            if len(matches) == 1:
                return matches[0]
            raise


class User(AbstractUser):
    """Custom user model with Shopify integration."""

    email = models.EmailField(unique=True)
    shopify_customer_id = models.CharField(max_length=255, blank=True, null=True)
    shopify_linked_at = models.DateTimeField(blank=True, null=True)

    # Birthday rewards. Validated 18+ wherever it is set (see users.validators).
    birthdate = models.DateField(
        blank=True,
        null=True,
        help_text="Date of birth. Must be 18+. Locked once a birthday gift has been issued."
    )
    birthdate_set_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the birthdate was last set. Used for the anti-abuse lead time."
    )

    # Where this member came from. The FK is set only when the code was
    # actually redeemable at registration; signup_code_raw keeps whatever they
    # arrived with — including a mistyped or long-expired flyer code, because
    # "this flyer is still pulling people in" is worth knowing even when no
    # bonus was paid out.
    signup_code = models.ForeignKey(
        'users.SignupCode',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='signups',
    )
    signup_code_raw = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text="The code as it arrived (QR or typed), valid or not."
    )
    # The once-ever marker for the welcome bonus. Checked and set under a row
    # lock in the same transaction as the points write, so a retried request
    # or a double-submitted form cannot pay out twice. "Registration happens
    # once" is not a guard we are willing to lean on.
    welcome_bonus_awarded_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the signup-code welcome bonus was paid out. Set once, ever."
    )

    # Last time the user did anything in the app. Indexed because segment
    # queries filter on it.
    last_active_at = models.DateTimeField(
        blank=True,
        null=True,
        db_index=True,
        help_text="Last recorded activity. Updated from analytics.tracker.track()."
    )

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.email

    def touch_last_active(self) -> bool:
        """
        Record that the user was just active. Returns True if it wrote.

        Throttled to one write per LAST_ACTIVE_THROTTLE, and written with a
        queryset UPDATE so it touches exactly one column - no signals, no
        auto_now fields, and no clobbering of concurrent writes to the row.
        """
        now = timezone.now()

        if self.last_active_at and (now - self.last_active_at) < LAST_ACTIVE_THROTTLE:
            return False

        User.objects.filter(pk=self.pk).update(last_active_at=now)
        self.last_active_at = now
        return True

    @property
    def birthdate_locked(self) -> bool:
        """
        The birthdate can be set once; after that it is locked in-app
        (admin can still correct it). Set-once is also the anti-abuse rule:
        nobody can move their birthday around to farm gifts.
        """
        return self.birthdate is not None


from .models_signup import *  # noqa: E402,F401,F403
