"""Source abstraction: each source resolves a (product, date) pair to a file."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

PRODUCT_CM = "cm"
PRODUCT_FO = "fo"
PRODUCT_IDX = "idx"
PRODUCT_DELIV = "deliv"
PRODUCT_MASTER = "master"

ALL_PRODUCTS = (PRODUCT_CM, PRODUCT_FO, PRODUCT_IDX, PRODUCT_DELIV)
PHASE1_PRODUCTS = (PRODUCT_CM,)


@dataclass(frozen=True)
class BhavFile:
    """A resolved data file: either a remote URL or a local filesystem path."""

    url: str
    inner_name: str | None = None

    @property
    def is_local(self) -> bool:
        return self.url.startswith("file://") or (":" not in self.url)


class Source:
    """Interface for resolving product/day files.

    Subclasses implement `resolve`; returning None means the product is not
    available for that day (e.g. non-trading day handled by the fetcher).
    """

    name: str = "base"

    def resolve(self, product: str, day: date) -> BhavFile | None:  # pragma: no cover
        raise NotImplementedError