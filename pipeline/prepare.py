"""Normalize downloaded sources into GeoParquet under ``tmp/prepare/``."""

import html
import re
from logging import getLogger

from duckdb import DuckDBPyConnection, connect

from .config import CRS, PARQUET_OPTS, download_dir, input_dir, prepare_dir

logger = getLogger(__name__)

UNTERM_LANGS = ("English", "French", "Spanish", "Russian", "Chinese", "Arabic")
UNTERM_STATUS = {
    0: "Member State",
    1: "Observer State",
    2: "Member of specialized agencies",
}


def _copy(conn: DuckDBPyConnection, query: str, name: str) -> None:
    out = prepare_dir / f"{name}.parquet"
    conn.execute(f"""--sql
        COPY (SELECT * REPLACE (ST_SetCRS(geometry, '{CRS}') AS geometry)
              FROM ({query}))
        TO '{out}' {PARQUET_OPTS}
    """)
    n = conn.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchall()[0][0]
    logger.info("%s: %d rows", name, n)


def gaul(conn: DuckDBPyConnection) -> None:
    """Dissolve GAUL 2025 L1 to one L0 entity per distinct L0 attribute set."""
    path = download_dir / "gaul/gaul_2025_l1.shp"
    conn.execute(f"CREATE TABLE gaul_l1 AS SELECT * FROM ST_Read('{path}')")
    attrs = "GAUL0_CODE, ISO3_CODE, MAP_CODE, GAUL0_NAME, CONTINENT"
    for code, names in conn.execute(f"""--sql
        SELECT GAUL0_CODE, list(DISTINCT GAUL0_NAME) FROM gaul_l1
        GROUP BY GAUL0_CODE HAVING count(DISTINCT ({attrs})) > 1
    """).fetchall():
        logger.warning("GAUL0_CODE %d splits into %s", code, names)
    # gaul_id stays the L0 code unless that code carries several attribute sets.
    _copy(
        conn,
        f"""--sql
        SELECT CASE WHEN count(*) OVER (PARTITION BY GAUL0_CODE) = 1
                    THEN GAUL0_CODE::VARCHAR
                    ELSE GAUL0_CODE || '-' || ISO3_CODE || '-' || row_number()
                         OVER (PARTITION BY GAUL0_CODE ORDER BY GAUL0_NAME)
               END AS gaul_id,
               * EXCLUDE geometry, geometry
        FROM (
            SELECT {attrs}, count(*) AS gaul1_count,
                   ST_Multi(ST_CollectionExtract(
                       ST_MakeValid(ST_Union_Agg(geom)), 3)) AS geometry
            FROM gaul_l1 GROUP BY ALL
        )
        ORDER BY GAUL0_CODE, gaul_id
        """,
        "gaul_l0",
    )


def lsib(conn: DuckDBPyConnection) -> None:
    """Copy LSIB boundary lines."""
    path = download_dir / "lsib/LSIB.gpkg"
    layer = conn.execute(f"""--sql
        SELECT name FROM (
            SELECT UNNEST(layers).name AS name FROM ST_Read_Meta('{path}')
        )
        WHERE starts_with(name, 'Department of State LSIB')
    """).fetchall()[0][0]
    _copy(
        conn,
        f"""--sql
        SELECT * EXCLUDE (fid, geom), geom AS geometry
        FROM ST_Read('{path}', layer='{layer}')
        """,
        "lsib_lines",
    )


def wp(conn: DuckDBPyConnection) -> None:
    """Copy State Department World Polygons (full resolution layer)."""
    path = next((download_dir / "wp").rglob("WorldPolygons*.gpkg"))
    layer = conn.execute(f"""--sql
        SELECT name FROM (
            SELECT UNNEST(layers).name AS name FROM ST_Read_Meta('{path}')
        )
        WHERE regexp_full_match(name, 'DoS_WP_\\d+_\\d+')
    """).fetchall()[0][0]
    _copy(
        conn,
        f"""--sql
        SELECT * EXCLUDE (fid, geom), geom AS geometry
        FROM ST_Read('{path}', layer='{layer}')
        """,
        "wp_polygons",
    )


def osm(conn: DuckDBPyConnection) -> None:
    """Copy OSM land polygons."""
    path = next((download_dir / "osm").rglob("land_polygons.shp"))
    _copy(
        conn,
        f"SELECT row_number() OVER () AS fid, geom AS geometry FROM ST_Read('{path}')",
        "osm_land",
    )


