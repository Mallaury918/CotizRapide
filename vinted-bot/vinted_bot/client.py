"""Client minimal pour l'API publique (non officielle) du catalogue Vinted.

Depuis septembre 2026, le catalogue est servi par api.vinted.<pays>/svc-catalogue/items.
L'API exige l'identité anonyme que le site donne à tout visiteur : le cookie
« access_token_web », l'en-tête « X-Anon-Id » et, s'il existe, le jeton CSRF de la page.
"""

import logging
import random
import re
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
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)

# Filtres de l'URL web (brand_ids[]=1&brand_ids[]=2) -> attribute_ids[brand]=1,2 pour l'API
_FILTRES = {
    "catalog_ids": "catalog", "brand_ids": "brand", "size_ids": "size", "status_ids": "status",
    "color_ids": "color", "material_ids": "material",
}
_CSRF = re.compile(r'CSRF_TOKEN\\?"?\s*[:=]\s*\\?"([0-9A-Za-z_-]{16,})')


class VintedErreur(Exception):
    pass


def params_depuis_url(url: str) -> dict:
    """Convertit une URL de recherche Vinted (copiée du navigateur) en paramètres d'API."""
    qs = parse_qs(urlparse(url).query)
    params = {}
    for ancien, nouveau in _FILTRES.items():
        valeurs = qs.get(ancien + "[]") or qs.get(ancien) or qs.get(f"attribute_ids[{nouveau}]")
        if valeurs:
            params[f"attribute_ids[{nouveau}]"] = ",".join(",".join(valeurs).split(","))
    for cle in ("search_text", "price_from", "price_to", "currency"):
        if qs.get(cle) and qs[cle][0].strip():
            params[cle] = qs[cle][0]
    return params


class VintedClient:
    def __init__(self, domaine="www.vinted.fr", pause=(2.0, 5.0)):
        hote = domaine.removeprefix("www.")
        self.site = f"https://www.{hote}"
        self.api = f"https://api.{hote}"
        self.pause = pause
        self.session = None
        self.entetes_api = {}
        self._derniere_requete = 0.0
        self._url_profil = None   # adresse des profils qui a fonctionné

    def _nouvelle_session(self):
        session = http.Session(**_IMPERSONATE)
        session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
        })
        r = session.get(self.site + "/", timeout=20, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none",
        })
        if r.status_code >= 400:
            raise VintedErreur(
                f"Vinted refuse la connexion (HTTP {r.status_code}). "
                "Installe curl_cffi (pip install curl_cffi) ou réessaie plus tard."
            )
        jeton = session.cookies.get("access_token_web")
        if not jeton:
            raise VintedErreur("Vinted n'a pas fourni de jeton de session (cookie access_token_web).")
        anon = r.headers.get("X-Anon-Id") or session.cookies.get("anon_id") or ""
        csrf = _CSRF.search(r.text or "")
        self.entetes_api = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {jeton}",
            "Cookie": "; ".join(f"{k}={v}" for k, v in session.cookies.items()),
            "Origin": self.site,
            "Referer": self.site + "/",
            "Locale": "fr-FR",
            "Platform": "web",
            "X-Next-App": "marketplace-web",
            "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-site",
        }
        if anon:
            self.entetes_api["X-Anon-Id"] = anon.strip()
        if csrf:
            self.entetes_api["X-Csrf-Token"] = csrf.group(1)
        self.session = session
        log.debug("Session Vinted initialisée (anon_id : %s, csrf : %s)", bool(anon), bool(csrf))

    def _attendre(self):
        delai = random.uniform(*self.pause) - (time.time() - self._derniere_requete)
        if delai > 0:
            time.sleep(delai)
        self._derniere_requete = time.time()

    def rechercher(self, params: dict, ordre="newest_first", page=1, par_page=96) -> list:
        """Renvoie la liste brute des annonces (dicts JSON) d'une page de résultats."""
        requete = {k: v for k, v in params.items() if v not in (None, "", 0)}
        requete.update(order=ordre, page=page, per_page=par_page, time=int(time.time()))
        requete.setdefault("currency", "EUR")
        reponse = self.requete(self.api + "/svc-catalogue/items", requete)
        items = reponse.get("items") or (reponse.get("data") or {}).get("items") or []
        for item in items:  # les liens sont devenus relatifs (« /items/123-… »)
            if str(item.get("url", "")).startswith("/"):
                item["url"] = self.site + item["url"]
        return items

    def utilisateur(self, id_: int) -> dict:
        """Profil public d'un membre (ventes, avis, note…)."""
        adresses = [self._url_profil] if self._url_profil else [
            self.site + "/api/v2/users/{}", self.api + "/api/v2/users/{}"]
        derniere_erreur = None
        for adresse in adresses:
            try:
                reponse = self.requete(adresse.format(id_))
            except VintedErreur as e:
                derniere_erreur = e
                continue
            self._url_profil = adresse
            return reponse.get("user") or reponse
        raise derniere_erreur

    def requete(self, url: str, params=None) -> dict:
        for tentative in range(3):
            if self.session is None:
                self._nouvelle_session()
            self._attendre()
            r = self.session.get(url, params=params, headers=self.entetes_api, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                log.info("Session expirée (HTTP %s), renouvellement…", r.status_code)
                self.session = None
                time.sleep(5 * (tentative + 1))
            elif r.status_code == 429:
                log.warning("Trop de requêtes (HTTP 429), pause de 2 minutes…")
                time.sleep(120)
            else:
                detail = (r.text or "")[:200].replace("\n", " ")
                raise VintedErreur(f"Réponse inattendue de Vinted : HTTP {r.status_code} "
                                   f"sur {url.split('?')[0]} {detail}")
        raise VintedErreur("Impossible d'interroger Vinted après 3 tentatives")
