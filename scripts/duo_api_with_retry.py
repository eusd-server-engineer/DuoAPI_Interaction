#!/usr/bin/env python3
"""
Enhanced Duo API client with retry logic and better error handling
"""

import time
import logging
from typing import Dict, Optional, Callable, Any
from functools import wraps
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError


class DuoAPIError(Exception):
    """Base exception for Duo API errors"""
    pass


class DuoAuthenticationError(DuoAPIError):
    """Authentication failed"""
    pass


class DuoRateLimitError(DuoAPIError):
    """Rate limit exceeded"""
    pass


class DuoNotFoundError(DuoAPIError):
    """Resource not found"""
    pass


class DuoServerError(DuoAPIError):
    """Server error (5xx)"""
    pass


def exponential_backoff_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2,
    jitter: bool = True
):
    """
    Decorator for exponential backoff retry logic

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential calculation
        jitter: Add random jitter to prevent thundering herd
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (DuoRateLimitError, DuoServerError, Timeout, ConnectionError) as e:
                    last_exception = e

                    if attempt == max_retries:
                        break

                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)

                    # Add jitter if enabled
                    if jitter:
                        import random
                        delay = delay * (0.5 + random.random())

                    logging.warning(
                        f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                        f"Retrying in {delay:.2f} seconds..."
                    )
                    time.sleep(delay)
                except (DuoAuthenticationError, DuoNotFoundError) as e:
                    # Don't retry on authentication or not found errors
                    raise

            # If we've exhausted all retries, raise the last exception
            raise last_exception

        return wrapper
    return decorator


class RateLimiter:
    """Rate limiter to prevent hitting API limits"""

    def __init__(self, calls_per_minute: int = 50):
        self.calls_per_minute = calls_per_minute
        self.min_interval = 60.0 / calls_per_minute
        self.last_call_time = 0

    def wait_if_needed(self):
        """Wait if necessary to respect rate limit"""
        current_time = time.time()
        elapsed = current_time - self.last_call_time

        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            logging.debug(f"Rate limiting: sleeping for {sleep_time:.3f} seconds")
            time.sleep(sleep_time)

        self.last_call_time = time.time()


class EnhancedDuoAdminAPI:
    """Enhanced Duo Admin API client with retry and error handling"""

    def __init__(
        self,
        integration_key: str,
        secret_key: str,
        api_host: str,
        rate_limit: int = 50,
        timeout: int = 30,
        max_retries: int = 3
    ):
        self.ikey = integration_key
        self.skey = secret_key
        self.host = api_host
        self.base_url = f"https://{api_host}"
        self.rate_limiter = RateLimiter(rate_limit)
        self.timeout = timeout
        self.max_retries = max_retries

        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def _handle_response_errors(self, response: requests.Response):
        """Handle various HTTP response errors"""
        if response.status_code == 401:
            raise DuoAuthenticationError("Authentication failed. Check your API credentials.")
        elif response.status_code == 403:
            raise DuoAuthenticationError("Forbidden. Check API permissions.")
        elif response.status_code == 404:
            raise DuoNotFoundError("Resource not found.")
        elif response.status_code == 429:
            # Parse retry-after header if available
            retry_after = response.headers.get('Retry-After', '60')
            raise DuoRateLimitError(f"Rate limit exceeded. Retry after {retry_after} seconds.")
        elif response.status_code >= 500:
            raise DuoServerError(f"Server error {response.status_code}: {response.text}")
        elif response.status_code >= 400:
            raise DuoAPIError(f"Client error {response.status_code}: {response.text}")

    @exponential_backoff_retry(max_retries=3)
    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None
    ) -> Dict:
        """Make API request with retry logic"""
        # Apply rate limiting
        self.rate_limiter.wait_if_needed()

        # Your existing request logic here
        # (simplified for example)
        path = f"/admin/v1{endpoint}"
        url = f"{self.base_url}{path}"

        try:
            response = requests.request(
                method,
                url,
                params=params,
                timeout=self.timeout
            )

            # Check for HTTP errors
            self._handle_response_errors(response)
            response.raise_for_status()

            # Parse response
            result = response.json()

            if result.get('stat') != 'OK':
                error_msg = result.get('message', 'Unknown error')
                error_code = result.get('code', 'unknown')
                raise DuoAPIError(f"API error {error_code}: {error_msg}")

            return result.get('response', {})

        except Timeout:
            raise DuoAPIError(f"Request timed out after {self.timeout} seconds")
        except ConnectionError as e:
            raise DuoAPIError(f"Connection error: {e}")
        except RequestException as e:
            raise DuoAPIError(f"Request failed: {e}")

    def get_user_safe(self, username: str) -> Optional[Dict]:
        """
        Safely get user with proper error handling

        Returns:
            User dict if found, None if not found, raises exception on error
        """
        try:
            users = self._make_request('GET', '/users', {'username': username})
            return users[0] if users else None
        except DuoNotFoundError:
            return None
        except Exception as e:
            self.logger.error(f"Failed to get user {username}: {e}")
            raise

    def delete_user_safe(self, user_id: str) -> bool:
        """
        Safely delete user with proper error handling

        Returns:
            True if deleted, False on error
        """
        try:
            self._make_request('DELETE', f'/users/{user_id}')
            self.logger.info(f"Successfully deleted user {user_id}")
            return True
        except DuoNotFoundError:
            self.logger.warning(f"User {user_id} not found for deletion")
            return False
        except Exception as e:
            self.logger.error(f"Failed to delete user {user_id}: {e}")
            return False

    def bulk_delete_users_safe(
        self,
        user_ids: list,
        batch_size: int = 10,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, list]:
        """
        Safely delete multiple users with batching and progress tracking

        Args:
            user_ids: List of user IDs to delete
            batch_size: Number of users to delete in each batch
            progress_callback: Optional callback for progress updates

        Returns:
            Dict with 'success' and 'failed' lists
        """
        results = {'success': [], 'failed': []}
        total = len(user_ids)

        for i in range(0, total, batch_size):
            batch = user_ids[i:i + batch_size]

            for user_id in batch:
                if self.delete_user_safe(user_id):
                    results['success'].append(user_id)
                else:
                    results['failed'].append(user_id)

                # Call progress callback if provided
                if progress_callback:
                    processed = len(results['success']) + len(results['failed'])
                    progress_callback(processed, total)

            # Add extra delay between batches
            if i + batch_size < total:
                time.sleep(2)

        return results


# Example usage with the new error handling
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    # Create enhanced API client
    api = EnhancedDuoAdminAPI(
        integration_key=os.getenv('DUO_IKEY'),
        secret_key=os.getenv('DUO_SKEY'),
        api_host=os.getenv('DUO_HOST'),
        rate_limit=50,  # 50 calls per minute
        timeout=30,      # 30 second timeout
        max_retries=3    # 3 retry attempts
    )

    # Example: Get user with proper error handling
    try:
        user = api.get_user_safe('123456')
        if user:
            print(f"Found user: {user['username']}")
        else:
            print("User not found")
    except DuoAuthenticationError:
        print("Authentication failed. Check your API credentials.")
    except DuoRateLimitError as e:
        print(f"Rate limit hit: {e}")
    except DuoAPIError as e:
        print(f"API error: {e}")