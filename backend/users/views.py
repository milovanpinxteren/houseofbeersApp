import logging
from django.conf import settings
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.template.loader import render_to_string
from django.shortcuts import render
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from django.utils import timezone

from .serializers import (
    RegisterSerializer,
    UserSerializer,
    EmailTokenObtainPairSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    BirthdateSerializer,
)
from .models import SignupCode
from .services import ShopifyService
from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger(__name__)


class EmailTokenObtainPairView(TokenObtainPairView):
    """Custom JWT login view that uses email instead of username."""
    serializer_class = EmailTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            from analytics.tracker import track
            email = request.data.get('email', '')
            try:
                user = User.objects.get_by_natural_key(email)
                track('login', user=user)
            except User.DoesNotExist:
                pass
        return response


def password_reset_page(request):
    """Render the password reset page."""
    uid = request.GET.get('uid', '')
    token = request.GET.get('token', '')
    return render(request, 'password_reset.html', {'uid': uid, 'token': token})


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Try to link Shopify customer
        shopify_linked = False
        try:
            service = ShopifyService()
            shopify_linked = service.link_customer_to_user(user)
        except Exception as e:
            logger.error(f"Shopify linking failed for {user.email}: {e}")

        # Email-keyed pending grants must be claimable even when no Shopify
        # customer was found (the link path above only claims after a link).
        try:
            from loyalty.services.grants import claim_pending_grants
            claim_pending_grants(user)
        except Exception as e:
            logger.error(f"Pending grant claim failed for {user.email}: {e}")

        # Same claim, for missed-items snapshots hob pushed before this
        # person joined. Best-effort for the same reason as the grants.
        try:
            from fulfillment.services.missed import claim_pending_missed
            claim_pending_missed(user)
        except Exception as e:
            logger.error(f"Pending missed-items claim failed for {user.email}: {e}")

        # Flyer welcome bonus. Wrapped exactly like the campaign hook in
        # process_all_orders_for_user: someone who cannot create an account
        # because a printed QR code was misconfigured is a far worse outcome
        # than a missing bonus.
        bonus_points = 0
        try:
            from .services.signup_codes import award_signup_bonus
            bonus_points = award_signup_bonus(user)
        except Exception as e:
            logger.error(
                f"Signup bonus failed for {user.email}: {e}", exc_info=True
            )

        # Signup attribution on the register event, so registrations become
        # breakable-down by source straight from the event stream (see the
        # "Signup Sources" block on the analytics dashboard, which reads the
        # User columns instead — this is the per-event record).
        #
        # Both values are recorded on purpose. The normalized code is the
        # grouping key: a QR carrying "POPUP" and someone typing "popup" are
        # one source. The raw value is the only record of what was actually
        # entered, which is exactly why attach_signup_code stores it even for
        # a code that wins no bonus ("this flyer is still pulling people in").
        # Normalization uppercases and trims; it does not fix typos, so the
        # raw value is still the only way to spot a near-miss.
        #
        # signup_code_valid separates "arrived with POPUP and got 100 points"
        # from "arrived with POPUP after it hit max_uses" — the same string,
        # two very different events, and the FK is the only thing that tells
        # them apart.
        #
        # The keys are omitted entirely when no code was used, so "registered
        # without a code" stays distinguishable from "sent an empty code".
        #
        # No try/except: analytics.tracker.track already swallows and logs
        # every failure (both its event write and the last_active_at touch are
        # individually wrapped), and the metadata below is plain attribute
        # reads plus a static string normalization, so it cannot raise.
        from analytics.tracker import track
        register_metadata = {}
        if user.signup_code_raw:
            register_metadata = {
                'signup_code': SignupCode.normalize(user.signup_code_raw),
                'signup_code_raw': user.signup_code_raw,
                'signup_code_valid': user.signup_code_id is not None,
            }
        track('register', user=user, **register_metadata)

        return Response(
            {
                'message': 'Registration successful.',
                'shopify_linked': shopify_linked,
                'signup_bonus_points': bonus_points,
            },
            status=status.HTTP_201_CREATED
        )


class SignupCodeLookupView(APIView):
    """
    GET /api/auth/signup-code/<code>/ — what a flyer code is worth.

    Unauthenticated on purpose: the register screen calls it before an account
    exists, so it can promise the right number of points. It answers 200 with
    `valid: false` rather than a 404 body (one code path for the client) and
    never says WHY a code failed — an anonymous caller must not be able to
    probe which codes exist, are exhausted, or are scheduled for next month.
    """
    permission_classes = [AllowAny]

    def get(self, request, code):
        from .services.signup_codes import resolve_signup_code

        signup_code, usable = resolve_signup_code(code)
        if not usable:
            return Response({'valid': False, 'label': '', 'points': 0})

        return Response({
            'valid': True,
            'label': signup_code.label,
            'points': signup_code.points,
        })


class UserMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class UserBirthdateView(APIView):
    """
    Set the current user's birthdate.

    Can be set exactly once; changes go through Django admin (users contact
    us). Set-once doubles as the anti-abuse rule for birthday gifts.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        user = request.user

        if user.birthdate_locked:
            return Response(
                {'error': 'Your birthdate can only be set once. '
                          'Contact us if it needs correcting.'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = BirthdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user.birthdate = serializer.validated_data['birthdate']
        user.birthdate_set_at = timezone.now()
        user.save(update_fields=['birthdate', 'birthdate_set_at'])

        logger.info(f"Birthdate set for {user.email}")

        return Response(UserSerializer(user).data)


class UserSyncShopifyView(APIView):
    """Manually trigger Shopify sync for current user."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            service = ShopifyService()
            linked = service.resync_user(request.user)
            return Response({
                'linked': linked,
                'shopify_customer_id': request.user.shopify_customer_id,
            })
        except Exception as e:
            logger.error(f"Manual Shopify sync failed: {e}")
            return Response(
                {'error': 'Sync failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PasswordResetRequestView(APIView):
    """Request a password reset email."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email']
        
        try:
            # Case-insensitive (exact match first, see UserManager) so a
            # capitalized signup still gets their reset mail.
            user = User.objects.get_by_natural_key(email)

            # Generate token
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            
            # Build reset URL
            reset_url = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"
            
            # Send email
            subject = 'House of Beers - Password Reset'
            message = f"""
Hello {user.first_name or 'there'},

You requested a password reset for your House of Beers account.

Click the link below to reset your password:
{reset_url}

This link will expire in 1 hour.

If you didn't request this, please ignore this email.

Cheers,
House of Beers Team
            """.strip()
            
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
            
            logger.info(f"Password reset email sent to {email}")
            
        except User.DoesNotExist:
            # Don't reveal if email exists
            logger.info(f"Password reset requested for non-existent email: {email}")
        except Exception as e:
            logger.error(f"Failed to send password reset email: {e}")
            return Response(
                {'error': 'Failed to send email. Please try again later.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Always return success (don't reveal if email exists)
        return Response({'message': 'If an account exists with this email, a reset link has been sent.'})


class PasswordResetConfirmView(APIView):
    """Confirm password reset with token."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"Password reset validation failed: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            uid = force_str(urlsafe_base64_decode(serializer.validated_data['uid']))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist) as e:
            logger.warning(f"Password reset failed - invalid uid '{serializer.validated_data.get('uid')}': {e}")
            return Response(
                {'error': 'Invalid reset link.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        token = serializer.validated_data['token']
        if not default_token_generator.check_token(user, token):
            logger.warning(f"Password reset failed - invalid/expired token for user {user.email}")
            return Response(
                {'error': 'Reset link has expired or is invalid.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Set new password
        user.set_password(serializer.validated_data['password'])
        user.save()
        
        logger.info(f"Password reset completed for {user.email}")
        
        return Response({'message': 'Password has been reset successfully.'})


class UserOrdersView(APIView):
    """
    The app's orders screen: real Shopify orders, open draft orders (the
    WhatsApp-sale invoices waiting for payment), and recent missed-items
    records hob pushed ("you ordered 3, got 1").

    Every line item carries a derived `state` (shipped / partial /
    in_warehouse / incoming / unknown — see users/services/order_state.py)
    and a `display_title` (custom.app_title when present: WhatsApp-sale
    products are titled "24-10 - K - Beer" for pipeline idempotency, the
    clean name lives in the metafield).
    """
    permission_classes = [IsAuthenticated]

    MISSED_WINDOW_DAYS = 30

    def get(self, request):
        from .services.order_state import derive_line_state, display_title

        user = request.user

        if not user.shopify_customer_id:
            return Response(
                {'error': 'No Shopify account linked. Please sync your account first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Cheap, best-effort: pending missed-items records keyed on this
        # user's identity attach themselves the moment the screen is opened,
        # so a push that raced the registration hooks still shows up.
        try:
            from fulfillment.services.missed import claim_pending_missed
            claim_pending_missed(user)
        except Exception as e:
            logger.error(f"Missed-items claim failed for {user.email}: {e}")

        try:
            service = ShopifyService()
            orders = service.get_customer_orders(user.shopify_customer_id)
            drafts = service.get_customer_draft_orders(user.shopify_customer_id)

            # Pool product ids from BOTH orders and drafts into one chunked
            # metafield fetch (ETA + app_title per product).
            all_product_ids = set()
            for order in orders:
                for item in order.get('line_items', []):
                    if item.get('product_id'):
                        all_product_ids.add(str(item['product_id']))
            for draft in drafts:
                for item in draft.get('line_items', []):
                    if item.get('product_id'):
                        all_product_ids.add(str(item['product_id']))

            metafields, unresolved_ids = {}, set()
            if all_product_ids:
                metafields, unresolved_ids = service.get_products_metafields_bulk(
                    list(all_product_ids),
                    'custom',
                    ['estimated_delivery_date', 'app_title'],
                )

            # The warehouse's calendar decides whether an ETA has passed
            # (TIME_ZONE = Europe/Amsterdam), not the customer's phone.
            today = timezone.localdate()

            def _line_fields(item, fulfillment_status=None):
                """state / display_title / normalized ETA for one line."""
                product_id = item.get('product_id')
                product_metafields = metafields.get(
                    str(product_id), {}
                ) if product_id else {}
                state, eta = derive_line_state(
                    product_id=product_id,
                    raw_eta=product_metafields.get('estimated_delivery_date'),
                    unresolved_ids=unresolved_ids,
                    today=today,
                    fulfillment_status=fulfillment_status,
                )
                return {
                    'display_title': display_title(
                        item.get('title'), product_metafields
                    ),
                    'state': state,
                    'estimated_delivery_date': eta,
                }

            formatted_orders = []
            for order in orders:
                formatted_orders.append({
                    'id': order.get('id'),
                    'order_number': order.get('order_number'),
                    'name': order.get('name'),  # e.g., "#1001"
                    'created_at': order.get('created_at'),
                    'financial_status': order.get('financial_status'),
                    'fulfillment_status': order.get('fulfillment_status'),
                    'total_price': order.get('total_price'),
                    'currency': order.get('currency'),
                    'line_items': [
                        {
                            'id': item.get('id'),
                            'title': item.get('title'),
                            'variant_title': item.get('variant_title'),
                            'quantity': item.get('quantity'),
                            'price': item.get('price'),
                            'sku': item.get('sku'),
                            'product_id': item.get('product_id'),
                            'fulfillment_status': item.get('fulfillment_status'),
                            **_line_fields(
                                item,
                                fulfillment_status=item.get('fulfillment_status'),
                            ),
                        }
                        for item in order.get('line_items', [])
                    ],
                })

            formatted_drafts = []
            for draft in drafts:
                formatted_drafts.append({
                    'id': draft.get('id'),
                    'name': draft.get('name'),
                    'status': draft.get('status'),
                    'created_at': draft.get('created_at'),
                    'invoice_url': draft.get('invoice_url'),
                    'total_price': draft.get('total_price'),
                    'currency': draft.get('currency'),
                    'line_items': [
                        {
                            'title': item.get('title'),
                            'variant_title': item.get('variant_title'),
                            'quantity': item.get('quantity'),
                            'price': item.get('price'),
                            'product_id': item.get('product_id'),
                            # Draft lines are never fulfilled, so they always
                            # take the ETA path.
                            **_line_fields(item),
                        }
                        for item in draft.get('line_items', [])
                    ],
                })

            # Recent missed-items only: attached to THIS user, within the
            # window. 'cleared' (customer misses nothing anymore) and
            # 'pending' (not provably this user) must never render.
            from datetime import timedelta
            from fulfillment.models import MissedItemsRecord

            missed_records = (
                MissedItemsRecord.objects
                .filter(
                    user=user,
                    status='attached',
                    sale_date__gte=today - timedelta(days=self.MISSED_WINDOW_DAYS),
                )
                .order_by('-sale_date', '-id')
            )
            missed = [
                {
                    'sale_id': record.sale_id,
                    'sale_name': record.sale_name,
                    'sale_date': record.sale_date.isoformat(),
                    'draft_order_id': record.draft_order_id or None,
                    'shopify_order_id': record.shopify_order_id or None,
                    'lines': record.lines,
                }
                for record in missed_records
            ]

            from analytics.tracker import track
            track('orders_view', user=user, order_count=len(formatted_orders))

            return Response({
                'orders': formatted_orders,
                'drafts': formatted_drafts,
                'missed': missed,
            })

        except Exception as e:
            logger.error(f"Failed to fetch orders for user {user.email}: {e}")
            return Response(
                {'error': 'Failed to fetch orders'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UserDeleteAccountView(APIView):
    """Delete user account and all associated data."""
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = request.user
        email = user.email

        try:
            # Delete all loyalty-related data
            from loyalty.models import PointsBalance, PointsTransaction, Redemption, DismissedNotification

            PointsTransaction.objects.filter(user=user).delete()
            Redemption.objects.filter(user=user).delete()
            DismissedNotification.objects.filter(user=user).delete()
            PointsBalance.objects.filter(user=user).delete()

            # Delete the user account
            user.delete()

            logger.info(f"Account deleted for user: {email}")

            return Response(
                {'message': 'Your account and all associated data have been permanently deleted.'},
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Failed to delete account for {email}: {e}")
            return Response(
                {'error': 'Failed to delete account. Please try again or contact support.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
