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
    RecommendationFilterSerializer, SelectedFavoritesSerializer
)

logger = logging.getLogger(__name__)


def _get_untappd_profile(user):
    """Safely get user's Untappd profile, returning None if not linked."""
    try:
        return user.untappd_profile
    except UntappdProfile.DoesNotExist:
        return None


EMPTY_RECOMMENDATIONS = {
    'recommendations': [],
    'discovery_picks': [],
    'tried_beers': [],
    'profile_summary': None,
}

EMPTY_TASTE_PROFILE = {
    'total_checkins': 0,
    'unique_beers': 0,
    'radar_chart': {'axes': [], 'values': [], 'details': []},
    'style_distribution': [],
    'top_breweries': [],
    'abv_profile': None,
    'rating_profile': None,
}


def _is_empty_taste_profile(result):
    """
    True when the upstream returned 200 but the profile carries no usable data.

    Untappd scrapes can succeed at the HTTP level while yielding nothing (for
    example when Untappd blocks the beer-list pages), which would otherwise
    render an empty taste wheel instead of triggering the Shopify fallback.
    """
    if not result:
        return True
    if result.get('total_checkins'):
        return False
    radar = result.get('radar_chart') or {}
    return not radar.get('axes') and not result.get('style_distribution')


def _is_empty_recommendations(result):
    """True when a 200 recommendations payload carries no beers at all."""
    if not result:
        return True
    return not any(
        result.get(key)
        for key in ('recommendations', 'discovery_picks', 'tried_beers')
    )


