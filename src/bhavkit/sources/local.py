from __future__ import annotations

from datetime import date
from pathlib import Path

from .base import PRODUCT_CM, PRODUCT_DELIV, PRODUCT_FO, PRODUCT_IDX, BhavFile, Source
from .nse import (
    cm_filename,
    deliverable_filename,
    fo_inner_filename,
    fo_zip_filename,
    index_filename,
)


class LocalSource(Source):
    """Offline mirror: reads files from a local directory tree.

    Expected layout:
        <local_dir>/<product>/<YYYY>/<MMM>/<filename>
    e.g. local/cm/2024/JAN/cm01JAN2024bhav.csv[.zip]
         local/fo/2024/JAN/fo01JAN2024bhav.csv.zip
         local/idx/2024/JAN/ind_close_all_01012024.csv
         local/deliv/2024/JAN/sec_bhavdata_full_01012024.csv
    """

    name = "local"

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def resolve(self, product: str, day: date) -> BhavFile | None:
        subdir = self.base_dir / product / str(day.year) / day.strftime("%b").upper()
        candidates: tuple[Path, ...]
        if product == PRODUCT_CM:
            candidates = (
                subdir / cm_filename(day),
                subdir / f"{cm_filename(day)}.zip",
            )
        elif product == PRODUCT_FO:
            candidates = (subdir / fo_zip_filename(day),)
        elif product == PRODUCT_IDX:
            candidates = (subdir / index_filename(day),)
        elif product == PRODUCT_DELIV:
            candidates = (subdir / deliverable_filename(day),)
        else:
            raise ValueError(f"unknown product {product!r}")
        for candidate in candidates:
            if candidate.is_file():
                inner = fo_inner_filename(day) if product == PRODUCT_FO else None
                return BhavFile(candidate.as_posix(), inner)
        return None