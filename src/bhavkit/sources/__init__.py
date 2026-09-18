from __future__ import annotations

from .base import (
    ALL_PRODUCTS,
    PHASE1_PRODUCTS,
    PRODUCT_CM,
    PRODUCT_DELIV,
    PRODUCT_FO,
    PRODUCT_IDX,
    Source,
)


def make_source(cfg) -> Source:
    """Build the configured Source (nse or local)."""
    from .local import LocalSource
    from .nse import NSESource

    if cfg.source == "local":
        if cfg.local_dir is None:
            raise ValueError("source=local requires local_dir to be configured")
        return LocalSource(cfg.local_dir)
    return NSESource(cfg.nse_base_url)


__all__ = [
    "ALL_PRODUCTS",
    "PHASE1_PRODUCTS",
    "PRODUCT_CM",
    "PRODUCT_DELIV",
    "PRODUCT_FO",
    "PRODUCT_IDX",
    "Source",
    "make_source",
]