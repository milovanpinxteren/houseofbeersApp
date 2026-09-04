import logging

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

from .validators import validate_birthdate

User = get_user_model()
logger = logging.getLogger(__name__)


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom JWT serializer that uses email instead of username."""
    username_field = 'email'


class RegisterSerializer(serializers.ModelSerializer):
    # Declared explicitly so the model field's UniqueValidator does not
    # pre-empt validate_email(). It fires first on an exact match and its
    # message ("user with this email already exists") offers no way forward —
    # a dead end for someone who just scanned a flyer and landed here.
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)
    # Optional: existing clients that never send a birthdate keep working.
    # When it IS supplied it goes through exactly the same rule as the
    # birthdate endpoint, so an under-18 registration fails.
    birthdate = serializers.DateField(
        required=False,
        allow_null=True,
        validators=[validate_birthdate],
    )
    # Flyer code (?ref=CODE or typed by hand). Never a validation error: an
    # unknown or expired code must not block an account, it just wins no bonus.
    signup_code = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=64,
        write_only=True,
    )

    class Meta:
        model = User
        fields = ['email', 'password', 'password_confirm', 'first_name', 'last_name',
                  'birthdate', 'signup_code']

    def validate_email(self, value):
        # Stored lowercase so login and password reset are case-insensitive
        # regardless of what the phone keyboard capitalized.
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            # Names the way out. Someone arriving from a flyer QR lands on the
            # register screen, and "already exists" alone is a dead end.
            raise serializers.ValidationError(
                'A user with this email already exists. Please log in instead.'
            )
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match.'})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        birthdate = validated_data.get('birthdate')
        signup_code = validated_data.pop('signup_code', '')
        user = User.objects.create_user(
            username=validated_data['email'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
        )
        if birthdate:
            user.birthdate = birthdate
            user.birthdate_set_at = timezone.now()
            user.save(update_fields=['birthdate', 'birthdate_set_at'])

        if signup_code:
            # Records the code on the user (raw always, FK only when usable).
            # Awarding the bonus happens in the view. Guarded here too: a
            # misconfigured flyer must cost someone a bonus, never an account.
            try:
                from .services.signup_codes import attach_signup_code
                attach_signup_code(user, signup_code)
            except Exception as e:
                logger.error(
                    f"Attaching signup code '{signup_code}' to {user.email} "
                    f"failed: {e}",
                    exc_info=True,
                )

        return user


class UserSerializer(serializers.ModelSerializer):
    birthdate_locked = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'shopify_customer_id', 'shopify_linked_at',
                  'date_joined', 'birthdate', 'birthdate_locked', 'is_staff']
        # birthdate is read-only here on purpose: it may only be written
        # through PATCH /api/users/me/birthdate/, which enforces the lock.
        read_only_fields = ['id', 'shopify_customer_id', 'shopify_linked_at', 'date_joined',
                            'birthdate', 'birthdate_locked', 'is_staff']


class BirthdateSerializer(serializers.Serializer):
    """Write serializer for PATCH /api/users/me/birthdate/."""
    birthdate = serializers.DateField(validators=[validate_birthdate])


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()
    uid = serializers.CharField()
    password = serializers.CharField(validators=[validate_password])
    password_confirm = serializers.CharField()

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match.'})
        return attrs
