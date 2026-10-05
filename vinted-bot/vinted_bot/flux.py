"""Mode « flux global » : surveille toutes les nouvelles annonces du site, sans mots-clés.

Sans recherche pour cadrer les comparaisons, le bot se construit lui-même sa base de prix
à partir du flux. Pour chaque nouvelle annonce, il retient comme comparables les annonces
de la même marque, au titre proche et du même type d'article (des chaussettes Nike ne sont
pas comparées à des baskets Nike).
"""

import logging
import math
import re
import time
from collections import deque

from .analyse import criteres_pour, evaluer, normaliser, passe_filtres, simplifier

log = logging.getLogger(__name__)

MOTS_VIDES = {
    "le", "la", "les", "de", "des", "du", "un", "une", "et", "ou", "en", "au", "aux", "pour",
    "avec", "sans", "sur", "dans", "par", "tres", "bon", "bonne", "etat", "neuf", "neuve",
    "jamais", "porte", "portee", "peu", "tbe", "be", "etiquette", "etiquettes", "taille",
    "pointure", "homme", "femme", "mixte", "garcon", "fille", "original", "originale",
    "authentique", "vends", "vend", "superbe", "joli", "jolie", "magnifique", "comme",
}

# Types d'articles : deux annonces dont les types diffèrent ne sont jamais comparées
FAMILLES = {
    "chaussures": {"baskets", "basket", "sneakers", "sneaker", "chaussures", "chaussure", "bottes",
                   "bottines", "boots", "sandales", "claquettes", "escarpins", "mocassins", "derbies"},
    "pull": {"pull", "sweat", "hoodie", "gilet", "cardigan", "crewneck", "sweatshirt"},
    "tshirt": {"tshirt", "tee", "top", "debardeur", "maillot", "brassiere"},
    "chemise": {"chemise", "polo", "blouse", "surchemise"},
    "veste": {"veste", "manteau", "doudoune", "blouson", "parka", "trench", "coupevent", "jacket"},
    "bas": {"jean", "jeans", "pantalon", "short", "jogging", "legging", "jupe", "cargo"},
    "robe": {"robe", "combinaison"},
    "sac": {"sac", "pochette", "portefeuille", "banane", "sacoche", "cabas", "cartable", "valise"},
    "accessoires": {"chaussettes", "casquette", "bonnet", "echarpe", "gants", "ceinture", "lunettes",
                    "bracelet", "collier", "bague", "boucles", "montre", "cravate", "noeud"},
    "objets": {"coque", "housse", "etui", "protection", "lacets", "boite", "sticker", "stickers",
               "poster", "portecles", "chargeur", "cable", "manette", "jeu", "jeux", "figurine",
               "peluche", "carte", "cartes", "livre", "magnet"},
}
# Familles d'articles bon marché : une annonce de ce type n'est jamais comparée à une annonce
# sans type (sinon « Coque iPhone 15 » ressemblerait à « iPhone 15 »)
FAMILLES_RISQUEES = {"accessoires", "objets"}

SIMILARITE_MIN = 0.4   # part de mots communs (indice de Jaccard) entre deux titres
_TAILLE = re.compile(r"\b(?:taille|pointure|size|t)[\s:.]*\d+(?:[.,]5)?\b")


def jetons(titre: str, marque: str = "", taille: str = "") -> set:
    """Mots significatifs d'un titre, sans la marque, la taille ni les mots vides."""
    texte = _TAILLE.sub(" ", simplifier(titre).replace("-", ""))
    exclus = (MOTS_VIDES | set(re.findall(r"[a-z0-9]+", simplifier(marque).replace("-", "")))
              | set(re.findall(r"[a-z0-9]+", simplifier(taille))))
    return {m for m in re.findall(r"[a-z0-9]+", texte) if len(m) >= 2 and m not in exclus}


def familles(j: set) -> set:
    return {nom for nom, mots in FAMILLES.items() if j & mots}


def comparables(ja: set, jb: set) -> bool:
    communs = len(ja & jb)
    if not communs or communs / len(ja | jb) < SIMILARITE_MIN:
        return False
    fa, fb = familles(ja), familles(jb)
    if fa and fb:
        return bool(fa & fb)
    return not ((fa | fb) & FAMILLES_RISQUEES)


class Flux:
    def __init__(self, conf: dict):
        self.conf = conf.get("flux", {})
        self.crit = criteres_pour(self.conf, conf)
        self.intervalle = self.conf.get("intervalle_secondes", 30)
        self.pages_max = self.conf.get("pages_max", 3)
        self.jours = self.conf.get("historique_jours", 10)
        self.sans_marque = not self.conf.get("ignorer_sans_marque", True)
        self.alertes_max = self.conf.get("alertes_max_par_heure", 30)
        self._alertes = deque()

    @property
    def actif(self) -> bool:
        return self.conf.get("actif", False)

    def _lire_nouveautes(self, client, stock) -> list:
        dernier = stock.dernier_id_flux()
        lues = {}
        for page in range(1, self.pages_max + 1):
            items = client.rechercher({"currency": "EUR"}, ordre="newest_first", page=page)
            for a in filter(None, map(normaliser, items)):
                lues[a.id] = a
            if not items or dernier is None or min(int(i["id"]) for i in items) <= dernier:
                break
        else:
            log.info("[Flux] Le site publie plus vite que le bot ne lit : des annonces ont pu "
                     "être manquées (augmente pages_max ou baisse intervalle_secondes).")
        return [a for a in lues.values() if not stock.dans_flux(a.id)]

    def _peut_alerter(self) -> bool:
        maintenant = time.time()
        while self._alertes and maintenant - self._alertes[0] > 3600:
            self._alertes.popleft()
        return len(self._alertes) < self.alertes_max

    def passage(self, client, stock, notif) -> int:
        nouvelles = [a for a in self._lire_nouveautes(client, stock) if a.marque or self.sans_marque]
        avec_jetons = [(a, jetons(a.titre, a.marque, a.taille)) for a in nouvelles]
        avec_jetons = [(a, j) for a, j in avec_jetons if j]
        stock.enregistrer_flux(avec_jetons)

        trouvees = 0
        for a, j in avec_jetons:
            if not passe_filtres(a, self.crit):
                continue
            candidats = stock.candidats_flux(a.marque, j, math.ceil(SIMILARITE_MIN * len(j)), self.jours)
            historique = [
                (id_, prix, a.marque, etat) for id_, prix, etat, catalogue, jb in candidats
                if (not a.catalogue or not catalogue or catalogue == a.catalogue)
                and comparables(j, set(jb.split()))
            ]
            aff = evaluer(a, historique, self.crit)
            if not aff:
                continue
            if not self._peut_alerter():
                log.warning("[Flux] Limite de %d alertes/heure atteinte, affaire ignorée : %s",
                            self.alertes_max, a.url)
                continue
            aff.groupe += " · titres proches"
            notif.envoyer(aff, "Tout Vinted")
            stock.noter_affaire(aff, "Tout Vinted")
            self._alertes.append(time.time())
            trouvees += 1
        stock.valider()
        log.info("[Flux] %d nouvelle(s) annonce(s) analysée(s), %d en mémoire, %d bonne(s) affaire(s).",
                 len(avec_jetons), stock.taille_flux(), trouvees)
        return trouvees
