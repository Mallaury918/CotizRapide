"""Mémoire du bot (SQLite) : annonces déjà vues et historique des prix du marché."""

import sqlite3
import time


TABLES_FLUX = ("flux", "lbc_flux")


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
            -- ancien cache des profils Vinted, remplacé par « profils » (Vinted + Leboncoin)
            DROP TABLE IF EXISTS vendeurs;
            CREATE TABLE IF NOT EXISTS profils (
                cle TEXT PRIMARY KEY, ventes INTEGER, avis INTEGER, note REAL,
                ventes_connues INTEGER, maj_le REAL);
        """)
        # Une mémoire « tout le site » par site : flux (Vinted) et lbc_flux (Leboncoin).
        # La colonne « marque » contient la clé de regroupement des annonces comparables.
        for table in TABLES_FLUX:
            self.db.executescript(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id INTEGER PRIMARY KEY, marque TEXT, etat TEXT, prix REAL, catalogue INTEGER,
                    jetons TEXT, vu_le REAL);
                CREATE INDEX IF NOT EXISTS {table}_vu_le ON {table} (vu_le);
                CREATE TABLE IF NOT EXISTS {table}_jetons (
                    marque TEXT, jeton TEXT, id INTEGER, PRIMARY KEY (marque, jeton, id)) WITHOUT ROWID;
            """)
            # Taille / pointure, ajoutée en octobre 2026 : vide (NULL) pour les annonces plus anciennes
            colonnes = {c[1] for c in self.db.execute(f"PRAGMA table_info({table})")}
            if "taille" not in colonnes:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN taille TEXT")

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
        self.db.execute("DELETE FROM profils WHERE maj_le < ?", (time.time() - 86400,))
        # On garde les annonces vues deux fois plus longtemps pour ne jamais re-notifier
        self.db.execute("DELETE FROM vues WHERE vu_le < ?", (time.time() - 2 * jours * 86400,))

    def profil_en_cache(self, cle, heures=24):
        """Profil vendeur mémorisé ; `cle` = « site:identifiant »."""
        ligne = self.db.execute(
            "SELECT ventes, avis, note, ventes_connues FROM profils WHERE cle = ? AND maj_le >= ?",
            (cle, time.time() - heures * 3600)).fetchone()
        return ligne and (*ligne[:3], bool(ligne[3]))

    def memoriser_profil(self, cle, p):
        self.db.execute("INSERT OR REPLACE INTO profils VALUES (?, ?, ?, ?, ?, ?)",
                        (cle, p.ventes, p.avis, p.note, int(p.ventes_connues), time.time()))

    # ─── Flux global ───────────────────────────────────────────────────────────

    def dernier_id_flux(self, table="flux"):
        return self.db.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]

    def dans_flux(self, id_, table="flux") -> bool:
        return self.db.execute(f"SELECT 1 FROM {table} WHERE id = ?", (id_,)).fetchone() is not None

    def taille_flux(self, table="flux") -> int:
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def enregistrer_flux(self, lignes, table="flux"):
        """`lignes` : (annonce, jetons du titre, clé de regroupement)."""
        maintenant = time.time()
        self.db.executemany(
            f"INSERT OR REPLACE INTO {table} (id, marque, etat, prix, catalogue, jetons, vu_le, taille)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(a.id, groupe, a.etat, a.prix_total, a.catalogue, " ".join(sorted(j)), maintenant,
              a.taille or "") for a, j, groupe in lignes])
        self.db.executemany(
            f"INSERT OR IGNORE INTO {table}_jetons VALUES (?, ?, ?)",
            [(groupe, jeton, a.id) for a, j, groupe in lignes for jeton in j])

    def candidats_flux(self, groupe, jetons, communs_min, jours, table="flux") -> list:
        """Annonces du même groupe partageant au moins `communs_min` mots avec `jetons`."""
        jetons = list(jetons)
        return self.db.execute(f"""
            SELECT f.id, f.prix, f.etat, f.catalogue, f.jetons, f.taille FROM {table} f
            JOIN (SELECT id FROM {table}_jetons
                  WHERE marque = ? AND jeton IN ({",".join("?" * len(jetons))})
                  GROUP BY id HAVING COUNT(*) >= ?) c ON c.id = f.id
            WHERE f.vu_le >= ?""",
            (groupe, *jetons, communs_min, time.time() - jours * 86400)).fetchall()

    def nettoyer_flux(self, jours, table="flux"):
        limite = time.time() - jours * 86400
        anciennes = self.db.execute(
            f"SELECT id, marque, jetons FROM {table} WHERE vu_le < ?", (limite,)).fetchall()
        self.db.executemany(
            f"DELETE FROM {table}_jetons WHERE marque = ? AND jeton = ? AND id = ?",
            [(marque, jeton, id_) for id_, marque, j in anciennes for jeton in j.split()])
        self.db.execute(f"DELETE FROM {table} WHERE vu_le < ?", (limite,))

    def valider(self):
        self.db.commit()
