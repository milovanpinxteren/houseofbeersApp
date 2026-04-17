"""
Service to proxy requests to the Beer Recommender API.
"""

import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Beer Recommender API base URL
RECOMMENDER_API_URL = getattr(
    settings,
    'RECOMMENDER_API_URL',
    'https://recommendation.houseofbeers.nl/api'
)


class RecommendationService:
    """Proxy service for the Beer Recommender API."""

    def __init__(self):
        self.base_url = RECOMMENDER_API_URL
        self.timeout = 120  # Recommendations can take time for new users

    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make HTTP request to recommendation API."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        kwargs.setdefault('timeout', self.timeout)

        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            logger.error(f"Timeout calling {url}")
            raise RecommendationAPIError("Request timed out. Please try again.")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error from {url}: {e.response.status_code} - {e.response.text}")
            # Try to extract error message from response
            try:
                error_data = e.response.json()
                error_msg = error_data.get('error') or error_data.get('detail') or str(e)
            except Exception:
                error_msg = str(e)
            raise RecommendationAPIError(error_msg, status_code=e.response.status_code)
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error calling {url}: {e}")
            raise RecommendationAPIError("Failed to connect to recommendation service.")

    def get_recommendations(
        self,
        email: str = None,
        username: str = None,
        limit: int = 10,
        price_max: float = None,
        style_filter: str = None
    ) -> dict:
        """
        Get beer recommendations for a user.

        Args:
            email: Shopify customer email (for order-based profile)
            username: Untappd username (for Untappd-based profile)
            limit: Number of recommendations to return
            price_max: Maximum price filter
            style_filter: Filter by beer style

        Returns:
            Recommendation result with profile summary, recommendations, etc.
        """
        if not email and not username:
            raise ValueError("Either email or username must be provided")

        payload = {'limit': limit}

        if email:
            payload['email'] = email
        else:
            payload['username'] = username

        if price_max is not None:
            payload['price_max'] = float(price_max)
        if style_filter:
            payload['style_filter'] = style_filter

        return self._make_request('POST', '/recommendations/', json=payload)

    def get_task_status(self, task_id: str) -> dict:
        """Poll for async task status."""
        return self._make_request('GET', f'/tasks/{task_id}/')

    def get_profile(self, identifier: str, profile_type: str = 'untappd') -> dict:
        """
        Get detailed taste profile for visualization.

        Args:
            identifier: Email or Untappd username
            profile_type: 'untappd' or 'shopify'
        """
        params = {}
        if profile_type == 'shopify':
            params['type'] = 'shopify'

        return self._make_request('GET', f'/profile/{identifier}/', params=params)

    def get_styles(self) -> dict:
        """Get available beer styles for filtering."""
        return self._make_request('GET', '/styles/')

    def poll_for_result(self, task_id: str, max_attempts: int = 60, interval: float = 2.0) -> dict:
        """
        Poll for task completion.

        Args:
            task_id: Celery task ID
            max_attempts: Maximum polling attempts
            interval: Seconds between polls

        Returns:
            Final result when task completes
        """
        import time

        for attempt in range(max_attempts):
            result = self.get_task_status(task_id)

            if result.get('status') == 'completed':
                return result.get('result', result)
            elif result.get('status') == 'failed':
                raise RecommendationAPIError(
                    result.get('error', 'Task failed')
                )

            time.sleep(interval)

        raise RecommendationAPIError("Recommendation generation timed out")


class RecommendationAPIError(Exception):
    """Exception for recommendation API errors."""

    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code
