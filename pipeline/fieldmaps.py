"""Build the fieldmaps LSIB humanitarian ADM0 (intl view) for each land source."""

from logging import getLogger

from duckdb import DuckDBPyConnection, connect

from .config import CRS, PARQUET_OPTS, fieldmaps_dir, input_dir, prepare_dir, tmp_dir

logger = getLogger(__name__)

LANDS = ("osm", "wp")
GEOM_PRECISION = 0.000000001
LINE_KEYS = ["COUNTRY1", "COUNTRY2", "RANK", "LABEL"]
# Known erroneous LSIB segments, as (CC1, CC2, RANK).
LSIB_DROP = [("SS", "SD", 1), ("KE", "SS", 2), ("SS", "SS", 2), ("KE", "KE", 2)]


def _attributes(conn: DuckDBPyConnection) -> None:
    """Load the hand-curated point and line attributes."""
    src = input_dir / "fieldmaps"
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE attrs_points AS
        SELECT * REPLACE (
            coalesce(iso_3_grp, iso_3) AS iso_3_grp,
            coalesce(region1_cd, status_cd) AS region1_cd,
            coalesce(region1_nm, status_nm) AS region1_nm,
            coalesce(region2_cd, region1_cd, status_cd) AS region2_cd,
            coalesce(region2_nm, region1_nm, status_nm) AS region2_nm,
            coalesce(region3_cd, region2_cd, region1_cd, status_cd) AS region3_cd,
            coalesce(region3_nm, region2_nm, region1_nm, status_nm) AS region3_nm
        )
        FROM read_csv('{src / "adm0_points.csv"}', all_varchar=true,
                      nullstr=['', '#N/A'])
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE attrs_lines AS
        SELECT * EXCLUDE (rank_all)
        FROM read_csv('{src / "adm0_lines.csv"}', all_varchar=true,
                      nullstr=['', '#N/A'])
    """)


def _inputs(conn: DuckDBPyConnection, land: str) -> None:
    """Load land, template lines plus LSIB, and seed points."""
    src = input_dir / "fieldmaps"
    if land == "osm":
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE land_00 AS
            SELECT fid, geometry AS geom
            FROM read_parquet('{prepare_dir / "osm_land.parquet"}')
        """)
    else:
        # Caspian Sea is the only World Polygons feature without a WP_Name.
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE land_00 AS
            SELECT row_number() OVER () AS fid, geom FROM (
                SELECT UNNEST(ST_Dump(geometry)).geom AS geom
                FROM read_parquet('{prepare_dir / "wp_polygons.parquet"}')
                WHERE WP_Name IS NOT NULL
            )
        """)
    drop = " OR ".join(
        f"(CC1 = '{a}' AND CC2 = '{b}' AND RANK::INTEGER = {r})"
        for a, b, r in LSIB_DROP
    )
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE lines_00 AS
        SELECT CC1, COUNTRY1, CC2, COUNTRY2, RANK::BIGINT AS RANK, LABEL, STATUS,
               NOTES, ST_SetCRS(geom, '{CRS}') AS geom
        FROM read_parquet('{src / "adm0_lines.parquet"}')
        UNION ALL
        SELECT CC1, COUNTRY1, CC2, COUNTRY2, RANK::BIGINT, LABEL, STATUS, NOTES,
               geometry
        FROM read_parquet('{prepare_dir / "lsib_lines.parquet"}')
        WHERE NOT ({drop})
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE points_00 AS
        SELECT id, ST_SetCRS(geom, '{CRS}') AS geom
        FROM read_parquet('{src / "adm0_points.parquet"}')
    """)


def _polygonize(conn: DuckDBPyConnection) -> None:
    """Polygonize the union of lines and seed each face from its point."""
    conn.execute("""--sql
        CREATE OR REPLACE TABLE lines_01 AS
        SELECT ST_Multi(ST_Union_Agg(geom)) AS geom FROM lines_00
    """)
    conn.execute("""--sql
        CREATE OR REPLACE TABLE voronoi_00 AS
        WITH faces AS (
            SELECT UNNEST(ST_Dump(ST_Polygonize(list(geom)))).geom AS geom
            FROM lines_01
        )
        SELECT p.id, f.geom
        FROM faces f JOIN points_00 p ON ST_DWithin(p.geom, f.geom, 0)
    """)
    faces, points = conn.execute("""--sql
        SELECT (SELECT count(*) FROM voronoi_00), (SELECT count(*) FROM points_00)
    """).fetchall()[0]
    invalid = conn.execute(
        "SELECT ST_CoverageInvalidEdges_Agg(geom) IS NOT NULL FROM voronoi_00"
    ).fetchall()[0][0]
    if faces != points or invalid:
        msg = f"polygonize: {faces} faces for {points} points, invalid={invalid}"
        raise RuntimeError(msg)


