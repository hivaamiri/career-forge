"""Canonical URL Resolver for unwrapping click-tracking redirects and normalizing job links."""

from __future__ import annotations

import logging
from typing import Optional, Set
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

logger = logging.getLogger(__name__)

# Standard tracking parameters to strip for canonical deduplication
TRACKING_PARAMS: Set[str] = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "trackingid",
    "refid",
    "mid",
    "trk",
    "trkid",
    "clickid",
    "mc_cid",
    "mc_eid",
    "fbclid",
    "gclid",
    "igshid",
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def strip_tracking_params(url: str) -> str:
    """Strip known marketing tracking parameters from a URL."""
    try:
        parsed = urlparse(url)
        query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
        cleaned_pairs = [
            (k, v) for k, v in query_pairs if k.lower() not in TRACKING_PARAMS
        ]
        new_query = urlencode(cleaned_pairs)
        # Also strip trailing fragments that might carry tracking tokens
        return urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, "")
        )
    except Exception as e:
        logger.warning(f"Failed to strip tracking parameters from '{url}': {e}")
        return url


def resolve_canonical_url(
    raw_url: str,
    timeout: float = 10.0,
    client: Optional[httpx.Client] = None,
) -> str:
    """Unwrap redirects using HTTP HEAD/GET and normalize the target URL."""
    cleaned_original = strip_tracking_params(raw_url)
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
    }

    def _do_resolve(http_client: httpx.Client) -> str:
        final_url = cleaned_original
        try:
            # First try HEAD request to save bandwidth
            response = http_client.head(
                raw_url,
                headers=headers,
                follow_redirects=True,
                timeout=timeout,
            )
            final_url = str(response.url)
        except (httpx.HTTPStatusError, httpx.RequestError) as head_err:
            # Some servers reject HEAD requests with 405 Method Not Allowed or 403 Forbidden
            logger.debug(f"HEAD failed for {raw_url} ({head_err}), falling back to GET")
            try:
                response = http_client.get(
                    raw_url,
                    headers=headers,
                    follow_redirects=True,
                    timeout=timeout,
                )
                final_url = str(response.url)
            except Exception as get_err:
                logger.warning(
                    f"Redirect unwrap failed for {raw_url} ({get_err}), using stripped original URL"
                )
                return cleaned_original
        except Exception as e:
            logger.warning(f"Unexpected error resolving {raw_url}: {e}")
            return cleaned_original

        return strip_tracking_params(final_url)

    if client:
        return _do_resolve(client)

    with httpx.Client(timeout=timeout) as new_client:
        return _do_resolve(new_client)
