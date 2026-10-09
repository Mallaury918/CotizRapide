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

from .analyse import criteres_pour, evaluer, passe_filtres, simplifier, tailles_compatibles
from .vendeurs import verifier_vendeur

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

SIMILARITE_MIN = 0.5   # part de mots communs (indice de Jaccard) entre deux titres

# Mots qui distinguent deux modèles d'une même gamme : ils doivent être identiques des deux
# côtés (« Dunk Low » ≠ « Dunk High », « iPhone 13 » ≠ « iPhone 13 Pro »). Les nombres aussi
# (« Air Max 90 » ≠ « Air Max 95 », « 550 » ≠ « 530 »).
VARIANTES = {"low", "mid", "high", "pro", "max", "mini", "plus", "ultra", "lite", "oled",
             "slim", "air", "xl", "xxl", "jr", "junior", "kids", "enfant", "bebe", "baby", "gs", "ps", "td",
             # parfums : concentration, déclinaison et présentation changent le prix
             "edp", "edt", "edc", "extrait", "elixir", "intense", "absolu", "absolue", "extreme",
             "testeur", "tester", "coffret"}
_VOLUME = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*ml\b")
_CONCENTRATIONS = [("eau de parfum", " edp "), ("eau de toilette", " edt "), ("eau de cologne", " edc ")]
_TAILLE = re.compile(r"\b(?:taille|pointure|size|t)[\s:.]*\d+(?:[.,]5)?\b")


def _normaliser_parfum(texte: str) -> str:
    """« Eau de Parfum 100 ml » → « edp 100ml » : même écriture pour la même contenance."""
    for long, court in _CONCENTRATIONS:
        texte = texte.replace(long, court)
    return _VOLUME.sub(lambda m: f" {float(m.group(1).replace(',', '.')):g}ml ", texte)


def jetons(titre: str, marque: str = "", taille: str = "") -> set:
    """Mots significatifs d'un titre, sans la marque, la taille ni les mots vides."""
    texte = _TAILLE.sub(" ", _normaliser_parfum(simplifier(titre).replace("-", "")))
    exclus = (MOTS_VIDES | set(re.findall(r"[a-z0-9]+", simplifier(marque).replace("-", "")))
              | set(re.findall(r"[a-z0-9]+", simplifier(taille))))
    return {m for m in re.findall(r"\d+(?:\.\d+)?ml|[a-z0-9]+", texte) if len(m) >= 2 and m not in exclus}


def familles(j: set) -> set:
    return {nom for nom, mots in FAMILLES.items() if j & mots}


def _signature(j: set) -> set:
    """Ce qui identifie le modèle exact : nombres, contenances (« 100ml ») et variantes."""
    return {m for m in j if m.isdigit() or m in VARIANTES or re.fullmatch(r"[\d.]+ml", m)}


def comparables(ja: set, jb: set) -> bool:
    communs = len(ja & jb)
    if not communs or communs / len(ja | jb) < SIMILARITE_MIN:
        return False
    if _signature(ja) != _signature(jb):
        return False
    fa, fb = familles(ja), familles(jb)
    if fa and fb:
        return bool(fa & fb)
    return not ((fa | fb) & FAMILLES_RISQUEES)


