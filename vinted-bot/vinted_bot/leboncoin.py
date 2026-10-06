"""Client Leboncoin : recherches ciblées dans toute la France, annonces avec livraison.

Leboncoin n'a pas d'API publique : le bot utilise celle de son application
(api.leboncoin.fr/finder/search), comme la bibliothèque libre « lbc ». Le site est protégé
par DataDome, très sensible aux robots : curl_cffi est obligatoire et le rythme doit
rester lent.
"""

import logging
import random
import time
import uuid
from urllib.parse import parse_qs, urlparse

from .analyse import PROTECTION_FIXE, PROTECTION_TAUX, Annonce, Profil
from .client import ErreurSite

log = logging.getLogger(__name__)

try:
    from curl_cffi import requests as http
except ImportError:
    http = None

API = "https://api.leboncoin.fr"
SITE = "https://www.leboncoin.fr"
# Empreintes de navigateurs mobiles (l'API est celle de l'application)
_IMPERSONATIONS = ["chrome131_android", "chrome_android", "safari172_ios", "safari17_2_ios"]


def _user_agent() -> str:
    """User-Agent de l'application Leboncoin, au format qu'elle envoie elle-même."""
    if random.random() < 0.5:
        version = random.choice(["18.5", "18.6", "26.0", "26.1"])
        return (f"LBC;iOS;{version};iPhone;phone;{str(uuid.uuid4()).upper()};wifi;"
                f"{random.choice(['101.44.0', '101.43.1', '101.42.1'])}")
    modele = random.choice(["SM-S911B", "SM-A546B", "Pixel 7", "Pixel 8", "Redmi Note 12"])
    return (f"LBC;Android;{random.choice(['13', '14', '15'])};{modele};phone;{uuid.uuid4().hex[:16]};"
            f"wifi;{random.choice(['100.85.2', '100.84.1'])}")


def _attribut(ad: dict, cle: str) -> str:
    for attr in ad.get("attributes") or []:
        if attr.get("key") == cle:
            return (attr.get("value_label") or attr.get("value") or "").strip()
    return ""


def _marque(ad: dict) -> str:
    """Le champ « brand » vaut « leboncoin » (le site) : la vraie marque est dans un attribut,
    « brand » ou propre à la catégorie (« console_brand », « phone_brand »…)."""
    marque = _attribut(ad, "brand")
    if not marque:
        for attr in ad.get("attributes") or []:
            if str(attr.get("key", "")).endswith("_brand"):
                marque = (attr.get("value_label") or attr.get("value") or "").strip()
                break
    if not marque and str(ad.get("brand", "")).lower() not in ("", "leboncoin"):
        marque = ad["brand"].strip()
    return marque


def _frais_acheteur(ad: dict, prix: float) -> float:
    """Frais de protection acheteur réels (« buyer_fee », en centimes), sinon estimés."""
    montant = (ad.get("buyer_fee") or {}).get("amount")
    if isinstance(montant, (int, float)) and montant >= 0:
        return montant / 100
    return PROTECTION_FIXE + prix * PROTECTION_TAUX


def _port_le_moins_cher(ad: dict):
    """Prix du mode de livraison le moins cher (« shipping_fees », en centimes), ou None."""
    prix = [f.get("price") for f in ad.get("shipping_fees") or []
            if isinstance(f, dict) and isinstance(f.get("price"), (int, float)) and f["price"] >= 0]
    return min(prix) / 100 if prix else None


def normaliser_lbc(ad: dict):
    """Convertit une annonce Leboncoin au format commun du bot."""
    prix = None
    if ad.get("price_cents"):
        prix = ad["price_cents"] / 100
    elif ad.get("price"):
        prix = float(ad["price"][0] if isinstance(ad["price"], list) else ad["price"])
    if not prix or prix <= 0 or not ad.get("list_id"):
        return None
    images = ad.get("images") or {}
    owner = ad.get("owner") or {}
    return Annonce(
        id=int(ad["list_id"]),
        titre=(ad.get("subject") or "").strip(),
        prix=prix,
        prix_total=round(prix + _frais_acheteur(ad, prix), 2),
        marque=_marque(ad),
        taille=_attribut(ad, "clothing_tag") or _attribut(ad, "shoe_size"),
        etat=_attribut(ad, "condition"),
        url=ad.get("url") or f"{SITE}/ad/{ad['list_id']}",
        photo=(images.get("urls_large") or images.get("urls") or [images.get("thumb_url") or ""])[0],
        vendeur=owner.get("name", ""),
        favoris=int((ad.get("counters") or {}).get("favorites") or 0),
        catalogue=int(ad.get("category_id") or 0),
        vendeur_id=owner.get("user_id") or "",
        livraison=_port_le_moins_cher(ad),
    )


