from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

from .validators import validate_birthdate

User = get_user_model()


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom JWT serializer that uses email instead of username."""
    username_field = 'email'


class RegisterSerializer(serializers.ModelSerializer):
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

    class Meta:
        model = User
        fields = ['email', 'password', 'password_confirm', 'first_name', 'last_name', 'birthdate']

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match.'})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        birthdate = validated_data.get('birthdate')
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
