import logging
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.utils import timezone

from .models import UntappdProfile, Favorite
from .services import RecommendationService, RecommendationAPIError
from .serializers import (
    UntappdProfileSerializer, LinkUntappdSerializer,
    FavoriteSerializer, AddFavoriteSerializer,
    RecommendationFilterSerializer
)

logger = logging.getLogger(__name__)


class RecommendationsView(APIView):
    """
    Get beer recommendations for the current user.
    Uses Untappd profile if linked, otherwise falls back to Shopify order history.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        service = RecommendationService()

        # Parse filters
        filter_serializer = RecommendationFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        try:
            # Check if user has linked Untappd
            untappd_profile = getattr(user, 'untappd_profile', None)

            if untappd_profile:
                # Use Untappd profile
                result = service.get_recommendations(
                    username=untappd_profile.username,
                    **filters
                )
                profile_source = 'untappd'
                profile_identifier = untappd_profile.username
            else:
                # Fall back to email (Shopify order history)
                result = service.get_recommendations(
                    email=user.email,
                    **filters
                )
                profile_source = 'shopify'
                profile_identifier = user.email

            # Handle async response (new user, needs profile building)
            if result.get('status') == 'pending' and result.get('task_id'):
                # Poll for result (blocking, but recommendation API handles the heavy lifting)
                result = service.poll_for_result(result['task_id'])

            # Add profile source info
            result['profile_source'] = profile_source
            result['profile_identifier'] = profile_identifier

            return Response(result)

        except RecommendationAPIError as e:
            logger.error(f"Recommendation API error for {user.email}: {e}")
            # Return friendly message for 404 (user has no profile/orders yet)
            if e.status_code == 404:
                return Response({
                    'recommendations': [],
                    'discovery_picks': [],
                    'tried_beers': [],
                    'profile_summary': None,
                    'profile_source': profile_source if 'profile_source' in dir() else 'shopify',
                    'message': 'No purchase history found yet. Start shopping to get personalized recommendations!'
                })
            return Response(
                {'error': str(e)},
                status=status.HTTP_502_BAD_GATEWAY if not e.status_code else e.status_code
            )
        except Exception as e:
            logger.error(f"Unexpected error getting recommendations for {user.email}: {e}")
            return Response(
                {'error': 'Failed to get recommendations'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class TasteProfileView(APIView):
    """
    Get detailed taste profile for visualization (radar chart, etc.)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        service = RecommendationService()

        try:
            untappd_profile = getattr(user, 'untappd_profile', None)

            if untappd_profile:
                result = service.get_profile(
                    untappd_profile.username,
                    profile_type='untappd'
                )
                result['profile_source'] = 'untappd'
                result['profile_identifier'] = untappd_profile.username
            else:
                result = service.get_profile(
                    user.email,
                    profile_type='shopify'
                )
                result['profile_source'] = 'shopify'
                result['profile_identifier'] = user.email

            return Response(result)

        except RecommendationAPIError as e:
            logger.error(f"Profile API error for {user.email}: {e}")
            # Return friendly message for 404 (user has no profile/orders yet)
            if e.status_code == 404:
                return Response({
                    'taste_profile': None,
                    'style_distribution': [],
                    'top_breweries': [],
                    'abv_profile': None,
                    'total_beers': 0,
                    'profile_source': result.get('profile_source', 'shopify') if 'result' in dir() else 'shopify',
                    'message': 'No taste profile available yet. Start shopping or link your Untappd account to build your profile!'
                })
            return Response(
                {'error': str(e)},
                status=status.HTTP_502_BAD_GATEWAY if not e.status_code else e.status_code
            )
        except Exception as e:
            logger.error(f"Unexpected error getting profile for {user.email}: {e}")
            return Response(
                {'error': 'Failed to get taste profile'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UntappdProfileView(APIView):
    """
    Manage user's linked Untappd account.
    GET: Get current linked Untappd username
    POST: Link Untappd account
    DELETE: Unlink Untappd account
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = request.user.untappd_profile
            serializer = UntappdProfileSerializer(profile)
            return Response({'untappd': serializer.data})
        except UntappdProfile.DoesNotExist:
            return Response({'untappd': None})

    def post(self, request):
        serializer = LinkUntappdSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data['username'].strip()

        # Validate the Untappd profile exists by trying to fetch it
        service = RecommendationService()
        try:
            # This will fail if the profile doesn't exist or is private
            service.get_profile(username, profile_type='untappd')
        except RecommendationAPIError as e:
            return Response(
                {'error': f'Could not verify Untappd profile: {e}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create or update the profile link
        profile, created = UntappdProfile.objects.update_or_create(
            user=request.user,
            defaults={
                'username': username,
                'last_synced': timezone.now()
            }
        )

        return Response({
            'success': True,
            'untappd': UntappdProfileSerializer(profile).data,
            'message': 'Untappd account linked successfully'
        })

    def delete(self, request):
        try:
            profile = request.user.untappd_profile
            profile.delete()
            return Response({
                'success': True,
                'message': 'Untappd account unlinked'
            })
        except UntappdProfile.DoesNotExist:
            return Response(
                {'error': 'No Untappd account linked'},
                status=status.HTTP_404_NOT_FOUND
            )


class StylesListView(APIView):
    """Get available beer styles for filtering."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = RecommendationService()
        try:
            return Response(service.get_styles())
        except RecommendationAPIError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_502_BAD_GATEWAY
            )


class FavoritesListView(APIView):
    """
    List and add favorite beers.
    GET: List user's favorites
    POST: Add beer to favorites
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        favorites = Favorite.objects.filter(user=request.user)
        serializer = FavoriteSerializer(favorites, many=True)
        return Response({'favorites': serializer.data})

    def post(self, request):
        serializer = AddFavoriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Check if already favorited
        if Favorite.objects.filter(
            user=request.user,
            beer_id=serializer.validated_data['beer_id']
        ).exists():
            return Response(
                {'error': 'Beer already in favorites'},
                status=status.HTTP_400_BAD_REQUEST
            )

        favorite = Favorite.objects.create(
            user=request.user,
            **serializer.validated_data
        )

        return Response({
            'success': True,
            'favorite': FavoriteSerializer(favorite).data
        }, status=status.HTTP_201_CREATED)


class FavoriteDetailView(APIView):
    """Delete a favorite beer."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, favorite_id):
        try:
            favorite = Favorite.objects.get(id=favorite_id, user=request.user)
            favorite.delete()
            return Response({'success': True})
        except Favorite.DoesNotExist:
            return Response(
                {'error': 'Favorite not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class FavoritesCartLinkView(APIView):
    """
    Generate a Shopify cart permalink with all favorites that have variant IDs.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        favorites = Favorite.objects.filter(
            user=request.user,
            variant_id__isnull=False
        ).exclude(variant_id='')

        if not favorites:
            return Response(
                {'error': 'No favorites with variant IDs found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Build cart permalink: /cart/variant_id:qty,variant_id:qty
        items = [f"{fav.variant_id}:1" for fav in favorites]
        cart_path = ','.join(items)
        cart_url = f"https://houseofbeers.nl/cart/{cart_path}"

        return Response({
            'cart_url': cart_url,
            'item_count': len(items),
            'items': [
                {
                    'title': fav.title,
                    'variant_id': fav.variant_id,
                    'price': str(fav.price) if fav.price else None
                }
                for fav in favorites
            ]
        })


class FavoritesSelectedCartLinkView(APIView):
    """
    Generate a Shopify cart permalink for selected favorites.
    POST with list of favorite IDs.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        favorite_ids = request.data.get('favorite_ids', [])

        if not favorite_ids:
            return Response(
                {'error': 'No favorites selected'},
                status=status.HTTP_400_BAD_REQUEST
            )

        favorites = Favorite.objects.filter(
            id__in=favorite_ids,
            user=request.user,
            variant_id__isnull=False
        ).exclude(variant_id='')

        if not favorites:
            return Response(
                {'error': 'No valid favorites found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Build cart permalink
        items = [f"{fav.variant_id}:1" for fav in favorites]
        cart_path = ','.join(items)
        cart_url = f"https://houseofbeers.nl/cart/{cart_path}"

        return Response({
            'cart_url': cart_url,
            'item_count': len(items),
            'items': [
                {
                    'title': fav.title,
                    'variant_id': fav.variant_id,
                    'price': str(fav.price) if fav.price else None
                }
                for fav in favorites
            ]
        })
