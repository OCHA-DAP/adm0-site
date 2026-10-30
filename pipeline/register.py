"""Build the GAUL-to-source overlap crosswalk under ``outputs/register/``."""

from logging import getLogger

from duckdb import DuckDBPyConnection, connect

from .config import fieldmaps_dir, prepare_dir, register_dir, tmp_dir

logger = getLogger(__name__)

# Each comparison source: (id expression, code, sovereign, name, status, region).
SOURCES = {
    "ungeodata": {
        "path": prepare_dir / "ungeodata_polygons.parquet",
        "id": "iso3cd || coalesce('-' || romnam, '')",
        "code": "iso3cd",
        "sovereign": "isoclr",
        "name": "romnam",
        "status": "stscod::VARCHAR",
        "region": "contcd",
    },
    **{
        f"fieldmaps_{land}": {
            "path": fieldmaps_dir / f"{land}_polygons.parquet",
            "id": "id",
            "code": "iso_3",
            "sovereign": "iso_3_grp",
            "name": "adm0_name",
            "status": "status_nm",
            "region": "region1_nm",
        }
        for land in ("wp", "osm")
    },
}


def _entities(conn: DuckDBPyConnection) -> None:
    """Load every source's entities into one long table with common columns."""
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE entities AS
        SELECT 'gaul' AS source, gaul_id AS id, iso3_code AS code,
               map_code AS sovereign, gaul0_name AS name, NULL::VARCHAR AS status,
               continent AS region, geometry AS geom
        FROM read_parquet('{prepare_dir / "gaul_l0.parquet"}')
    """)
    for source, s in SOURCES.items():
        if not s["path"].exists():
            logger.warning("%s: %s missing, skipping", source, s["path"].name)
            continue
        conn.execute(f"""--sql
            INSERT INTO entities
            SELECT '{source}', {s["id"]}, {s["code"]}, {s["sovereign"]}, {s["name"]},
                   {s["status"]}, {s["region"]}, geometry
            FROM read_parquet('{s["path"]}')
        """)
    conn.execute("""--sql
        CREATE OR REPLACE TABLE entities AS
        SELECT * EXCLUDE geom, ST_Area(geom) AS area,
               ST_XMin(geom) AS xmin, ST_YMin(geom) AS ymin,
               ST_XMax(geom) AS xmax, ST_YMax(geom) AS ymax, geom
        FROM entities
    """)


def _crosswalk(conn: DuckDBPyConnection) -> None:
    """Overlap each GAUL entity with other sources' entities, one pair per call."""
    conn.execute("""--sql
        CREATE OR REPLACE TABLE crosswalk (
            gaul_id VARCHAR, source VARCHAR, other_id VARCHAR, overlap DOUBLE
        )
    """)
    pairs = conn.execute("""--sql
        SELECT g.id, o.source, o.id,
               greatest(g.xmin, o.xmin), greatest(g.ymin, o.ymin),
               least(g.xmax, o.xmax), least(g.ymax, o.ymax)
        FROM entities g JOIN entities o
          ON g.source = 'gaul' AND o.source != 'gaul'
         AND g.xmin <= o.xmax AND g.xmax >= o.xmin
         AND g.ymin <= o.ymax AND g.ymax >= o.ymin
        ORDER BY g.id
    """).fetchall()
    logger.info("crosswalk: %d candidate pairs", len(pairs))
    for i, (gid, source, oid, *box) in enumerate(pairs, 1):
        if i % 100 == 0:
            logger.info("crosswalk: %d/%d pairs", i, len(pairs))
        # Clipping both sides to the shared bbox first is exact and much cheaper.
        conn.execute(
            """--sql
            INSERT INTO crosswalk
            SELECT $1, $2, $3, ST_Area(ST_Intersection(
                ST_Intersection(g.geom, ST_MakeEnvelope($4, $5, $6, $7)),
                ST_Intersection(o.geom, ST_MakeEnvelope($4, $5, $6, $7))
            ))
            FROM entities g, entities o
            WHERE g.source = 'gaul' AND g.id = $1 AND o.source = $2 AND o.id = $3
            """,
            [gid, source, oid, *box],
        )
    conn.execute("""--sql
        CREATE OR REPLACE TABLE crosswalk AS
        SELECT c.*, c.overlap / g.area AS gaul_share, c.overlap / o.area AS other_share
        FROM crosswalk c
        JOIN entities g ON g.source = 'gaul' AND g.id = c.gaul_id
        JOIN entities o ON o.source = c.source AND o.id = c.other_id
        WHERE c.overlap > 0
    """)


def _write(conn: DuckDBPyConnection, table: str) -> None:
    out = register_dir / f"{table}.parquet"
    conn.execute(f"COPY \"{table}\" TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    n = conn.execute(f'SELECT count(*) FROM "{table}"').fetchall()[0][0]
    logger.info("%s: %d rows", table, n)


def main() -> None:
    """Build and write the crosswalk."""
    register_dir.mkdir(parents=True, exist_ok=True)
    db = tmp_dir / "register.duckdb"
    db.unlink(missing_ok=True)
    conn = connect(db)
    conn.execute("LOAD spatial")
    _entities(conn)
    _crosswalk(conn)
    _write(conn, "crosswalk")
    conn.close()
