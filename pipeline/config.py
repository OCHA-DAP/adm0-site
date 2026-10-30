"""Pipeline-wide constants and command-line options."""

from argparse import ArgumentParser
from logging import INFO, basicConfig
from os import getenv
from pathlib import Path

basicConfig(
    level=INFO,
    format="%(asctime)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

STEPS = ("download", "prepare", "attributes", "tiles")
OPTIONAL_STEPS = ("fieldmaps", "register")

parser = ArgumentParser(description="Build the ADM0 differences register.")
parser.add_argument("--step", default=getenv("STEP"), choices=STEPS + OPTIONAL_STEPS)
args, _ = parser.parse_known_args()
steps = [args.step] if args.step else list(STEPS)

GAUL_URL = (
    "https://storage.googleapis.com/fao-maps-catalog-data/boundaries/GAUL_2025_L1.zip"
)
LAND_OSM_URL = (
    "https://osmdata.openstreetmap.de/download/land-polygons-complete-4326.zip"
)
LAND_WP_URL = "https://data.geodata.state.gov/WorldPolygons.zip"
LSIB_URL = "https://data.geodata.state.gov/LSIB.gpkg"
LSIB_META_URL = "https://geodata.state.gov/geonetwork/srv/api/records/3bdb81a0-c1b9-439a-a0b1-85dac30c59b2"
LSIB_NS = {
    "gco": "http://www.isotc211.org/2005/gco",
    "gmd": "http://www.isotc211.org/2005/gmd",
}
UNTERM_URL = "https://conferences.unite.un.org/untermapi/api/term/downloadCountries"
FIELDMAPS_URL = "https://data.source.coop/fieldmaps/international/{license}/humanitarian/adm0-{geom}/adm0_{geom}.parquet"
FIELDMAPS_LICENSE = {"wp": "cc0", "osm": "odbl"}
M49_URL = "https://unstats.un.org/unsd/methodology/m49/overview/"

CRS = "OGC:CRS84"
PARQUET_OPTS = "(FORMAT PARQUET, COMPRESSION ZSTD, GEOPARQUET_VERSION V2)"

root = Path(__file__).parent.parent
tmp_dir = root / "tmp"
download_dir = tmp_dir / "download"
prepare_dir = tmp_dir / "prepare"
fieldmaps_dir = tmp_dir / "fieldmaps"
register_dir = root / "outputs/register"
tiles_dir = root / "outputs/tiles"
input_dir = root / "inputs"
