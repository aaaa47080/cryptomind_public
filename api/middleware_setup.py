"""Middleware registration — CORS, GZip, rate limiting, security headers, etc."""

import os
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from api.utils import logger


def get_security_config() -> dict:
    """Read security middleware settings and reject unsafe production defaults."""
    is_production = os.getenv("ENVIRONMENT", "development").lower() in {
        "production",
        "prod",
    }
    origins = [
        # Strip trailing slash: browsers send Origin without one
        # (https://host), so an allowlist entry like https://host/ would never
        # match and silently block legit cross-origin requests.
        origin.strip().rstrip("/")
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:8080").split(",")
        if origin.strip()
    ]
    allowed_hosts = [
        host.strip()
        for host in os.getenv("ALLOWED_HOSTS", "").split(",")
        if host.strip()
    ]

    if is_production:
        if not origins or "*" in origins:
            raise RuntimeError(
                "CORS_ORIGINS must list explicit HTTPS origins in production."
            )
        if not allowed_hosts:
            raise RuntimeError(
                "ALLOWED_HOSTS is required in production to enable host-header protection."
            )

    return {
        "is_production": is_production,
        "origins": origins,
        "allowed_hosts": allowed_hosts,
    }


def setup_middleware(app: FastAPI) -> None:
    """Register all middleware and exception handlers on the FastAPI app."""

    security_config = get_security_config()
    is_production = security_config["is_production"]

    # --- Global Exception Handler (Fix 500 Internal Server Error) ---
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """
        Catch-all exception handler to ensure all 500 errors return JSON
        and are properly logged with traceback.

        Stage 2 Security: Hide error details in production to prevent
        information leakage.
        """
        import traceback

        error_msg = f"{type(exc).__name__}: {str(exc)}"

        # Log full details for debugging
        logger.error(
            f"🔥 Unhandled 500 Error at {request.method} {request.url.path}: {error_msg}"
        )
        if not is_production:
            logger.error(traceback.format_exc())

        # Response varies by environment - hide details in production
        # Uses structured APIErrorResponse format for consistency
        response_content = {
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An error occurred" if is_production else error_msg,
                "path": request.url.path,
            },
        }

        return JSONResponse(status_code=500, content=response_content)

    # ================================================================
    # Security Enhancements (Phase 7)
    # ================================================================

    # --- 1. Rate Limiting ---
    try:
        from slowapi.errors import RateLimitExceeded

        from api.middleware.rate_limit import limiter, rate_limit_exceeded_handler

        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]
        logger.info("✅ Rate limiting enabled")
    except ImportError as e:
        logger.warning(f"⚠️ Rate limiting not available: {e}")
        logger.warning("Install slowapi: pip install slowapi")

    # --- 2. Audit Logging Middleware ---
    try:
        from api.middleware.audit import audit_middleware

        @app.middleware("http")
        async def audit_logging(request, call_next):
            """Audit all API requests"""
            return await audit_middleware(request, call_next)

        logger.info("✅ Audit logging enabled")
    except ImportError as e:
        logger.warning(f"⚠️ Audit logging not available: {e}")

    # --- 3. CORS ---
    # 🔒 Security: Read allowed origins from environment variable
    # Default to localhost for development, production MUST override this
    origins = security_config["origins"]

    # Security check: warn if wildcard is accidentally configured
    if "*" in origins or "" in origins:
        logger.warning(
            "⚠️ SECURITY: Wildcard CORS origin detected!"
            " This should NOT be used in production."
        )

    logger.info(f"🔒 CORS allowed origins: {origins}")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-API-Key",
            "X-OKX-API-KEY",
        ],
    )

    # --- 4. GZip Compression (Performance Optimization) ---
    # 自動壓縮大於1KB的響應，減少帶寬消耗，提升加載速度
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    logger.info("✅ GZip compression enabled")

    # --- 5. Security Headers Middleware (Stage 2 Security) ---
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        """
        Stage 2 Security: Add security headers to all responses.

        Headers added:
        - X-Content-Type-Options: Prevent MIME type sniffing
        - X-Frame-Options: Prevent clickjacking
        - X-XSS-Protection: Enable XSS filter
        - Referrer-Policy: Control referrer information
        - Strict-Transport-Security (production): Force HTTPS
        - Content-Security-Policy (production): Control resource loading
        """
        response = await call_next(request)

        # Cache-Control for static assets
        # HTML files: no-cache allows BFCache (Back-Forward Cache) in WebViews
        #   so TON wallets (Tonkeeper, etc.) can restore full JS state when user switches back.
        # JS/CSS/images: no-store prevents stale assets (deployed with ?v= hash).
        _static_prefixes = ("/static/", "/js/", "/css/", "/scam-tracker/")
        if any(request.url.path.startswith(p) for p in _static_prefixes):
            if request.url.path.endswith((".html", ".htm")):
                response.headers["Cache-Control"] = "no-cache"
            else:
                response.headers["Cache-Control"] = (
                    "no-cache, no-store, must-revalidate"
                )

        # Basic security headers (always on)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # X-Frame-Options intentionally omitted — TON wallet apps load DApps in
        # WebView; frame-ancestors is controlled via CSP below.
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Production-only headers (require HTTPS)
        if is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
            # script-src stays strict (no inline scripts) — that is the
            # XSS-critical directive. style-src needs 'unsafe-inline' because
            # TON Connect UI injects dynamic inline styles (CSP hashes cannot
            # cover style attributes), and connect-src needs https: because the
            # TON Connect wallet list resolves to per-wallet bridge origins
            # that change as wallets are added.
            # script-src needs 'unsafe-inline' because TON Connect SDK v3
            # injects inline event handlers (without hash) into the DOM.
            # Without 'unsafe-inline', these handlers are blocked → SDK
            # connection fails → "Operation aborted" / "Manifest not found".
            # This is a security trade-off: TON Connect requires it.
            # Mitigation: CSP report-only mode could be used for monitoring,
            # but for now 'unsafe-inline' is required for functionality.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' "
                "https://cdn.jsdelivr.net https://unpkg.com "
                "https://cdnjs.cloudflare.com https://telegram.org; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
                "https://unpkg.com https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data: https:; "
                "connect-src 'self' https: wss: ws:; "
                "worker-src 'self'; "
                "frame-ancestors 'self'"
            )

        return response

    logger.info("✅ Security headers enabled")

    # --- 6. TrustedHostMiddleware (production) ---
    if is_production:
        allowed_hosts = security_config["allowed_hosts"]
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
        logger.info("✅ TrustedHostMiddleware enabled: %s", allowed_hosts)

    # --- 7. Request ID Middleware ---
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    logger.info("✅ Request ID middleware enabled")
