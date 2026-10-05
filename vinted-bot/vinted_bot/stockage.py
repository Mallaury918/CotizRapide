"""Mémoire du bot (SQLite) : annonces déjà vues et historique des prix du marché."""

import sqlite3
import time


class Stockage:
    def __init__(self, chemin="vinted_bot.db"):
        self.db = sqlite3.connect(chemin)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS vues (
                id INTEGER, recherche TEXT, vu_le REAL, PRIMARY KEY (id, recherche));
            CREATE TABLE IF NOT EXISTS prix (
                id INTEGER, recherche TEXT, prix REAL, marque TEXT, etat TEXT, vu_le REAL,
                PRIMARY KEY (id, recherche));
            CREATE TABLE IF NOT EXISTS affaires (
                id INTEGER, recherche TEXT, titre TEXT, prix REAL, reference REAL,
                benefice REAL, url TEXT, envoye_le REAL);
            CREATE TABLE IF NOT EXISTS meta (recherche TEXT PRIMARY KEY, dernier_echantillon REAL);
            CREATE TABLE IF NOT EXISTS flux (
                id INTEGER PRIMARY KEY, marque TEXT, etat TEXT, prix REAL, catalogue INTEGER,
                jetons TEXT, vu_le REAL);
            CREATE INDEX IF NOT EXISTS flux_vu_le ON flux (vu_le);
            CREATE TABLE IF NOT EXISTS flux_jetons (
                marque TEXT, jeton TEXT, id INTEGER, PRIMARY KEY (marque, jeton, id)) WITHOUT ROWID;
        """)

    def connait_recherche(self, recherche) -> bool:
        return self.db.execute(
            "SELECT 1 FROM vues WHERE recherche = ? LIMIT 1", (recherche,)).fetchone() is not None

    def deja_vue(self, id_, recherche) -> bool:
        return self.db.execute(
            "SELECT 1 FROM vues WHERE id = ? AND recherche = ?", (id_, recherche)).fetchone() is not None

    def marquer_vue(self, id_, recherche):
        self.db.execute("INSERT OR IGNORE INTO vues VALUES (?, ?, ?)", (id_, recherche, time.time()))

    def enregistrer_prix(self, annonces, recherche):
        maintenant = time.time()
        self.db.executemany(
            "INSERT OR REPLACE INTO prix VALUES (?, ?, ?, ?, ?, ?)",
            [(a.id, recherche, a.prix_total, a.marque, a.etat, maintenant) for a in annonces])

    def historique(self, recherche, jours=30) -> list:
        limite = time.time() - jours * 86400
        return self.db.execute(
            "SELECT id, prix, marque, etat FROM prix WHERE recherche = ? AND vu_le >= ?",
            (recherche, limite)).fetchall()

    def echantillon_a_rafraichir(self, recherche, heures) -> bool:
        ligne = self.db.execute(
            "SELECT dernier_echantillon FROM meta WHERE recherche = ?", (recherche,)).fetchone()
        return ligne is None or time.time() - ligne[0] > heures * 3600

    def echantillon_fait(self, recherche):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (recherche, time.time()))

    def noter_affaire(self, aff, recherche):
        a = aff.annonce
        self.db.execute("INSERT INTO affaires VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (a.id, recherche, a.titre, a.prix, aff.reference, aff.benefice, a.url, time.time()))

    def nettoyer(self, jours=30):
        limite = time.time() - jours * 86400
        self.db.execute("DELETE FROM prix WHERE vu_le < ?", (limite,))
        # On garde les annonces vues deux fois plus longtemps pour ne jamais re-notifier
        self.db.execute("DELETE FROM vues WHERE vu_le < ?", (time.time() - 2 * jours * 86400,))

    # ─── Flux global ───────────────────────────────────────────────────────────

    def dernier_id_flux(self):
        return self.db.execute("SELECT MAX(id) FROM flux").fetchone()[0]

    def dans_flux(self, id_) -> bool:
        return self.db.execute("SELECT 1 FROM flux WHERE id = ?", (id_,)).fetchone() is not None

    def taille_flux(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM flux").fetchone()[0]

    def enregistrer_flux(self, annonces_jetons):
        maintenant = time.time()
        self.db.executemany(
            "INSERT OR REPLACE INTO flux VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(a.id, a.marque, a.etat, a.prix_total, a.catalogue, " ".join(sorted(j)), maintenant)
             for a, j in annonces_jetons])
        self.db.executemany(
            "INSERT OR IGNORE INTO flux_jetons VALUES (?, ?, ?)",
            [(a.marque, jeton, a.id) for a, j in annonces_jetons for jeton in j])

    def candidats_flux(self, marque, jetons, communs_min, jours) -> list:
        """Annonces de la même marque partageant au moins `communs_min` mots avec `jetons`."""
        jetons = list(jetons)
        return self.db.execute(f"""
            SELECT f.id, f.prix, f.etat, f.catalogue, f.jetons FROM flux f
            JOIN (SELECT id FROM flux_jetons
                  WHERE marque = ? AND jeton IN ({",".join("?" * len(jetons))})
                  GROUP BY id HAVING COUNT(*) >= ?) c ON c.id = f.id
            WHERE f.vu_le >= ?""",
            (marque, *jetons, communs_min, time.time() - jours * 86400)).fetchall()

    def nettoyer_flux(self, jours):
        limite = time.time() - jours * 86400
        anciennes = self.db.execute(
            "SELECT id, marque, jetons FROM flux WHERE vu_le < ?", (limite,)).fetchall()
        self.db.executemany(
            "DELETE FROM flux_jetons WHERE marque = ? AND jeton = ? AND id = ?",
            [(marque, jeton, id_) for id_, marque, j in anciennes for jeton in j.split()])
        self.db.execute("DELETE FROM flux WHERE vu_le < ?", (limite,))

    def valider(self):
        self.db.commit()
