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

    def valider(self):
        self.db.commit()
