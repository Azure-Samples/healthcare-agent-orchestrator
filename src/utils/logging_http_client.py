# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Custom HTTPX client with request/response logging."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LoggingHTTPXClient(httpx.AsyncClient):
    """
    Custom HTTPX async client that logs all requests and responses.

    This client extends httpx.AsyncClient to provide detailed logging of:
    - Request method, URL, headers, and body
    - Response status, headers, and body
    """

    async def send(self, request: httpx.Request, *args: Any, **kwargs: Any) -> httpx.Response:
        """
        Send an HTTP request with logging.

        Args:
            request: The HTTP request to send
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments

        Returns:
            The HTTP response
        """
        # Log the request
        logger.info(f"HTTP Request: {request.method} {request.url}")
        logger.debug(f"Request Headers: {dict(request.headers)}")

        if request.content:
            try:
                # Try to decode and log request body
                body_text = request.content.decode('utf-8')
                logger.debug(f"Request Body: {body_text}")
            except (UnicodeDecodeError, AttributeError):
                logger.debug(f"Request Body: <binary content, {len(request.content)} bytes>")

        # Send the request
        response = await super().send(request, *args, **kwargs)

        # Log the response
        logger.info(f"HTTP Response: {response.status_code} for {request.method} {request.url}")
        logger.debug(f"Response Headers: {dict(response.headers)}")

        try:
            # Try to log response body
            response_text = response.text
            if len(response_text) > 1000:
                logger.debug(f"Response Body (truncated): {response_text[:1000]}...")
            else:
                logger.debug(f"Response Body: {response_text}")
        except Exception as e:
            logger.debug(f"Response Body: <unable to decode: {e}>")

        return response


def create_logging_http_client(timeout) -> LoggingHTTPXClient:
    """
    Create a logging HTTPX client with default settings.

    Args:
        timeout: The timeout setting for the HTTP client.

    Returns:
        A configured LoggingHTTPXClient instance
    """

    return LoggingHTTPXClient(timeout=timeout)