def _key(name: str) -> str:
    """Match UNTERM names ("Sudan (the)", "Côte d'Ivoire") to M49 names."""
    name = re.sub(r"\s*\*+$", "", name.strip())
    name = re.sub(r"\s*\((the|The)\)$", "", name)
    return name.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'").strip().lower()


def _m49_rows() -> list[list[str]]:
    page = (download_dir / "ref/m49.html").read_text(encoding="utf-8")
    start = page.find('id="ENG_Overview"')
    table = page[start : page.find("</table>", start)]
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL):
        cells = [
            html.unescape(re.sub("<[^>]+>", "", td)).strip()
            for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        ]
        if len(cells) >= 16 and cells[9].isdigit():  # noqa: PLR2004
            rows.append(cells)
    return rows


def ref(conn: DuckDBPyConnection) -> None:
    """Join UNTERM names to M49 codes and regions, one row per M49 area."""
    conn.execute("INSTALL excel; LOAD excel")
    unterm = conn.execute(f"""--sql
        SELECT * FROM read_xlsx('{download_dir / "ref/unterm.xlsx"}', all_varchar=true)
        WHERE "English short" IS NOT NULL
    """).fetchall()
    cols = [d[0].strip() for d in conn.description]
    by_key = {
        _key(r[cols.index("English short")]): dict(zip(cols, r, strict=True))
        for r in unterm
    }
    out, used = [], set()
    for m in _m49_rows():
        u = by_key.get(_key(m[8]))
        if u:
            used.add(_key(m[8]))
        short = u["English short"] if u else ""
        stars = len(short.strip()) - len(short.strip().rstrip("*"))
        clean = {
            k: re.sub(r"\s*\*+$", "", (v or "").strip()) for k, v in (u or {}).items()
        }
        out.append(
            {
                "iso3": m[11],
                "iso2": m[10],
                "m49": m[9],
                "name_m49": m[8],
                "un_status": UNTERM_STATUS[stars] if u else "Other area",
                **{
                    f"name_{lang[:2].lower()}_{form}": clean.get(f"{lang} {form}", "")
                    for lang in UNTERM_LANGS
                    for form in ("short", "formal")
                },
                "region": m[3],
                "subregion": m[5],
                "intermediate_region": m[7],
            }
        )
    missing = sorted(set(by_key) - used)
    if missing:
        msg = f"UNTERM names with no M49 match: {missing}"
        raise ValueError(msg)
    conn.execute(
        "CREATE TABLE ref (" + ", ".join(f'"{c}" VARCHAR' for c in out[0]) + ")"
    )
    conn.executemany(
        f"INSERT INTO ref VALUES ({', '.join('?' * len(out[0]))})",
        [list(r.values()) for r in out],
    )
    out_path = prepare_dir / "ref.parquet"
    conn.execute(
        f"COPY (SELECT * FROM ref ORDER BY iso3) TO '{out_path}' (FORMAT PARQUET)"
    )
    logger.info("ref: %d rows", len(out))


def ungeodata(conn: DuckDBPyConnection) -> None:
    """Copy UN Geodata 1M country polygons and boundary lines from ``inputs/``."""
    for layer, name in (
        ("bnda_cty", "ungeodata_polygons"),
        ("bndl", "ungeodata_lines"),
    ):
        path = input_dir / f"ungeodata/{layer}.parquet"
        if not path.exists():
            msg = f"{path} missing; import it from the UN Geodata 1M FileGDB"
            raise FileNotFoundError(msg)
        _copy(
            conn,
            f"SELECT * EXCLUDE globalid FROM read_parquet('{path}')",
            name,
        )


def fieldmaps(conn: DuckDBPyConnection) -> None:
    """Copy the published fieldmaps humanitarian polygons and lines."""
    for path in sorted((download_dir / "fieldmaps").glob("*.parquet")):
        _copy(conn, f"SELECT * FROM read_parquet('{path}')", f"fieldmaps_{path.stem}")


def main() -> None:
    """Prepare every downloaded source."""
    prepare_dir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    conn.execute("LOAD spatial")
    for fn in (ref, gaul, lsib, wp, osm, ungeodata, fieldmaps):
        fn(conn)
