from __future__ import annotations

from datetime import date

from .base import (
    PRODUCT_CM,
    PRODUCT_DELIV,
    PRODUCT_FO,
    PRODUCT_IDX,
    BhavFile,
    Source,
)


def _month_abbr(day: date) -> str:
    return day.strftime("%b").upper()


def _suffix(day: date) -> str:
    return f"{day.strftime('%d')}{_month_abbr(day)}{day.year}"


def _ddmmyyyy(day: date) -> str:
    return day.strftime("%d%m%Y")


def cm_url(base_url: str, day: date) -> str:
    return (
        f"{base_url}/content/historical/EQUITIES/{day.year}/{_month_abbr(day)}/"
        f"cm{_suffix(day)}bhav.csv.zip"
    )


def cm_filename(day: date) -> str:
    return f"cm{_suffix(day)}bhav.csv"


def fo_url(base_url: str, day: date) -> str:
    return (
        f"{base_url}/content/historical/DERIVATIVES/{day.year}/{_month_abbr(day)}/"
        f"fo{_suffix(day)}bhav.csv.zip"
    )


def fo_zip_filename(day: date) -> str:
    return f"fo{_suffix(day)}bhav.csv.zip"


def fo_inner_filename(day: date) -> str:
    return f"fo{_suffix(day)}bhav.csv"


def index_url(base_url: str, day: date) -> str:
    return f"{base_url}/content/indices/ind_close_all_{_ddmmyyyy(day)}.csv"


def index_filename(day: date) -> str:
    return f"ind_close_all_{_ddmmyyyy(day)}.csv"


def deliverable_url(base_url: str, day: date) -> str:
    return f"{base_url}/products/content/sec_bhavdata_full_{_ddmmyyyy(day)}.csv"


def deliverable_filename(day: date) -> str:
    return f"sec_bhavdata_full_{_ddmmyyyy(day)}.csv"


class NSESource(Source):
    """Resolves files from the NSE historical archives host."""

    name = "nse"

    def __init__(self, base_url: str = "https://nsearchives.nseindia.com"):
        self.base_url = base_url

    def resolve(self, product: str, day: date) -> BhavFile | None:
        if product == PRODUCT_CM:
            return BhavFile(cm_url(self.base_url, day), cm_filename(day))
        if product == PRODUCT_FO:
            return BhavFile(fo_url(self.base_url, day), fo_inner_filename(day))
        if product == PRODUCT_IDX:
            return BhavFile(index_url(self.base_url, day), None)
        if product == PRODUCT_DELIV:
            return BhavFile(deliverable_url(self.base_url, day), None)
        raise ValueError(f"unknown product {product!r}")


NSE_ALTERNATE_BASES = ("https://nsearchives.nseindia.com", "https://archives.nseindia.com")