class RecommendationsView(APIView):
    """
    Get beer recommendations for the current user.
    Uses Untappd profile if linked, otherwise falls back to Shopify order history.
    If Untappd fails, automatically falls back to Shopify.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        service = RecommendationService()

        # Parse filters
        filter_serializer = RecommendationFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        untappd_profile = _get_untappd_profile(user)
        result = None
        profile_source = 'shopify'
        profile_identifier = user.email

        try:
            # Try Untappd first if linked
            if untappd_profile:
                try:
                    result = service.get_recommendations(
                        username=untappd_profile.username,
                        **filters
                    )
                    # Handle async response (new user, needs profile building).
                    # This sits INSIDE the try so a failed build task still
                    # falls back to Shopify order history.
                    if result.get('status') == 'pending' and result.get('task_id'):
                        result = service.poll_for_result(result['task_id'])
                    # A 200 with no beers is still a failed profile — fall back
                    # rather than showing the user an empty screen. Pending
                    # results are not yet resolved, so leave those alone.
                    if (
                        result.get('status') != 'pending'
                        and _is_empty_recommendations(result)
                    ):
                        logger.warning(
                            f"Untappd recommendations empty for {user.email} "
                            f"(username: {untappd_profile.username}) — falling back to Shopify"
                        )
                        result = None
                    else:
                        profile_source = 'untappd'
                        profile_identifier = untappd_profile.username
                except RecommendationAPIError as e:
                    logger.warning(
                        f"Untappd recommendations failed for {user.email} "
                        f"(username: {untappd_profile.username}): {e} — falling back to Shopify"
                    )
                    result = None

            # Fall back to Shopify if Untappd failed or not linked
            if result is None:
                result = service.get_recommendations(
                    email=user.email,
                    **filters
                )
                if result.get('status') == 'pending' and result.get('task_id'):
                    result = service.poll_for_result(result['task_id'])
                profile_source = 'shopify'
                profile_identifier = user.email

            # Still pending after the short inline poll — hand the task to the
            # client, which long-polls the status endpoint instead of us
            # blocking a gunicorn worker.
            if result.get('status') == 'pending' and result.get('task_id'):
                return Response({
                    'status': 'pending',
                    'task_id': result['task_id'],
                    'profile_source': profile_source,
                    'profile_identifier': profile_identifier,
                })

            # Add profile source info
            result['profile_source'] = profile_source
            result['profile_identifier'] = profile_identifier

            if _is_empty_recommendations(result) and not result.get('message'):
                summary = result.get('profile_summary') or {}
                if summary.get('total_checkins'):
                    # The user has a taste profile — there is simply nothing in
                    # stock to match it against right now. Telling them to
                    # "start shopping" here would be plainly wrong.
                    result['message'] = (
                        "We couldn't match any beers to your taste profile right "
                        "now. Please check back soon!"
                    )
                else:
                    result['message'] = (
                        'No purchase history found yet. Start shopping to get '
                        'personalized recommendations!'
                    )

            from analytics.tracker import track
            track('recommendations', user=user, source=profile_source)

            return Response(result)

        except RecommendationAPIError as e:
            logger.error(f"Recommendation API error for {user.email}: {e}")
            if e.status_code == 404:
                return Response({
                    **EMPTY_RECOMMENDATIONS,
                    'profile_source': profile_source,
                    'profile_identifier': profile_identifier,
                    'message': 'No purchase history found yet. Start shopping to get personalized recommendations!'
                })
            # Never proxy upstream status codes (401/429/...) to the client —
            # they would be misread as app-level auth/rate-limit errors.
            return Response(
                {'error': str(e)},
                status=status.HTTP_502_BAD_GATEWAY
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
    If Untappd fails, automatically falls back to Shopify order history.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        service = RecommendationService()

        untappd_profile = _get_untappd_profile(user)
        result = None
        profile_source = 'shopify'
        profile_identifier = user.email

        try:
            # Try Untappd first if linked
            if untappd_profile:
                try:
                    result = service.get_profile(
                        untappd_profile.username,
                        profile_type='untappd'
                    )
                    # A 200 with no check-ins/styles means the Untappd scrape
                    # produced nothing usable — fall back instead of rendering
                    # an empty taste wheel.
                    if _is_empty_taste_profile(result):
                        logger.warning(
                            f"Untappd taste profile empty for {user.email} "
                            f"(username: {untappd_profile.username}) — falling back to Shopify"
                        )
                        result = None
                    else:
                        profile_source = 'untappd'
                        profile_identifier = untappd_profile.username
                except RecommendationAPIError as e:
                    logger.warning(
                        f"Untappd profile fetch failed for {user.email} "
                        f"(username: {untappd_profile.username}): {e} — falling back to Shopify"
                    )

            # Fall back to Shopify if Untappd failed or not linked
            if result is None:
                result = service.get_profile(
                    user.email,
                    profile_type='shopify'
                )
                profile_source = 'shopify'
                profile_identifier = user.email

            result['profile_source'] = profile_source
            result['profile_identifier'] = profile_identifier

            if _is_empty_taste_profile(result) and not result.get('message'):
                result['message'] = (
                    'No taste profile available yet. Start shopping or link your '
                    'Untappd account to build your profile!'
                )

            from analytics.tracker import track
            track('taste_profile', user=user)

            return Response(result)

        except RecommendationAPIError as e:
            logger.error(f"Profile API error for {user.email}: {e}")
            if e.status_code == 404:
                return Response({
                    **EMPTY_TASTE_PROFILE,
                    'profile_source': profile_source,
                    'profile_identifier': profile_identifier,
                    'message': 'No taste profile available yet. Start shopping or link your Untappd account to build your profile!'
                })
            # Never proxy upstream status codes (401/429/...) to the client.
            return Response(
                {'error': str(e)},
                status=status.HTTP_502_BAD_GATEWAY
            )
        except Exception as e:
            logger.error(f"Unexpected error getting profile for {user.email}: {e}")
            return Response(
                {'error': 'Failed to get taste profile'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class RecommendationStatusView(APIView):
    """
    Proxy a single task-status check to the recommender API so the mobile
    client (not a gunicorn worker) does the long polling for profile builds.

    Always returns HTTP 200 with one of:
      {status: 'pending'}
      {status: 'completed', result: {...}}
      {status: 'failed', error: '...'}

    On 'completed' or 'failed' the client refetches /api/recommendations/,
    which returns the finished profile or falls back to Shopify order history.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        service = RecommendationService()
        try:
            result = service.get_task_status(task_id)
        except RecommendationAPIError as e:
            logger.warning(
                f"Task status check failed for {request.user.email} "
                f"(task: {task_id}): {e}"
            )
            # Report as failed so the client refetches /recommendations/,
            # which will fall back to Shopify order history if needed.
            return Response({'status': 'failed', 'error': str(e)})

        task_status = result.get('status')
        if task_status == 'completed':
            return Response({
                'status': 'completed',
                'result': result.get('result', result),
            })
        if task_status == 'failed':
            return Response({
                'status': 'failed',
                'error': result.get('error', 'Task failed'),
            })
        return Response({'status': 'pending'})


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
            if e.status_code == 404:
                # Stable message the mobile client can match on
                return Response(
                    {'error': 'Untappd profile not found or is private'},
                    status=status.HTTP_400_BAD_REQUEST
                )
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

        from analytics.tracker import track
        track('untappd_link', user=request.user, username=username)

        return Response({
            'success': True,
            'untappd': UntappdProfileSerializer(profile).data,
            'message': 'Untappd account linked successfully'
        })

    def delete(self, request):
        try:
            profile = request.user.untappd_profile
            profile.delete()
            from analytics.tracker import track
            track('untappd_unlink', user=request.user)
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
        data = serializer.validated_data

        # get_or_create is atomic against the unique_together constraint, so
        # a double-tap can't race check-then-create into an IntegrityError
        favorite, created = Favorite.objects.get_or_create(
            user=request.user,
            beer_id=data['beer_id'],
            defaults={k: v for k, v in data.items() if k != 'beer_id'}
        )

        if created:
            from analytics.tracker import track
            track('favorite_add', user=request.user, beer=data.get('title', ''))

        return Response({
            'success': True,
            'favorite': FavoriteSerializer(favorite).data
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class FavoriteDetailView(APIView):
    """Delete a favorite beer."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, favorite_id):
        try:
            favorite = Favorite.objects.get(id=favorite_id, user=request.user)
            title = favorite.title
            favorite.delete()
            from analytics.tracker import track
            track('favorite_remove', user=request.user, beer=title)
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

        from analytics.tracker import track
        track('cart_link', user=request.user, item_count=len(items))

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
        serializer = SelectedFavoritesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        favorite_ids = serializer.validated_data['favorite_ids']

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

        from analytics.tracker import track
        track('cart_link', user=request.user, item_count=len(items))

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