def _continents(conn: DuckDBPyConnection) -> None:
    """Keep the land masses crossed by a boundary line."""
    wkb = conn.execute("SELECT ST_AsWKB(geom) FROM lines_01").fetchall()[0][0]
    conn.execute(
        """--sql
        CREATE OR REPLACE TABLE land_01 AS
        SELECT * FROM land_00 WHERE ST_Intersects(geom, ST_GeomFromWKB($1))
        """,
        [wkb],
    )


def _intersection(conn: DuckDBPyConnection) -> None:
    """Clip voronoi cells to land; whole islands go to the cell holding them."""
    conn.execute("CREATE OR REPLACE TABLE clip (id VARCHAR, geom GEOMETRY)")
    # One land polygon per execute(), passed as WKB, caps GEOS memory.
    for (fid,) in conn.execute("SELECT fid FROM land_01").fetchall():
        env = conn.execute(
            "SELECT ST_AsWKB(ST_Envelope(geom)) FROM land_01 WHERE fid = $1", [fid]
        ).fetchall()[0][0]
        cells = conn.execute(
            "SELECT id, ST_AsWKB(geom) FROM voronoi_00 "
            "WHERE ST_Intersects(geom, ST_GeomFromWKB($1))",
            [env],
        ).fetchall()
        for vid, cell in cells:
            conn.execute(
                """--sql
                INSERT INTO clip
                SELECT $1, ST_CollectionExtract(ST_Intersection(
                    (SELECT geom FROM land_01 WHERE fid = $2), ST_GeomFromWKB($3)
                ), 3)
                """,
                [vid, fid, cell],
            )
    conn.execute("""--sql
        CREATE OR REPLACE TABLE land_pts AS
        SELECT fid, ST_PointOnSurface(geom) AS pt FROM land_00
        WHERE fid NOT IN (SELECT fid FROM land_01)
    """)
    for vid, cell in conn.execute(
        "SELECT id, ST_AsWKB(geom) FROM voronoi_00"
    ).fetchall():
        conn.execute(
            """--sql
            INSERT INTO clip
            SELECT $1, l.geom FROM land_pts p JOIN land_00 l USING (fid)
            WHERE ST_Contains(ST_GeomFromWKB($2), p.pt)
            """,
            [vid, cell],
        )
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE polygons_00 AS
        SELECT id, ST_Multi(ST_ReducePrecision(ST_Union_Agg(geom), {GEOM_PRECISION}))
            AS geom
        FROM clip WHERE NOT ST_IsEmpty(geom) GROUP BY id
    """)


def _dissolve(conn: DuckDBPyConnection, src: str, out: str) -> None:
    """Dissolve cells onto their intl-view ``a_intl`` unit and join attributes."""
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE "{out}" AS
        WITH dissolved AS (
            SELECT coalesce(a.a_intl, s.id) AS id,
                   ST_Multi(ST_Union_Agg(s.geom)) AS geom
            FROM "{src}" s JOIN attrs_points a USING (id)
            GROUP BY ALL
        )
        SELECT a.* EXCLUDE (a_intl, p_intl, a_all, p_all), d.geom
        FROM dissolved d LEFT JOIN attrs_points a USING (id)
    """)


