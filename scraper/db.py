"""Almacenamiento en SQLite de los anuncios recogidos."""
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    display_model TEXT NOT NULL,
    make TEXT,
    model TEXT,
    year INTEGER,
    price REAL,
    km INTEGER,
    fuel TEXT,
    province TEXT,
    city TEXT,
    seller_type TEXT,
    has_warranty INTEGER,
    hp INTEGER,
    description TEXT,
    title TEXT,
    publish_date TEXT,
    url TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_listings_model ON listings (display_model);
CREATE INDEX IF NOT EXISTS idx_listings_active ON listings (is_active);
CREATE INDEX IF NOT EXISTS idx_listings_publish_date ON listings (publish_date);

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    models_scanned INTEGER,
    listings_seen INTEGER,
    new_listings INTEGER,
    errors INTEGER
);
"""


# Columnas añadidas después de la creación inicial de la tabla: CREATE TABLE
# IF NOT EXISTS no las añade a una BD ya existente, hace falta migrarlas.
_MIGRATIONS = [
    ("listings", "hp", "INTEGER"),
]


def _migrate(conn: sqlite3.Connection):
    for table, column, coltype in _MIGRATIONS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


@contextmanager
def connect(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_listing(conn: sqlite3.Connection, listing: dict, now_iso: str) -> bool:
    """Inserta o actualiza un anuncio. Devuelve True si es nuevo."""
    cur = conn.execute(
        "SELECT source_id FROM listings WHERE source = ? AND source_id = ?",
        (listing["source"], listing["source_id"]),
    )
    exists = cur.fetchone() is not None

    if exists:
        conn.execute(
            """
            UPDATE listings SET
                price = ?, km = ?, hp = ?, is_active = 1, last_seen_at = ?,
                description = ?, title = ?
            WHERE source = ? AND source_id = ?
            """,
            (
                listing["price"], listing["km"], listing.get("hp"), now_iso,
                listing.get("description"), listing.get("title"),
                listing["source"], listing["source_id"],
            ),
        )
        return False

    conn.execute(
        """
        INSERT INTO listings (
            source, source_id, display_model, make, model, year, price, km,
            fuel, province, city, seller_type, has_warranty, hp, description,
            title, publish_date, url, first_seen_at, last_seen_at, is_active
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
        """,
        (
            listing["source"], listing["source_id"], listing["display_model"],
            listing.get("make"), listing.get("model"), listing.get("year"),
            listing.get("price"), listing.get("km"), listing.get("fuel"),
            listing.get("province"), listing.get("city"),
            listing.get("seller_type"), int(bool(listing.get("has_warranty"))),
            listing.get("hp"), listing.get("description"), listing.get("title"),
            listing.get("publish_date"), listing.get("url"),
            now_iso, now_iso,
        ),
    )
    return True


def mark_inactive_not_seen_since(conn: sqlite3.Connection, source: str, display_model: str, seen_ids: set, now_iso: str):
    """Marca como inactivos (ya no publicados) los anuncios de este modelo/fuente
    que no han aparecido en el barrido actual."""
    rows = conn.execute(
        "SELECT source_id FROM listings WHERE source = ? AND display_model = ? AND is_active = 1",
        (source, display_model),
    ).fetchall()
    stale = [r["source_id"] for r in rows if r["source_id"] not in seen_ids]
    if stale:
        conn.executemany(
            "UPDATE listings SET is_active = 0 WHERE source = ? AND source_id = ?",
            [(source, sid) for sid in stale],
        )


def record_scan_run(conn: sqlite3.Connection, started_at: str, finished_at: str,
                     models_scanned: int, listings_seen: int, new_listings: int, errors: int):
    conn.execute(
        """INSERT INTO scan_runs (started_at, finished_at, models_scanned, listings_seen, new_listings, errors)
           VALUES (?,?,?,?,?,?)""",
        (started_at, finished_at, models_scanned, listings_seen, new_listings, errors),
    )


def active_listings_for_model(conn: sqlite3.Connection, display_model: str):
    return conn.execute(
        "SELECT * FROM listings WHERE display_model = ? AND is_active = 1",
        (display_model,),
    ).fetchall()


def all_active_listings(conn: sqlite3.Connection):
    return conn.execute("SELECT * FROM listings WHERE is_active = 1").fetchall()
