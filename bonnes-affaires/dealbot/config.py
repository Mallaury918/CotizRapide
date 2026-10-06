from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Mots qui signalent presque toujours un accessoire, une pièce ou un article HS :
# ils faussent le prix du marché et donnent de fausses « affaires ».
DEFAULT_EXCLUDE = [
    "coque", "housse", "étui", "etui", "protection", "verre trempé", "film",
    "boîte vide", "boite vide", "carton vide", "facture seule", "pour pièces",
    "pour pieces", "hs", "cassé", "casse", "défectueux", "defectueux",
    "en panne", "bloqué icloud", "icloud", "réplique", "replique", "copie",
    "faux", "fake", "recherche", "échange", "echange", "location",
]


@dataclass
class Watch:
    """Ce qu'on surveille : une recherche + les règles pour juger une affaire."""

    name: str
    query: str
    sources: list[str]
    must_include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    min_price: float | None = None
    max_price: float | None = None
    # Prix de référence fixé à la main (ex. prix neuf). Utilisé si l'historique
    # ne contient pas encore assez d'annonces pour estimer le marché.
    reference_price: float | None = None
    deal_discount: float = 0.30  # alerte dès -30 % sous le marché
    error_discount: float = 0.60  # -60 % ou plus = erreur de prix probable
    urls: list[str] = field(default_factory=list)  # pour la source "sites"


@dataclass
class Site:
    """Une boutique scannée en entier par le mode catalogue."""

    name: str
    domain: str
    category: str = ""
    kind: str = "enseigne"  # "enseigne" ou "marketplace"
    sellers: list[str] = field(default_factory=list)  # vendeurs acceptés (marketplace)
    path_prefix: str = ""
    start_urls: list[str] = field(default_factory=list)
    enabled: bool = True
    note: str = ""


@dataclass
class Catalog:
    enabled: bool = True
    pages_per_site: int = 150  # pages lues par site et par passe
    workers: int = 8  # sites scannés en parallèle (un seul flux par site)
    min_price: float = 15.0  # ignore les petits articles (trop de bruit)
    deal_discount: float = 0.35  # vs le même produit (EAN) sur les autres sites
    error_discount: float = 0.60
    min_other_sites: int = 2  # nb de sites concurrents mini pour comparer
    sites: list[Site] = field(default_factory=list)


@dataclass
class Trust:
    """Seuils pour ne garder que les vendeurs professionnels fiables sur eBay."""

    ebay_min_feedback_percent: float = 98.0
    ebay_min_feedback_score: int = 100


@dataclass
class Settings:
    interval_minutes: int = 15
    database: str = "dealbot.sqlite3"
    market_window_days: int = 30
    min_samples: int = 8
    price_drop_alert: float = 0.30  # baisse soudaine d'un même article
    currency: str = "EUR"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_marketplace: str = "EBAY_FR"
    watches: list[Watch] = field(default_factory=list)
    catalog: Catalog = field(default_factory=Catalog)
    trust: Trust = field(default_factory=Trust)


SITES_FILE = Path(__file__).parent / "data" / "sites.toml"


def load_sites(path: str | Path = SITES_FILE) -> list[Site]:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return [Site(**{k: v for k, v in s.items() if k in Site.__dataclass_fields__})
            for s in raw.get("site", [])]


def _env_or(value: str, env: str) -> str:
    return os.environ.get(env, "") or value


def load(path: str | Path) -> Settings:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    general = raw.get("general", {})
    telegram = raw.get("telegram", {})
    ebay = raw.get("ebay", {})

    s = Settings(
        interval_minutes=int(general.get("interval_minutes", 15)),
        database=general.get("database", "dealbot.sqlite3"),
        market_window_days=int(general.get("market_window_days", 30)),
        min_samples=int(general.get("min_samples", 8)),
        price_drop_alert=float(general.get("price_drop_alert", 0.30)),
        currency=general.get("currency", "EUR"),
        # Les secrets peuvent venir des variables d'environnement pour ne
        # jamais les écrire dans un fichier versionné.
        telegram_token=_env_or(telegram.get("token", ""), "DEALBOT_TELEGRAM_TOKEN"),
        telegram_chat_id=_env_or(str(telegram.get("chat_id", "")), "DEALBOT_TELEGRAM_CHAT_ID"),
        ebay_client_id=_env_or(ebay.get("client_id", ""), "DEALBOT_EBAY_CLIENT_ID"),
        ebay_client_secret=_env_or(ebay.get("client_secret", ""), "DEALBOT_EBAY_CLIENT_SECRET"),
        ebay_marketplace=ebay.get("marketplace", "EBAY_FR"),
    )

    cat = raw.get("catalog", {})
    s.catalog = Catalog(
        enabled=bool(cat.get("enabled", True)),
        pages_per_site=int(cat.get("pages_per_site", 150)),
        workers=int(cat.get("workers", 8)),
        min_price=float(cat.get("min_price", 15.0)),
        deal_discount=float(cat.get("deal_discount", 0.35)),
        error_discount=float(cat.get("error_discount", 0.60)),
        min_other_sites=int(cat.get("min_other_sites", 2)),
    )
    disabled = {d.lower().removeprefix("www.") for d in cat.get("disabled_sites", [])}
    enabled_extra = {d.lower().removeprefix("www.") for d in cat.get("enable_sites", [])}
    sites = load_sites(cat.get("sites_file", SITES_FILE))
    sites += [Site(**x) for x in cat.get("site", [])]  # sites perso ajoutés dans config.toml
    for site in sites:
        bare = site.domain.lower().removeprefix("www.")
        if bare in enabled_extra:
            site.enabled = True
        if bare in disabled:
            site.enabled = False
    s.catalog.sites = [site for site in sites if site.enabled]

    t = raw.get("trust", {})
    s.trust = Trust(**{k: t[k] for k in Trust.__dataclass_fields__ if k in t})

    for w in raw.get("watch", []):
        exclude = list(w.get("exclude", []))
        if w.get("default_exclude", True):
            exclude += DEFAULT_EXCLUDE
        s.watches.append(
            Watch(
                name=w["name"],
                query=w.get("query", w["name"]),
                sources=list(w.get("sources", ["ebay"])),
                must_include=[m.lower() for m in w.get("must_include", [])],
                exclude=[e.lower() for e in exclude],
                min_price=w.get("min_price"),
                max_price=w.get("max_price"),
                reference_price=w.get("reference_price"),
                deal_discount=float(w.get("deal_discount", 0.30)),
                error_discount=float(w.get("error_discount", 0.60)),
                urls=list(w.get("urls", [])),
            )
        )
    return s