class Flux:
    """Surveillance de toutes les nouvelles annonces d'un site.

    Vinted : on compare les annonces de la même marque.
    Leboncoin : de la même catégorie (et de la même marque si elle est renseignée), car
    beaucoup d'annonces n'ont pas de marque mais toutes ont une catégorie.
    """

    def __init__(self, section: dict, crit: dict, nom="Tout Vinted", table="flux",
                 par_categorie=False, intervalle=30, pages_max=3, sans_marque=False):
        self.conf = section
        self.crit = crit
        self.nom = nom
        self.table = table
        self.par_categorie = par_categorie
        self.intervalle = section.get("intervalle_secondes", intervalle)
        self.pages_max = section.get("pages_max", pages_max)
        self.jours = section.get("historique_jours", 10)
        self.sans_marque = not section.get("ignorer_sans_marque", not sans_marque)
        self.alertes_max = section.get("alertes_max_par_heure", 30)
        self._alertes = deque()

    @classmethod
    def vinted(cls, conf: dict) -> "Flux":
        section = conf.get("flux", {})
        return cls(section, criteres_pour(section, conf))

    @classmethod
    def leboncoin(cls, conf: dict) -> "Flux":
        lbc = conf.get("leboncoin", {})
        section = lbc.get("tout_le_site", {})
        # Critères : globaux, puis ceux de [leboncoin], puis ceux de [leboncoin.tout_le_site]
        source = {**{k: v for k, v in lbc.items() if not isinstance(v, (dict, list))}, **section}
        source["mots_exclus"] = list(lbc.get("mots_exclus", [])) + list(section.get("mots_exclus", []))
        flux = cls(section, criteres_pour(source, conf), nom="Tout Leboncoin", table="lbc_flux",
                   par_categorie=True, intervalle=60, pages_max=2, sans_marque=True)
        flux.conf = {**section, "actif": bool(lbc.get("actif") and section.get("actif"))}
        return flux

    @property
    def actif(self) -> bool:
        return self.conf.get("actif", False)

    def groupe(self, a) -> str:
        """Clé des annonces comparables entre elles."""
        if self.par_categorie:
            return f"{simplifier(a.marque)}|{a.catalogue}"
        return a.marque

    def _lire_nouveautes(self, client, stock) -> list:
        dernier = stock.dernier_id_flux(self.table)
        lues = {}
        for page in range(1, self.pages_max + 1):
            annonces = client.nouveautes(page)
            for a in annonces:
                lues[a.id] = a
            if not annonces or dernier is None or min(a.id for a in annonces) <= dernier:
                break
        else:
            log.info("[%s] Le site publie plus vite que le bot ne lit : des annonces ont pu "
                     "être manquées (augmente pages_max ou baisse intervalle_secondes).", self.nom)
        return [a for a in lues.values() if not stock.dans_flux(a.id, self.table)]

    def _peut_alerter(self) -> bool:
        maintenant = time.time()
        while self._alertes and maintenant - self._alertes[0] > 3600:
            self._alertes.popleft()
        return len(self._alertes) < self.alertes_max

    def passage(self, client, stock, notif) -> int:
        nouvelles = [a for a in self._lire_nouveautes(client, stock) if a.marque or self.sans_marque]
        lignes = [(a, jetons(a.titre, a.marque, a.taille), self.groupe(a)) for a in nouvelles]
        lignes = [(a, j, g) for a, j, g in lignes if j]
        stock.enregistrer_flux(lignes, self.table)

        trouvees = 0
        for a, j, groupe in lignes:
            if not passe_filtres(a, self.crit):
                continue
            candidats = stock.candidats_flux(groupe, j, math.ceil(SIMILARITE_MIN * len(j)),
                                             self.jours, self.table)
            historique = [
                (id_, prix, a.marque, etat) for id_, prix, etat, catalogue, jb, taille in candidats
                if (not a.catalogue or not catalogue or catalogue == a.catalogue)
                and tailles_compatibles(a.taille, taille)
                and comparables(j, set(jb.split()))
            ]
            aff = evaluer(a, historique, self.crit)
            if not aff:
                continue
            if not self._peut_alerter():
                log.warning("[%s] Limite de %d alertes/heure atteinte, affaire ignorée : %s",
                            self.nom, self.alertes_max, a.url)
                continue
            if not verifier_vendeur(aff, client, stock, self.crit):
                continue
            aff.groupe += " · même catégorie · même modèle" if self.par_categorie else " · même modèle"
            notif.envoyer(aff, self.nom)
            stock.noter_affaire(aff, self.nom)
            self._alertes.append(time.time())
            trouvees += 1
        stock.valider()
        log.info("[%s] %d nouvelle(s) annonce(s) analysée(s), %d en mémoire, %d bonne(s) affaire(s).",
                 self.nom, len(lignes), stock.taille_flux(self.table), trouvees)
        return trouvees
