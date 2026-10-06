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
    vinted_domain: str = "www.vinted.fr"
    watches: list[Watch] = field(default_factory=list)


def _env_or(value: str, env: str) -> str:
    return os.environ.get(env, "") or value


def load(path: str | Path) -> Settings:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    general = raw.get("general", {})
    telegram = raw.get("telegram", {})
    ebay = raw.get("ebay", {})
    vinted = raw.get("vinted", {})

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
        vinted_domain=vinted.get("domain", "www.vinted.fr"),
    )

    for w in raw.get("watch", []):
        exclude = list(w.get("exclude", []))
        if w.get("default_exclude", True):
            exclude += DEFAULT_EXCLUDE
        s.watches.append(
            Watch(
                name=w["name"],
                query=w.get("query", w["name"]),
                sources=list(w.get("sources", ["ebay", "vinted"])),
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
