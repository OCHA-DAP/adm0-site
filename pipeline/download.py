"""Download every source into ``tmp/download/{source}/`` with a ``.date`` file."""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from fnmatch import filter as fnfilter
from logging import getLogger
from shutil import rmtree
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from httpx2 import Client, HTTPStatusError, Timeout, TransportError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .config import (
    FIELDMAPS_LICENSE,
    FIELDMAPS_URL,
    GAUL_URL,
    LAND_OSM_URL,
    LAND_WP_URL,
    LSIB_META_URL,
    LSIB_NS,
    LSIB_URL,
    M49_URL,
    UNTERM_URL,
    download_dir,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (adm0-site)"}


def _transient(e: BaseException) -> bool:
    """Retry network failures, rate limits and server errors, not 4xx."""
    if isinstance(e, HTTPStatusError):
        code = e.response.status_code
        return code == 429 or code >= 500  # noqa: PLR2004
    return isinstance(e, TransportError)


_retry = retry(
    retry=retry_if_exception(_transient),
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=2, max=60),
    reraise=True,
)


def _client() -> Client:
    return Client(
        http2=True,
        timeout=Timeout(60, connect=30),
        headers=HEADERS,
        follow_redirects=True,
    )


@_retry
def _stream(url: str, dest: Path) -> str | None:
    """Stream ``url`` to ``dest`` and return its Last-Modified date, if any."""
    with _client() as client, client.stream("GET", url) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            f.writelines(r.iter_bytes(chunk_size=4 * 1024 * 1024))
        modified = r.headers.get("last-modified")
    return parsedate_to_datetime(modified).date().isoformat() if modified else None


def _zip(url: str, out: Path, only: str | None = None) -> str | None:
    tmp = out / ".tmp"
    try:
        date = _stream(url, tmp)
        with ZipFile(tmp) as z:
            z.extractall(out, fnfilter(z.namelist(), only) if only else None)
    finally:
        tmp.unlink(missing_ok=True)
    return date


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _gaul(out: Path) -> str:
    return _zip(GAUL_URL, out) or _today()


def _osm(out: Path) -> str:
    date = _zip(LAND_OSM_URL, out)
    if not date:
        msg = "OSM land date not found in Last-Modified header"
        raise ValueError(msg)
    return date


def _wp(out: Path) -> str:
    # The outer zip also ships a Deflate64 hash .txt that zipfile can't read.
    _zip(LAND_WP_URL, out, only="*WorldPolygon*.zip")
    inner = next(out.rglob("WorldPolygon*.zip"))
    with ZipFile(inner) as z:
        z.extractall(out)
    inner.unlink()
    gpkg = next(out.rglob("WorldPolygons*.gpkg"))
    match = re.search(r"_(\d{1,2}[A-Za-z]{3}\d{4})$", gpkg.parent.name)
    if match is None:
        msg = f"World Polygons date not found in folder name: {gpkg.parent.name}"
        raise ValueError(msg)
    return datetime.strptime(match[1], "%d%b%Y").replace(tzinfo=UTC).date().isoformat()


@_retry
def _lsib_date() -> str:
    with _client() as client:
        r = client.get(LSIB_META_URL, headers={"Accept": "application/xml"})
        r.raise_for_status()
    el = ET.fromstring(r.text).find(  # noqa: S314
        ".//gmd:CI_Citation/gmd:date/gmd:CI_Date/gmd:date/gco:Date", LSIB_NS
    )
    if el is None or el.text is None:
        msg = "LSIB date not found in metadata response"
        raise ValueError(msg)
    return el.text


def _lsib(out: Path) -> str:
    date = _lsib_date()
    _stream(LSIB_URL, out / "LSIB.gpkg")
    return date


def _ref(out: Path) -> str:
    _stream(UNTERM_URL, out / "unterm.xlsx")
    _stream(M49_URL, out / "m49.html")
    return _today()


def _fieldmaps(out: Path) -> str:
    dates = []
    for land, license_ in FIELDMAPS_LICENSE.items():
        for geom in ("polygons", "lines"):
            url = FIELDMAPS_URL.format(license=license_, geom=geom)
            dates.append(_stream(url, out / f"{land}_{geom}.parquet") or _today())
    return max(dates)


def _fetch(source: str, fn: Callable[[Path], str]) -> None:
    out = download_dir / source
    rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    (out / ".date").write_text(fn(out))
    logger.info("%s: downloaded", source)


def main() -> None:
    """Download all sources in parallel."""
    jobs = {
        "gaul": _gaul,
        "lsib": _lsib,
        "osm": _osm,
        "wp": _wp,
        "ref": _ref,
        "fieldmaps": _fieldmaps,
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [pool.submit(_fetch, s, fn) for s, fn in jobs.items()]
    for f in futures:
        f.result()
