"""Text normalization and hashing for change detection."""

import hashlib
import re


def normalize_text(text: str) -> str:
    """Collapse whitespace and lowercase for stable comparison."""
    return re.sub(r"\s+", " ", text).strip().lower()


def compute_hash(text: str) -> str:
    """SHA-256 hash of normalized text."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
