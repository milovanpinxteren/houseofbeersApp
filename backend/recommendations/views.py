import logging
import random
from decimal import Decimal, InvalidOperation

from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from rest_framework.throttling import UserRateThrottle

from users.services.shopify import ShopifyService
from .models import UntappdProfile, Favorite, SixpackCheckout
from .pricing import charm_price
from .services import RecommendationService, RecommendationAPIError
from .serializers import (
    UntappdProfileSerializer, LinkUntappdSerializer,
    FavoriteSerializer, AddFavoriteSerializer,
    RecommendationFilterSerializer, RandomBeerFilterSerializer,
    SelectedFavoritesSerializer,
    SixpackGenerateSerializer, SixpackCheckoutSerializer,
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


# Random beer picker — product list cache so repeated spins don't hammer
# the Shopify Admin API. Shared across gunicorn workers via Redis in prod.
# v2: cached dicts gained variant_id/created_at — the key bump drops stale
# entries that lack them.
PRODUCT_CACHE_KEY = 'recommendations:shopify_active_products:v2'
PRODUCT_CACHE_TTL = 60 * 60 * 2  # 2 hours (beat refreshes hourly, so one missed run is survivable)

SHOP_BASE_URL = 'https://houseofbeers.nl'


def _get_shop_products() -> list:
    """Active, in-stock shop products (cached for PRODUCT_CACHE_TTL)."""
    products = cache.get(PRODUCT_CACHE_KEY)
    if products is None:
        products = ShopifyService().get_active_products()
        if products:
            # Don't cache an empty list — it usually means the Shopify call
            # failed, and we'd pin the failure for 15 minutes.
            cache.set(PRODUCT_CACHE_KEY, products, PRODUCT_CACHE_TTL)
    return products


def _product_price(product) -> Decimal:
    try:
        return Decimal(str(product.get('price')))
    except (InvalidOperation, TypeError, ValueError):
        return None


class RandomBeerView(APIView):
    """
    Pick a uniformly random beer from the shop's active, in-stock products.

    Optional query params:
      - style: case-insensitive exact match on product_type or any tag
      - max_price: only products with first-variant price <= max_price
      - styles_only: truthy value returns just {styles: [...]} without
        picking a beer (used by the client to prefetch filter chips)

    Response always includes `styles`: the distinct non-empty product_type
    values across ALL in-stock products (sorted), so the client can render
    filter chips without a separate request.

    When no product matches the filters (or the product list is empty),
    responds 200 with {found: false, styles: [...]} so the client can show
    a friendly "loosen your filters" state.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        filter_serializer = RandomBeerFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        style = (filter_serializer.validated_data.get('style') or '').strip()
        max_price = filter_serializer.validated_data.get('max_price')

        try:
            products = _get_shop_products()
        except Exception as e:
            logger.error(f"Random beer: failed to fetch products: {e}")
            return Response(
                {'error': 'Failed to fetch products'},
                status=status.HTTP_502_BAD_GATEWAY
            )

        styles = sorted(
            {p['product_type'] for p in products if p.get('product_type')},
            key=str.lower
        )

        if request.query_params.get('styles_only'):
            return Response({'styles': styles})

        filtered = products
        if style:
            needle = style.lower()
            filtered = [
                p for p in filtered
                if (p.get('product_type') or '').lower() == needle
                or needle in [tag.lower() for tag in p.get('tags') or []]
            ]
        if max_price is not None:
            filtered = [
                p for p in filtered
                if (price := _product_price(p)) is not None and price <= max_price
            ]

        if not filtered:
            return Response({'found': False, 'styles': styles})

        product = random.choice(filtered)
        beer = {
            **product,
            'shop_url': f"{SHOP_BASE_URL}/products/{product.get('handle', '')}",
        }

        from analytics.tracker import track
        track('random_beer', user=request.user, style=style or None)

        return Response({'found': True, 'beer': beer, 'styles': styles})


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


class NewArrivalsView(APIView):
    """
    Newest products in the shop, from the cached active-product list.

    GET /api/recommendations/new-arrivals/?limit=10
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            limit = min(max(int(request.query_params.get('limit', 10)), 1), 20)
        except (TypeError, ValueError):
            limit = 10

        try:
            products = _get_shop_products()
        except Exception as e:
            logger.error(f"New arrivals fetch failed: {e}")
            return Response(
                {'error': 'Could not load shop products'},
                status=status.HTTP_502_BAD_GATEWAY
            )

        newest = sorted(
            products,
            key=lambda p: p.get('created_at') or '',
            reverse=True,
        )[:limit]

        return Response({
            'products': [
                {
                    **product,
                    'shop_url': f"{SHOP_BASE_URL}/products/{product.get('handle', '')}",
                }
                for product in newest
            ]
        })


# App-exclusive shop — leftover WhatsApp-sale stock tagged `app-only` by the
# hob pipeline, sold at the secondary app price. Products are UNLISTED in the
# webshop; the App variant (never variants[0]) carries price and stock.
APP_SHOP_CACHE_KEY = 'recommendations:app_only_products:v1'
APP_SHOP_CACHE_TTL = 60 * 30  # 30 min — sold-out items should drop out fast

# Local-dev fixtures: run the backend with APP_SHOP_DEMO=1 (DEBUG only) to see
# the App-exclusief section in the app without touching Shopify or production.
_APP_SHOP_DEMO_PRODUCTS = [
    {
        'id': '1', 'title': '3 Fonteinen Oude Geuze [DEMO]',
        'shopify_title': 'Demo - Z1 - 3 Fonteinen Oude Geuze', 'handle': 'demo-1',
        'description': 'Dit is lokale demo-data (APP_SHOP_DEMO=1) — er bestaat geen echt product. '
                       'Een blend van jonge en oude lambik, spontaan gegist. Droog, complex en levendig.',
        'image_url': 'https://cdn.shopify.com/s/files/1/0807/5624/4818/files/674a70651e3c622d1171eb9fe37dc45a.png?v=1706722294',
        'tags': ['app-only'], 'created_at': '2026-08-01T10:00:00Z',
        'price': '9.95', 'variant_id': '0', 'inventory': 4,
        'untappd_rating': 4.42, 'untappd_checkins': 18234,
        'untappd_url': None, 'style': 'Lambiek/Geuze', 'abv': '6.0',
        'country': 'België', 'volume': '75 CL', 'deposit': '0.10',
        'cart_url': 'https://houseofbeers.nl/',
    },
    {
        'id': '2', 'title': 'Nevel Wilde Bosbes [DEMO]',
        'shopify_title': 'Demo - Z2 - Nevel Wilde Bosbes', 'handle': 'demo-2',
        'description': 'Demo-product zonder afbeelding, om de placeholder-weergave te zien.',
        'image_url': '',
        'tags': ['app-only'], 'created_at': '2026-08-05T10:00:00Z',
        'price': '7.50', 'variant_id': '0', 'inventory': 2,
        'untappd_rating': 3.98, 'untappd_checkins': 1543,
        'untappd_url': None, 'style': 'Wild Ale', 'abv': '5.5',
        'country': 'Nederland', 'volume': '37.5 CL', 'deposit': '0.10',
        'cart_url': 'https://houseofbeers.nl/',
    },
]


def _get_app_only_products() -> list:
    import os as _os
    if settings.DEBUG and _os.environ.get('APP_SHOP_DEMO') == '1':
        return _APP_SHOP_DEMO_PRODUCTS
    """App-only products (cached). Empty list is cached briefly (5 min):
    'no leftovers right now' is a normal state, unlike the active-product
    cache where empty means the fetch failed."""
    products = cache.get(APP_SHOP_CACHE_KEY)
    if products is None:
        products = ShopifyService().get_app_only_products()
        ttl = APP_SHOP_CACHE_TTL if products else 300
        cache.set(APP_SHOP_CACHE_KEY, products, ttl)
    return products


class AppShopView(APIView):
    """
    App-exclusive beers: leftover sale stock at the app price.

    GET /api/recommendations/app-shop/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            products = _get_app_only_products()
        except Exception as e:
            logger.error(f"App shop fetch failed: {e}")
            return Response(
                {'error': 'Could not load app shop products'},
                status=status.HTTP_502_BAD_GATEWAY
            )

        return Response({
            'products': [
                {
                    **product,
                    'cart_url': f"{SHOP_BASE_URL}/cart/{product['variant_id']}:1",
                }
                for product in products
                if product.get('variant_id')
            ]
        })


class SixpackRateThrottle(UserRateThrottle):
    scope = 'sixpack'
    rate = '60/hour'


class SixpackCheckoutRateThrottle(UserRateThrottle):
    scope = 'sixpack-checkout'
    rate = '10/hour'


class SixpackView(APIView):
    """
    Generate a personalized sixpack via the recommendation service.

    Completed responses get a `pricing` annotation (charm price). Pending
    responses carry a task_id; the client polls the status endpoint and then
    re-calls this view — the profile cache is warm by then, so the retry
    returns synchronously WITH pricing (the raw task result has none).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [SixpackRateThrottle]

    def post(self, request):
        user = request.user
        service = RecommendationService()

        serializer = SixpackGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        params['budget'] = float(params['budget'])

        untappd_profile = _get_untappd_profile(user)
        result = None
        profile_source = 'shopify'
        profile_identifier = user.email

        try:
            # Untappd first when linked. While Untappd profile building is
            # broken (waiting on the Untappd for Business API) the build task
            # fails fast against the cached-invalid profile and we fall back
            # to Shopify below — no code change needed once it works again.
            if untappd_profile:
                try:
                    result = service.get_sixpack(
                        username=untappd_profile.username, **params
                    )
                    # Poll INSIDE the try: a failed profile build raises and
                    # falls back to Shopify instead of surfacing an error.
                    if result.get('status') == 'pending' and result.get('task_id'):
                        result = service.poll_for_result(result['task_id'])
                    profile_source = 'untappd'
                    profile_identifier = untappd_profile.username
                except RecommendationAPIError as e:
                    logger.warning(
                        f"Untappd sixpack failed for {user.email} "
                        f"(username: {untappd_profile.username}): {e} — falling back to Shopify"
                    )
                    result = None
                    profile_source = 'shopify'
                    profile_identifier = user.email

            if result is None:
                result = service.get_sixpack(email=user.email, **params)
                if result.get('status') == 'pending' and result.get('task_id'):
                    result = service.poll_for_result(result['task_id'])

            if result.get('status') == 'pending' and result.get('task_id'):
                return Response({
                    'status': 'pending',
                    'task_id': result['task_id'],
                    'profile_source': profile_source,
                    'profile_identifier': profile_identifier,
                })

            pricing = charm_price(result.get('pack_value'))
            result['pricing'] = {
                'value': str(pricing['value']),
                'price': str(pricing['price']),
                'discount': str(pricing['discount']),
            }
            result['profile_source'] = profile_source

            from analytics.tracker import track
            track(
                'sixpack_generate', user=user,
                budget=params['budget'],
                adventurousness=params.get('adventurousness'),
                respin=bool(params.get('locked') or params.get('exclude')),
            )

            return Response(result)

        except RecommendationAPIError as e:
            logger.error(f"Sixpack API error for {user.email}: {e}")
            if e.status_code == 404:
                return Response({
                    'error': 'no_profile',
                    'message': 'No purchase history found yet. Start shopping '
                               'to get a personalized sixpack!',
                }, status=status.HTTP_404_NOT_FOUND)
            if e.status_code == 422:
                return Response(
                    {'error': 'not_enough_beers', 'message': str(e)},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY
                )
            return Response(
                {'error': str(e)},
                status=status.HTTP_502_BAD_GATEWAY
            )
        except Exception as e:
            logger.error(f"Unexpected sixpack error for {user.email}: {e}")
            return Response(
                {'error': 'Failed to generate sixpack'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


def _generate_sixpack_code() -> str:
    import secrets
    import string
    chars = string.ascii_uppercase + string.digits
    return 'SIX-' + ''.join(secrets.choice(chars) for _ in range(8))


class SixpackCheckoutView(APIView):
    """
    Mint the discount code for a sixpack and build the cart permalink.

    Pricing is server-authoritative: prices come from the cached Shopify
    product list keyed by shopify_id, never from the client. Identical packs
    reuse their stored code instead of minting a new one.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [SixpackCheckoutRateThrottle]

    CODE_VALIDITY_DAYS = 7
    REUSE_MIN_REMAINING_HOURS = 24

    def post(self, request):
        import hashlib
        from datetime import timedelta

        user = request.user
        serializer = SixpackCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data['items']

        products = _get_shop_products()
        if not products:
            return Response(
                {'error': 'Could not load shop products'},
                status=status.HTTP_502_BAD_GATEWAY
            )
        by_id = {str(p.get('id')): p for p in products}

        unavailable = [
            item['shopify_id'] for item in items
            if item['shopify_id'] not in by_id
            or _product_price(by_id[item['shopify_id']]) is None
        ]
        if unavailable:
            return Response(
                {'error': 'pack_unavailable', 'unavailable': unavailable},
                status=status.HTTP_409_CONFLICT
            )

        value = sum(
            _product_price(by_id[item['shopify_id']]) for item in items
        )
        pricing = charm_price(value)

        variant_ids = [item['variant_id'] for item in items]
        pack_hash = hashlib.sha256(
            ','.join(sorted(variant_ids)).encode()
        ).hexdigest()

        # Reuse an identical, still-valid pack instead of minting again.
        reuse_cutoff = timezone.now() + timedelta(hours=self.REUSE_MIN_REMAINING_HOURS)
        existing = SixpackCheckout.objects.filter(
            user=user, pack_hash=pack_hash,
            expires_at__gt=reuse_cutoff,
        ).exclude(discount_code='').first()
        if existing:
            return Response(self._response_payload(existing))

        cart_path = ','.join(f"{vid}:1" for vid in variant_ids)
        cart_url = f"{SHOP_BASE_URL}/cart/{cart_path}"

        code = ''
        shopify_discount_id = ''
        expires_at = None
        if pricing['discount'] > 0:
            code = _generate_sixpack_code()
            expires_at = timezone.now() + timedelta(days=self.CODE_VALIDITY_DAYS)
            # Minimum subtotal just under the pack value stops stripping the
            # cart down to one beer while keeping the full discount.
            minimum = (value * Decimal('0.98')).quantize(Decimal('0.01'))
            shopify_result = ShopifyService().create_basic_discount(
                code=code,
                title=f"Sixpack - {user.email}",
                discount_type='fixed_amount',
                value=float(pricing['discount']),
                usage_limit=1,
                applies_once_per_customer=True,
                ends_at=expires_at,
                minimum_subtotal=float(minimum),
            )
            if not shopify_result:
                logger.error(f"Sixpack discount creation failed for {user.email}")
                return Response(
                    {'error': 'discount_failed'},
                    status=status.HTTP_502_BAD_GATEWAY
                )
            shopify_discount_id = shopify_result.get('discount_id', '')
            cart_url = f"{cart_url}?discount={code}"

        checkout = SixpackCheckout.objects.create(
            user=user,
            pack_hash=pack_hash,
            items=[
                {
                    'shopify_id': item['shopify_id'],
                    'variant_id': item['variant_id'],
                    'title': by_id[item['shopify_id']].get('title', ''),
                    'price': str(_product_price(by_id[item['shopify_id']])),
                }
                for item in items
            ],
            pack_value=pricing['value'],
            charm_price=pricing['price'],
            discount_amount=pricing['discount'],
            discount_code=code,
            shopify_discount_id=shopify_discount_id,
            cart_url=cart_url,
            expires_at=expires_at,
        )

        from analytics.tracker import track
        track(
            'sixpack_checkout', user=user,
            value=str(pricing['value']), discount=str(pricing['discount']),
        )

        return Response(self._response_payload(checkout))

    @staticmethod
    def _response_payload(checkout: SixpackCheckout) -> dict:
        return {
            'cart_url': checkout.cart_url,
            'code': checkout.discount_code,
            'value': str(checkout.pack_value),
            'price': str(checkout.charm_price),
            'discount': str(checkout.discount_amount),
            'expires_at': checkout.expires_at.isoformat() if checkout.expires_at else None,
        }


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
