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

from .serializers import (
    RegisterSerializer, 
    UserSerializer, 
    EmailTokenObtainPairSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
)
from .services import ShopifyService
from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger(__name__)


class EmailTokenObtainPairView(TokenObtainPairView):
    """Custom JWT login view that uses email instead of username."""
    serializer_class = EmailTokenObtainPairSerializer


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

        return Response(
            {
                'message': 'Registration successful.',
                'shopify_linked': shopify_linked,
            },
            status=status.HTTP_201_CREATED
        )


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
            user = User.objects.get(email=email)
            
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
    """Get orders for the current user from Shopify."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if not user.shopify_customer_id:
            return Response(
                {'error': 'No Shopify account linked. Please sync your account first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            service = ShopifyService()
            orders = service.get_customer_orders(user.shopify_customer_id)

            # Collect all unique product IDs from all orders
            all_product_ids = set()
            for order in orders:
                for item in order.get('line_items', []):
                    product_id = item.get('product_id')
                    if product_id:
                        all_product_ids.add(str(product_id))

            # Fetch estimated delivery dates for all products in one request
            delivery_dates = {}
            if all_product_ids:
                delivery_dates = service.get_products_metafields(
                    list(all_product_ids),
                    'custom',
                    'estimated_delivery_date'
                )

            # Format orders for response
            formatted_orders = []
            for order in orders:
                formatted_order = {
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
                            'estimated_delivery_date': delivery_dates.get(str(item.get('product_id'))),
                        }
                        for item in order.get('line_items', [])
                    ],
                }
                formatted_orders.append(formatted_order)

            return Response({'orders': formatted_orders})

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
