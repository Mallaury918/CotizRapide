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
            """INSERT INTO listings(key, watch, source, title, url, currency, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET last_seen = excluded.last_seen,
                                              title = excluded.title""",
            (listing.key, watch, listing.source, listing.title, listing.url,
             listing.currency, now, now),
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

    def commit(self) -> None:
        self.db.commit()
