from __future__ import annotations

import sqlite3
import time

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    key        TEXT PRIMARY KEY,
    watch      TEXT NOT NULL,
    source     TEXT NOT NULL,
    title      TEXT NOT NULL,
    url        TEXT NOT NULL,
    currency   TEXT NOT NULL,
    gtin       TEXT NOT NULL DEFAULT '',
    first_seen REAL NOT NULL,
    last_seen  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS prices (
    key   TEXT NOT NULL,
    watch TEXT NOT NULL,
    total REAL NOT NULL,
    ts    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS prices_watch_ts ON prices(watch, ts);
CREATE INDEX IF NOT EXISTS prices_key_ts ON prices(key, ts);
CREATE TABLE IF NOT EXISTS alerts (
    key   TEXT NOT NULL,
    total REAL NOT NULL,
    ts    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS alerts_key ON alerts(key);
CREATE INDEX IF NOT EXISTS listings_gtin ON listings(gtin) WHERE gtin != '';
CREATE TABLE IF NOT EXISTS pages (
    url          TEXT PRIMARY KEY,
    domain       TEXT NOT NULL,
    lastmod      TEXT NOT NULL DEFAULT '',
    changed      INTEGER NOT NULL DEFAULT 1,
    is_product   INTEGER,
    last_checked REAL
);
CREATE INDEX IF NOT EXISTS pages_domain ON pages(domain, is_product, last_checked);
CREATE TABLE IF NOT EXISTS sites (
    domain        TEXT PRIMARY KEY,
    mode          TEXT NOT NULL DEFAULT '',
    cursor        INTEGER NOT NULL DEFAULT 1,
    sitemap_at    REAL NOT NULL DEFAULT 0,
    failures      INTEGER NOT NULL DEFAULT 0,
    blocked_until REAL NOT NULL DEFAULT 0,
    last_error    TEXT NOT NULL DEFAULT '',
    last_ok       REAL NOT NULL DEFAULT 0,
    products_seen INTEGER NOT NULL DEFAULT 0
);
"""


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def previous_price(self, key: str) -> float | None:
        """Dernier prix connu de cette annonce, avant cette passe."""
        row = self.db.execute(
            "SELECT total FROM prices WHERE key = ? ORDER BY ts DESC LIMIT 1", (key,)
        ).fetchone()
        return row[0] if row else None

    def record(self, watch: str, listing: Listing, now: float | None = None) -> None:
        now = now or time.time()
        self.db.execute(
            """INSERT INTO listings(key, watch, source, title, url, currency, gtin,
                                   first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET last_seen = excluded.last_seen,
                                              title = excluded.title,
                                              gtin = excluded.gtin""",
            (listing.key, watch, listing.source, listing.title, listing.url,
             listing.currency, listing.gtin, now, now),
        )
        # On n'ajoute un point de prix que s'il a changé : l'historique reste léger
        # et une annonce revue 100 fois ne pèse pas 100 fois dans le marché.
        if self.previous_price(listing.key) != listing.total:
            self.db.execute(
                "INSERT INTO prices(key, watch, total, ts) VALUES (?, ?, ?, ?)",
                (listing.key, watch, listing.total, now),
            )

    def market_prices(self, watch: str, since: float) -> list[float]:
        """Dernier prix de chaque annonce de cette surveillance vue depuis `since`."""
        rows = self.db.execute(
            """SELECT p.total FROM prices p
               JOIN (SELECT key, MAX(ts) AS ts FROM prices
                     WHERE watch = ? AND ts >= ? GROUP BY key) last
                 ON p.key = last.key AND p.ts = last.ts""",
            (watch, since),
        ).fetchall()
        return [r[0] for r in rows]

    def already_alerted(self, key: str, total: float) -> bool:
        """Déjà signalée à ce prix (ou plus bas) : on ne renvoie pas l'alerte."""
        row = self.db.execute("SELECT MIN(total) FROM alerts WHERE key = ?", (key,)).fetchone()
        return row[0] is not None and total >= row[0]

    def mark_alerted(self, key: str, total: float) -> None:
        self.db.execute(
            "INSERT INTO alerts(key, total, ts) VALUES (?, ?, ?)", (key, total, time.time())
        )

    def gtin_prices(self, gtin: str, exclude_source: str, since: float) -> dict[str, float]:
        """Prix actuel du même produit (code-barres) sur les AUTRES sites : {source: prix}."""
        rows = self.db.execute(
            """SELECT l.source, MIN(p.total) FROM listings l
               JOIN prices p ON p.key = l.key
                AND p.ts = (SELECT MAX(ts) FROM prices WHERE key = l.key)
               WHERE l.gtin = ? AND l.source != ? AND l.last_seen >= ?
               GROUP BY l.source""",
            (gtin, exclude_source, since),
        ).fetchall()
        return dict(rows)

    # -- mode catalogue -------------------------------------------------------
    def site_row(self, domain: str) -> dict:
        self.db.execute("INSERT OR IGNORE INTO sites(domain) VALUES (?)", (domain,))
        cur = self.db.execute("SELECT * FROM sites WHERE domain = ?", (domain,))
        return dict(zip([c[0] for c in cur.description], cur.fetchone()))

    def all_sites(self) -> dict[str, dict]:
        cur = self.db.execute("SELECT * FROM sites")
        cols = [c[0] for c in cur.description]
        return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}

    def update_site(self, domain: str, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE sites SET {sets} WHERE domain = ?", (*fields.values(), domain))

    def save_pages(self, domain: str, pages: list[tuple[str, str]]) -> None:
        """Ajoute les pages du sitemap ; marque « à revoir » celles modifiées depuis."""
        self.db.executemany(
            """INSERT INTO pages(url, domain, lastmod) VALUES (?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET
                 changed = CASE WHEN excluded.lastmod != pages.lastmod THEN 1 ELSE pages.changed END,
                 lastmod = excluded.lastmod""",
            [(u, domain, m) for u, m in pages],
        )

    def pages_to_check(self, domain: str, limit: int) -> list[str]:
        """Priorité : jamais vues, puis modifiées (lastmod), puis les plus anciennes."""
        rows = self.db.execute(
            """SELECT url FROM pages
               WHERE domain = ? AND (is_product IS NULL OR is_product = 1 OR changed = 1)
               ORDER BY last_checked IS NOT NULL, changed DESC, last_checked ASC
               LIMIT ?""",
            (domain, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def mark_checked(self, domain: str, checked: dict[str, bool], now: float) -> None:
        self.db.executemany(
            """INSERT INTO pages(url, domain, is_product, last_checked, changed)
               VALUES (?, ?, ?, ?, 0)
               ON CONFLICT(url) DO UPDATE SET is_product = excluded.is_product,
                 last_checked = excluded.last_checked, changed = 0""",
            [(u, domain, int(p), now) for u, p in checked.items()],
        )

    def page_count(self, domain: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM pages WHERE domain = ?", (domain,)).fetchone()[0]

    def commit(self) -> None:
        self.db.commit()
