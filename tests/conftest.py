from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

SAMPLE_HEADER = (
    "SYMBOL, SERIES,DATE, PREV_CLOSE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,LAST_PRICE,"
    "CLOSE_PRICE,AVG_PRICE,TTL_TRD_QNTY,TURNOVER_LACS,NO_OF_TRADES,DELIV_QTY,DELIV_PER"
)
SAMPLE_ROWS = [
    "SBIN,EQ,03-JAN-2024,620.00,626.00,635.50,621.10,631.00,632.00,628.50,4420123,278012.45,185432,1000000,84.32",
    "tcs,EQ,03-JAN-2024,3800.00,3810.00,3860.00,3795.00,3850.00,3852.00,3830.00,1200000,920000.10,32111,850000,78.00",
    "RELIANCE,EQ,03-JAN-2024,2550.00,2560.00,2586.00,2550.00,2580.00,2583.00,2570.00,980000,501233.90,45210,700000,90.50",
    "INFY,BE,03-JAN-2024,1400.00,1405.00,1410.00,1380.00,1395.00,1392.00,1390.00,500000,200000.00,15000,0,0.00",
]


@pytest.fixture
def sample_csv_content() -> str:
    return SAMPLE_HEADER + "\n" + "\n".join(SAMPLE_ROWS) + "\n"


@pytest.fixture
def sample_csv_bytes(sample_csv_content: str) -> bytes:
    return sample_csv_content.encode()


@pytest.fixture
def sample_zip_bytes(sample_csv_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("cm03JAN2024bhav.csv", sample_csv_bytes)
    return buf.getvalue()


@pytest.fixture
def sample_zip_path(tmp_path: Path, sample_zip_bytes: bytes) -> Path:
    path = tmp_path / "cm03JAN2024bhav.csv.zip"
    path.write_bytes(sample_zip_bytes)
    return path


@pytest.fixture(scope="session")
def tcs_row() -> list[str]:
    return SAMPLE_ROWS[1].split(",")


@pytest.fixture
def local_mirror(tmp_path: Path):
    """Create an empty local mirror dir; returns (mirror_root, write_fn)."""

    def write(day: date, content: bytes) -> Path:
        subdir = tmp_path / "mirror" / "cm" / str(day.year) / day.strftime("%b").upper()
        subdir.mkdir(parents=True, exist_ok=True)
        name = f"cm{day.strftime('%d')}{day.strftime('%b').upper()}{day.year}bhav.csv"
        (subdir / name).write_bytes(content)
        return subdir / name

    return tmp_path / "mirror", write