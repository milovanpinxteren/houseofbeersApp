"""Signup codes.

A printed flyer carries a QR code (https://app.houseofbeers.nl/?ref=CODE) plus
the code in plain text next to it. Someone who registers while carrying that
code gets a welcome bonus in loyalty points, and we learn which flyer brought
them in.

Imported at the end of models.py so `from users.models import SignupCode`
works — same idiom as loyalty's models_campaigns / models_grants.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

__all__ = ['SignupCode', 'PWA_URL_DEFAULT']

# The front-end origin the QR must point at. There is exactly one production
# PWA; settings.PWA_URL exists only so staging/local can override it.
PWA_URL_DEFAULT = 'https://app.houseofbeers.nl'


class SignupCode(models.Model):
    """
    One printed campaign: a code, what it is worth, and when it is valid.

    Codes are stored normalized (uppercase, trimmed) because they travel two
    ways with different casing: a QR carrying "FLYER-UTRECHT" and an admin (or
    a member) typing "flyer-utrecht" must be the same code.
    """

    code = models.CharField(
        max_length=64,
        unique=True,
        help_text="Normalized to UPPERCASE on save. Keep it short and "
                  "unambiguous — people type this off a flyer."
    )
    label = models.CharField(
        max_length=200,
        help_text="What this code is for, e.g. 'Flyer Utrecht september'. "
                  "Shown to the member in their points history."
    )
    points = models.PositiveIntegerField(
        default=100,
        help_text="Welcome bonus awarded once, at registration."
    )

    is_active = models.BooleanField(default=True)
    valid_from = models.DateTimeField(
        null=True, blank=True,
        help_text="Leave empty for 'valid immediately'."
    )
    valid_until = models.DateTimeField(
        null=True, blank=True,
        help_text="Leave empty for 'never expires'."
    )
    max_uses = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Leave empty for unlimited."
    )

    notes = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Signup Code'
        verbose_name_plural = 'Signup Codes'

    def __str__(self):
        return f"{self.code} ({self.points} pts)"

    @staticmethod
    def normalize(value) -> str:
        """The one place a raw code becomes a lookup key."""
        return (value or '').strip().upper()

    def save(self, *args, **kwargs):
        self.code = self.normalize(self.code)
        super().save(*args, **kwargs)

    @property
    def signup_count(self) -> int:
        """
        How many members were awarded this code's bonus.

        The FK is only attached when the code was usable at arrival time (see
        users.services.signup_codes.attach_signup_code), so this doubles as
        the max_uses meter. People who arrived with an expired or mistyped
        code keep their attribution in User.signup_code_raw instead.
        """
        return self.signups.count()

    @property
    def qr_url(self) -> str:
        """The exact URL to encode in the printed QR code."""
        base = getattr(settings, 'PWA_URL', PWA_URL_DEFAULT).rstrip('/')
        return f"{base}/?ref={self.code}"

    def check_usable(self, now=None):
        """
        Is this code redeemable right now? Returns (bool, reason).

        `reason` is for logs and the admin only — the public lookup endpoint
        deliberately collapses every failure into a bare valid:false so an
        unauthenticated caller cannot probe which codes exist.
        """
        now = now or timezone.now()

        if not self.is_active:
            return False, 'inactive'
        if self.valid_from and now < self.valid_from:
            return False, 'not yet valid'
        if self.valid_until and now > self.valid_until:
            return False, 'expired'
        if self.max_uses is not None and self.signup_count >= self.max_uses:
            return False, 'max uses reached'
        if self.points < 1:
            return False, 'no points configured'
        return True, ''
