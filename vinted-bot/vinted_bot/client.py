"""Client minimal pour l'API publique (non officielle) du catalogue Vinted."""

import logging
import random
import time
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)

try:  # curl_cffi imite l'empreinte TLS de Chrome : beaucoup moins de blocages
    from curl_cffi import requests as http

    _IMPERSONATE = {"impersonate": "chrome"}
except ImportError:  # repli sur requests classique
    import requests as http

    _IMPERSONATE = {}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)

# Paramètres "liste" de l'URL web (brand_ids[]=1&brand_ids[]=2) -> "1,2" pour l'API
_PARAMS_LISTE = [
    "catalog_ids", "brand_ids", "size_ids", "status_ids", "color_ids",
    "material_ids", "video_game_platform_ids", "patterns_ids",
]


class VintedErreur(Exception):
    pass


def params_depuis_url(url: str) -> dict:
    """Convertit une URL de recherche Vinted (copiée du navigateur) en paramètres d'API."""
    qs = parse_qs(urlparse(url).query)
    params = {}
    for cle in _PARAMS_LISTE:
        valeurs = qs.get(cle + "[]") or qs.get(cle)
        if valeurs:
            params[cle] = ",".join(",".join(valeurs).split(","))
    for cle in ("search_text", "price_from", "price_to", "currency"):
        if qs.get(cle):
            params[cle] = qs[cle][0]
    return params


class VintedClient:
    def __init__(self, domaine="www.vinted.fr", pause=(2.0, 5.0)):
        self.base = f"https://{domaine}"
        self.pause = pause
        self.session = None
        self._derniere_requete = 0.0

    def _nouvelle_session(self):
        session = http.Session(**_IMPERSONATE)
        session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "fr-FR,fr;q=0.9",
        })
        # La page d'accueil dépose le cookie "access_token_web" exigé par l'API
        r = session.get(self.base + "/", timeout=20)
        if r.status_code >= 400:
            raise VintedErreur(
                f"Vinted refuse la connexion (HTTP {r.status_code}). "
                "Installe curl_cffi (pip install curl_cffi) ou réessaie plus tard."
            )
        self.session = session
        log.debug("Session Vinted initialisée")

    def _attendre(self):
        delai = random.uniform(*self.pause) - (time.time() - self._derniere_requete)
        if delai > 0:
            time.sleep(delai)
        self._derniere_requete = time.time()

    def rechercher(self, params: dict, ordre="newest_first", page=1, par_page=96) -> list:
        """Renvoie la liste brute des annonces (dicts JSON) d'une page de résultats."""
        requete = {**params, "order": ordre, "page": page, "per_page": par_page}
        for tentative in range(3):
            if self.session is None:
                self._nouvelle_session()
            self._attendre()
            r = self.session.get(self.base + "/api/v2/catalog/items", params=requete, timeout=20)
            if r.status_code == 200:
                return r.json().get("items", [])
            if r.status_code in (401, 403):
                log.info("Session expirée (HTTP %s), renouvellement…", r.status_code)
                self.session = None
                time.sleep(5 * (tentative + 1))
            elif r.status_code == 429:
                log.warning("Trop de requêtes (HTTP 429), pause de 2 minutes…")
                time.sleep(120)
            else:
                raise VintedErreur(f"Réponse inattendue de Vinted : HTTP {r.status_code}")
        raise VintedErreur("Impossible d'interroger Vinted après 3 tentatives")
