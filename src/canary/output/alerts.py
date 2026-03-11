"""Alert dispatch stub — console logging only for Phase 1."""

import logging

logger = logging.getLogger(__name__)


async def dispatch_alerts(report: str, severity: str) -> None:
    """Stub: log alert to console. Telegram/Teams dispatch in Phase 3."""
    if severity == "high":
        logger.warning("HIGH SEVERITY change detected — alert would be dispatched")
    else:
        logger.info("Change report generated (severity: %s)", severity)