def _lines(conn: DuckDBPyConnection) -> None:
    """Clip boundary lines to the crossed land masses, intl ranks applied."""
    keys = ", ".join(f'"{k}"' for k in LINE_KEYS)
    conn.execute(
        f"CREATE OR REPLACE TABLE lines_clip AS "
        f"SELECT {keys}, geom FROM lines_00 LIMIT 0"
    )
    for (fid,) in conn.execute("SELECT fid FROM land_01").fetchall():
        land, env = conn.execute(
            "SELECT ST_AsWKB(geom), ST_AsWKB(ST_Envelope(geom)) FROM land_01 "
            "WHERE fid = $1",
            [fid],
        ).fetchall()[0]
        for *vals, line in conn.execute(
            f"SELECT {keys}, ST_AsWKB(geom) FROM lines_00 "
            "WHERE ST_Intersects(ST_Envelope(geom), ST_GeomFromWKB($1))",
            [env],
        ).fetchall():
            conn.execute(
                """--sql
                INSERT INTO lines_clip SELECT $1, $2, $3, $4, ST_CollectionExtract(
                    ST_Intersection(ST_GeomFromWKB($5), ST_GeomFromWKB($6)), 2)
                """,
                [*vals, line, land],
            )
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE lines_02 AS
        WITH dissolved AS (
            SELECT {keys}, ST_Multi(ST_ReducePrecision(
                ST_Union_Agg(geom), {GEOM_PRECISION})) AS geom
            FROM lines_clip WHERE NOT ST_IsEmpty(geom) GROUP BY ALL
        )
        SELECT a.adm_id, a.cc1, d."COUNTRY1" AS country1, a.cc2,
               d."COUNTRY2" AS country2,
               coalesce(a.rank_intl::BIGINT, d."RANK") AS rank,
               d."LABEL" AS label, a.status, a.notes, d.geom
        FROM dissolved d LEFT JOIN attrs_lines a
          ON d."COUNTRY1" = a.country1 AND d."COUNTRY2" = a.country2
         AND d."RANK" = a.rank::BIGINT AND d."LABEL" IS NOT DISTINCT FROM a.label
        WHERE coalesce(a.rank_intl::BIGINT, d."RANK") > 0
    """)


def _write(conn: DuckDBPyConnection, land: str) -> None:
    for table, name in (
        ("polygons_01", "polygons"),
        ("voronoi_01", "voronoi"),
        ("lines_02", "lines"),
    ):
        out = fieldmaps_dir / f"{land}_{name}.parquet"
        conn.execute(f"""--sql
            COPY (SELECT * EXCLUDE geom, ST_SetCRS(geom, '{CRS}') AS geometry
                  FROM "{table}")
            TO '{out}' {PARQUET_OPTS}
        """)
        n = conn.execute(f'SELECT count(*) FROM "{table}"').fetchall()[0][0]
        logger.info("%s_%s: %d rows", land, name, n)


def _validate(conn: DuckDBPyConnection, land: str) -> None:
    issues = []
    for table, key in (("polygons_01", "id"), ("lines_02", None)):
        bad = conn.execute(
            f'SELECT count(*) FROM "{table}" WHERE geom IS NULL OR NOT ST_IsValid(geom)'
        ).fetchall()[0][0]
        if bad:
            issues.append(f"{table}: {bad} null/invalid geometries")
        if key:
            dup = conn.execute(
                f'SELECT count(*) - count(DISTINCT "{key}") FROM "{table}"'
            ).fetchall()[0][0]
            if dup:
                issues.append(f"{table}: {dup} duplicate {key}")
    if conn.execute(
        "SELECT ST_CoverageInvalidEdges_Agg(geom) IS NOT NULL FROM polygons_01"
    ).fetchall()[0][0]:
        issues.append("polygons_01: overlaps or gaps between units")
    if issues:
        msg = f"{land}: {'; '.join(issues)}"
        raise RuntimeError(msg)


def main() -> None:
    """Build polygons, voronoi cells and lines for each land source."""
    fieldmaps_dir.mkdir(parents=True, exist_ok=True)
    for land in LANDS:
        db = tmp_dir / f"fieldmaps_{land}.duckdb"
        db.unlink(missing_ok=True)
        conn = connect(db)
        conn.execute("LOAD spatial")
        _attributes(conn)
        _inputs(conn, land)
        _polygonize(conn)
        _continents(conn)
        _intersection(conn)
        _dissolve(conn, "polygons_00", "polygons_01")
        _dissolve(conn, "voronoi_00", "voronoi_01")
        _lines(conn)
        _validate(conn, land)
        _write(conn, land)
        conn.close()
        logger.info("fieldmaps %s built", land)