def filtres_depuis_url(url: str) -> dict:
    """Reprend les filtres d'une URL de recherche leboncoin.fr copiée du navigateur."""
    filtres = {}
    for cle, valeurs in parse_qs(urlparse(url).query).items():
        valeur = valeurs[0]
        if cle == "text":
            filtres["keywords"] = {"text": valeur}
        elif cle == "category":
            filtres["category"] = {"id": valeur}
        elif cle in ("locations", "shippable", "page", "sort", "order", "owner_type"):
            continue  # toute la France ; livraison et tri gérés par le bot
        elif valeur.count("-") == 1:  # intervalle, ex. price=100-300
            mini, maxi = valeur.split("-")
            plage = {k: int(v) for k, v in (("min", mini), ("max", maxi)) if v.isdigit()}
            if plage:
                filtres.setdefault("ranges", {})[cle] = plage
        else:
            filtres.setdefault("enums", {})[cle] = valeur.split(",")
    return filtres


def requete_recherche(recherche: dict, crit: dict, recentes: bool, page: int,
                      par_page: int, livraison: bool) -> dict:
    filtres = filtres_depuis_url(recherche["url"]) if recherche.get("url") else {}
    filtres.setdefault("category", {"id": str(recherche.get("categorie", "0"))})
    filtres.setdefault("enums", {})["ad_type"] = ["offer"]
    if recherche.get("mots_cles"):
        filtres["keywords"] = {"text": recherche["mots_cles"]}
    prix = {k: int(crit[c]) for k, c in (("min", "prix_min"), ("max", "prix_max")) if crit.get(c)}
    if prix:
        filtres.setdefault("ranges", {})["price"] = prix
    filtres["location"] = {"shippable": True} if livraison else {}
    requete = {
        "filters": filtres,
        "limit": par_page,
        "limit_alu": 3,
        "offset": par_page * (page - 1),
        "disable_total": True,
        "extend": True,
        "listing_source": "direct-search" if page == 1 else "pagination",
        "owner_type": recherche.get("type_vendeur", "all"),
        "sort_by": "time" if recentes else "relevance",
    }
    if recentes:
        requete["sort_order"] = "desc"
    return requete


class LeboncoinClient:
    site = "leboncoin"
    par_page = 35

    def __init__(self, pause=(4.0, 9.0), livraison=True):
        if http is None:
            raise ErreurSite("Leboncoin nécessite curl_cffi : lance « py -m pip install curl_cffi ».")
        self.pause = pause
        self.livraison = livraison
        self.session = None
        self._derniere_requete = 0.0

    def _nouvelle_session(self):
        session = http.Session(impersonate=random.choice(_IMPERSONATIONS))
        session.headers.update({
            "User-Agent": _user_agent(),
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-site",
        })
        r = session.get(SITE + "/", timeout=30)  # dépose les cookies, dont celui de DataDome
        if r.status_code >= 400 and r.status_code != 403:
            raise ErreurSite(f"Leboncoin refuse la connexion (HTTP {r.status_code}).")
        self.session = session

    def _attendre(self):
        delai = random.uniform(*self.pause) - (time.time() - self._derniere_requete)
        if delai > 0:
            time.sleep(delai)
        self._derniere_requete = time.time()

    def requete(self, methode: str, url: str, json=None) -> dict:
        for tentative in range(3):
            if self.session is None:
                self._nouvelle_session()
            self._attendre()
            r = self.session.request(methode, url, json=json, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 403:  # DataDome : nouvelle identité, puis on ralentit
                log.warning("Leboncoin bloque temporairement (DataDome, HTTP 403), nouvel essai…")
                self.session = None
                time.sleep(30 * (tentative + 1))
            elif r.status_code == 429:
                log.warning("Trop de requêtes sur Leboncoin (HTTP 429), pause de 5 minutes…")
                time.sleep(300)
            else:
                detail = (r.text or "")[:200].replace("\n", " ")
                raise ErreurSite(f"Réponse inattendue de Leboncoin : HTTP {r.status_code} "
                                 f"sur {url} {detail}")
        raise ErreurSite("Leboncoin bloque le bot (DataDome). Augmente l'intervalle "
                         "ou fais une pause de quelques heures.")

    def rechercher(self, requete: dict) -> list:
        return self.requete("POST", API + "/finder/search", requete).get("ads") or []

    def annonces(self, recherche: dict, crit: dict, recentes=True, page=1) -> list:
        """Annonces d'une recherche ciblée, déjà normalisées."""
        ads = self.rechercher(requete_recherche(recherche, crit, recentes, page,
                                                self.par_page, self.livraison))
        if self.livraison:  # double sécurité : on écarte toute annonce marquée non expédiable
            ads = [ad for ad in ads if _attribut(ad, "shippable").lower() not in ("false", "non")]
        return [a for a in map(normaliser_lbc, ads) if a]

    def nouveautes(self, page=1) -> list:
        """Dernières annonces de toutes les catégories (avec livraison si demandé)."""
        return self.annonces({}, {}, recentes=True, page=page)

    def profil(self, user_id: str) -> Profil:
        """Avis et note d'un vendeur. Leboncoin n'affiche pas de nombre de ventes."""
        infos = self.requete("GET", f"{API}/api/user-card/v2/{user_id}/infos")
        avis = infos.get("feedback") or {}
        return Profil(
            ventes=int(avis.get("received_count") or 0),
            avis=int(avis.get("received_count") or 0),
            note=round(float(avis.get("overall_score") or 0) * 5, 1),
            ventes_connues=False,
        )
