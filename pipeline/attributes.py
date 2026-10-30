"""Join every source's ADM0 attributes on ISO3 into ``attributes.json`` for the site."""

from logging import getLogger

from duckdb import connect

from .config import prepare_dir, tiles_dir

logger = getLogger(__name__)

UNGEODATA_STATUS = {
    0: "Antarctica",
    1: "State",
    2: "Occupied Palestinian Territory",
    3: "Non-Self-Governing Territory",
    4: "Territory",
    5: "Special Region or Province",
    99: "Undetermined",
}

# Per source: join code, then output column -> source expression.
SOURCES = {
    "gaul": (
        "gaul_l0",
        "ISO3_CODE",
        {
            "name": "GAUL0_NAME",
            "mapcode": "MAP_CODE",
            "region": "CONTINENT",
        },
    ),
    "ungeodata": (
        "ungeodata_polygons",
        "iso3cd",
        {
            "name": "romnam",
            "sovereign": "isoclr",
            "status": "status_label",
            "region": "contcd",
        },
    ),
    "fieldmaps": (
        "fieldmaps_wp_polygons",
        "iso_3",
        {
            "name": "adm0_name",
            "sovereign": "iso_3_grp",
            "status": "status_nm",
            "region": "region1_nm",
        },
    ),
    "wp": (
        "wp_polygons",
        "GENC_3",
        {"name": "WP_Name", "status": "US_Recog"},
    ),
    "unterm": (
        "ref",
        "iso3",
        {"name": "name_en_short", "status": "un_status"},
    ),
    "m49": ("ref", "iso3", {"name": "name_m49", "region": "region"}),
}


def main() -> None:
    """Write one row per ISO3 code with each source's values side by side."""
    conn = connect()
    conn.execute("LOAD spatial")
    status = ", ".join(f"({k}, '{v}')" for k, v in UNGEODATA_STATUS.items())
    conn.execute(f"""--sql
        CREATE TABLE ungeodata_status (code SMALLINT, label VARCHAR);
        INSERT INTO ungeodata_status VALUES {status};
    """)
    selects = []
    for source, (table, code, cols) in SOURCES.items():
        frm = f"read_parquet('{prepare_dir / table}.parquet')"
        if source == "ungeodata":
            frm = f"""(SELECT t.*, s.label AS status_label FROM
                read_parquet('{prepare_dir / table}.parquet') t
                LEFT JOIN ungeodata_status s ON s.code = t.stscod)"""
        aggs = ", ".join(
            f"string_agg(DISTINCT trim({expr}::VARCHAR), ' | ' ORDER BY "
            f"trim({expr}::VARCHAR)) AS {col}_{source}"
            for col, expr in cols.items()
        )
        selects.append(
            (
                source,
                f"""(SELECT upper({code}) AS iso3, count(*) AS count_{source}, {aggs}
                FROM {frm} WHERE {code} IS NOT NULL GROUP BY 1)""",
            )
        )
    query = f"SELECT * FROM {selects[0][1]} AS {selects[0][0]}"
    for source, sub in selects[1:]:
        query += f" FULL JOIN {sub} AS {source} USING (iso3)"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    out = tiles_dir / "attributes.json"
    conn.execute(f"""--sql
        COPY ({query} ORDER BY iso3) TO '{out}' (FORMAT JSON, ARRAY true)
    """)
    n = conn.execute(f"SELECT count(*) FROM read_json('{out}')").fetchall()[0][0]
    logger.info("attributes: %d rows", n)
