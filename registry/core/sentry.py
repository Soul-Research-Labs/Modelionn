"""Optional Sentry integration — initialise with SENTRY_DSN env var."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def init_sentry() -> None:
    """Configure Sentry SDK if SENTRY_DSN is set. No-op otherwise."""
    dsn = os.environ.get("SENTRY_DSN", "")
    if not dsn:
        return

    try:
        import sentry_sdk  # type: ignore[import-untyped]
        from sentry_sdk.integrations.asgi import SentryAsgiMiddleware  # noqa: F401
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration  # noqa: F401

        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.1")),
            profiles_sample_rate=float(os.environ.get("SENTRY_PROFILES_RATE", "0.1")),
            environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
            release=os.environ.get("SENTRY_RELEASE", "modelionn@0.1.0"),
            integrations=[SqlalchemyIntegration()],
        )
        logger.info("Sentry initialised (env=%s)", os.environ.get("SENTRY_ENVIRONMENT", "dev"))
    except ImportError:
        logger.warning("SENTRY_DSN set but sentry-sdk not installed — skipping")
