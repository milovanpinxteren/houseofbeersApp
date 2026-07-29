"""
Service to proxy requests to the Beer Recommender API.
"""

import logging
import time
from urllib.parse import quote

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Total wall-clock budget for one web request's upstream work. Individual
# timeouts are not enough on their own: a request can try Untappd, poll, then
# fall back to Shopify and poll again. Without a shared budget those stack well
# past gunicorn's 30s worker timeout and the worker gets killed mid-request.
REQUEST_BUDGET_SECONDS = 20


class Deadline:
    """Shared wall-clock budget across every upstream call in one request."""

    def __init__(self, seconds: float = REQUEST_BUDGET_SECONDS):
        self._expires_at = time.monotonic() + seconds

    def remaining(self) -> float:
        return max(0.0, self._expires_at - time.monotonic())

    def expired(self, min_useful: float = 1.0) -> bool:
        """True when too little time is left for another upstream call."""
        return self.remaining() < min_useful

# Beer Recommender API base URL
RECOMMENDER_API_URL = getattr(
    settings,
    'RECOMMENDER_API_URL',
    'https://recommendation.houseofbeers.nl/api'
)


class RecommendationService:
    """Proxy service for the Beer Recommender API."""

    def __init__(self, deadline: 'Deadline' = None):
        self.base_url = RECOMMENDER_API_URL
        # Keep well under gunicorn's 30s worker timeout. Long-running profile
        # builds are handled asynchronously via the pending/task-status flow.
        self.timeout = 15
        # Shared across all calls made while serving one request, so retries
        # and fallbacks cannot stack past the worker timeout.
        self.deadline = deadline or Deadline()

    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make HTTP request to recommendation API."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        # Never wait longer than the request's remaining budget allows.
        timeout = min(kwargs.pop('timeout', self.timeout), self.deadline.remaining())
        if timeout <= 0:
            raise RecommendationAPIError("Request budget exhausted. Please try again.")
        kwargs['timeout'] = timeout

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

    def get_task_status(self, task_id: str, timeout: int = None) -> dict:
        """Poll for async task status."""
        kwargs = {}
        if timeout is not None:
            kwargs['timeout'] = timeout
        return self._make_request('GET', f'/tasks/{quote(task_id, safe="")}/', **kwargs)

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

        return self._make_request(
            'GET', f'/profile/{quote(identifier, safe="")}/', params=params
        )

    def get_styles(self) -> dict:
        """Get available beer styles for filtering."""
        return self._make_request('GET', '/styles/')

    def poll_for_result(self, task_id: str, max_attempts: int = 3, interval: float = 2.0) -> dict:
        """
        Short inline poll for task completion (fast path only).

        Long-running tasks are NOT awaited here — if the task is still pending
        after max_attempts, the still-pending status dict is returned so the
        caller can hand the task_id to the client for long polling.

        Args:
            task_id: Celery task ID
            max_attempts: Maximum polling attempts (kept small to stay within
                the web request budget)
            interval: Seconds between polls

        Returns:
            Final result if the task completed, otherwise the pending status dict

        Raises:
            RecommendationAPIError: if the task failed
        """
        for attempt in range(max_attempts):
            # Stop early rather than eating budget the caller still needs for
            # its Shopify fallback — the client polls for the rest.
            if self.deadline.expired(min_useful=interval + 5):
                break
            # The task was just dispatched — give it a moment before checking
            time.sleep(interval)
            # Short timeout: status checks are lightweight, and the whole
            # inline poll must stay within the web request budget
            result = self.get_task_status(task_id, timeout=5)

            if result.get('status') == 'completed':
                return result.get('result', result)
            elif result.get('status') == 'failed':
                raise RecommendationAPIError(
                    result.get('error', 'Task failed')
                )

        # Still pending — return it so the caller can defer to client-side polling
        return {'status': 'pending', 'task_id': task_id}


class RecommendationAPIError(Exception):
    """Exception for recommendation API errors."""

    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code
