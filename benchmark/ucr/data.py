"""The UCR Time Series Anomaly Archive (Wu & Keogh, 2021), pinned by the archive's SHA-256.

250 series, each with exactly one anomaly. Everything a series needs is in its file name:

    <number>_UCR_Anomaly_<name>_<train end>_<anomaly begin>_<anomaly end>.txt

The first <train end> points are anomaly-free; the anomaly lies in the rest. Positions are 1-based,
as published (the archive was built in MATLAB). The archive is downloaded from UCR's site into the
gitignored cache and only the series files are extracted; it is never vendored.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from benchmark.fetch import CACHE_DIR, CheckoutError, ensure_download

ARCHIVE_URL = "https://www.cs.ucr.edu/~eamonn/time_series_data_2018/UCR_TimeSeriesAnomalyDatasets2021.zip"
ARCHIVE_SHA256 = "ac4b991c701e620ae9cc5ebd57ae45593a36cc9c0b6ed5e3c4b7e466cf4783d4"
CACHE = CACHE_DIR / "ucr"
MEMBER_DIR = "AnomalyDatasets_2021/UCR_TimeSeriesAnomalyDatasets2021/FilesAreInHere/UCR_Anomaly_FullData/"
SERIES_COUNT = 250

FILE_NAME = re.compile(r"^(\d+)_UCR_Anomaly_(.+?)_(\d+)_(\d+)_(\d+)\.txt$")
VARIANTS = ("DISTORTED", "NOISE")

# Source recordings grouped by domain, from the archive's own description of each dataset
# (UCR_AnomalyDataSets.pptx in the archive). First match wins.
DOMAINS = (
    ("Insect feeding (EPG)", r"EPG"),
    ("Respiration", r"resperation"),
    ("Gait and motion", r"gait|Walking|weallwalk|park3m|GP711Marker|taichidb"),
    ("Power demand", r"(?i)powerdemand"),
    ("Air temperature", r"CIMIS44AirTemperature"),
    ("Spacecraft telemetry (NASA)", r"MARS"),
    ("Whale accelerometer", r"MesoplodonDensirostris"),
    (
        "Cardiovascular (ECG, blood pressure)",
        r"ECG|ecg|sddb|BIDMC|STAFFIII|ltstdb|qtdb|s20101|sel840m|Fantasia|tilt|InternalBleeding|CHARIS",
    ),
)


@dataclass(slots=True)
class UcrSeries:
    number: int
    file: str
    name: str
    source: str
    variant: str
    domain: str
    train_end: int
    begin: int
    end: int
    values: np.ndarray


def ensure_ucr() -> Path:
    """The directory of the 250 series files, downloading and extracting the archive if needed."""
    series_dir = CACHE / MEMBER_DIR
    if len(list(series_dir.glob("*.txt"))) == SERIES_COUNT:
        return series_dir
    archive = ensure_download(ARCHIVE_URL, ARCHIVE_SHA256, CACHE / "UCR_TimeSeriesAnomalyDatasets2021.zip")
    with zipfile.ZipFile(archive) as bundle:
        members = [name for name in bundle.namelist() if name.startswith(MEMBER_DIR) and name.endswith(".txt")]
        bundle.extractall(CACHE, members)
    found = len(list(series_dir.glob("*.txt")))
    if found != SERIES_COUNT:
        raise CheckoutError(f"{series_dir} has {found} series files, expected {SERIES_COUNT}")
    return series_dir


def series_files(series_dir: Path) -> list[Path]:
    return sorted(series_dir.glob("*.txt"), key=lambda path: int(path.name.split("_", 1)[0]))


def parse_file_name(file_name: str) -> dict[str, object]:
    match = FILE_NAME.match(file_name)
    if not match:
        raise ValueError(f"not a UCR anomaly series file name: {file_name}")
    number, name, train_end, begin, end = match.groups()
    variant = next((prefix for prefix in VARIANTS if name.startswith(prefix)), "")
    source = name[len(variant):]
    return {
        "number": int(number),
        "name": name,
        "source": source,
        "variant": variant.lower() or "original",
        "domain": domain_of(source),
        "train_end": int(train_end),
        "begin": int(begin),
        "end": int(end),
    }


def domain_of(source: str) -> str:
    return next((domain for domain, pattern in DOMAINS if re.search(pattern, source)), "Other")


def load_series(path: Path) -> UcrSeries:
    # Most files hold one value per line; a few hold every value on one line. Splitting on any
    # whitespace reads both.
    values = np.array(path.read_text(encoding="utf-8").split(), dtype=float)
    meta = parse_file_name(path.name)
    if not meta["train_end"] < meta["begin"] <= meta["end"] <= len(values):
        raise ValueError(f"{path.name}: labels don't fit a series of {len(values)} points")
    return UcrSeries(file=path.name, values=values, **meta)
