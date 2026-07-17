"""Custom middleware for the application."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses.

    These headers help protect against common web vulnerabilities:
    - XSS attacks
    - Clickjacking
    - MIME type sniffing
    - Information disclosure
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Prevent clickjacking - page cannot be embedded in frames
        response.headers["X-Frame-Options"] = "DENY"

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Enable XSS protection in older browsers
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Control referrer information sent with requests
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content-Security-Policy. This is a JSON API, so the default denies all
        # resource loads. The interactive docs (/docs, /redoc) render HTML that
        # pulls Swagger UI / ReDoc assets from jsDelivr and use inline
        # script/style, so they get a scoped relaxation (docs are disabled in
        # production anyway).
        path = request.url.path
        if path.startswith(("/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; "
                "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                "img-src 'self' https://cdn.jsdelivr.net https://fastapi.tiangolo.com data:; "
                "font-src 'self' https://cdn.jsdelivr.net; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
            )
        else:
            response.headers["Content-Security-Policy"] = settings.CONTENT_SECURITY_POLICY

        # Prevent caching of sensitive data
        if request.url.path.startswith("/api/v1/auth"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"

        # Add HSTS header in production (tells browsers to only use HTTPS)
        if settings.is_production:
            # max-age=31536000 = 1 year
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # Remove server identification headers
        if "server" in response.headers:
            del response.headers["server"]

        # Permissions Policy (formerly Feature Policy)
        # Restrict access to browser features
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), "
            "payment=(), usb=(), magnetometer=(), gyroscope=()"
        )

        return response
