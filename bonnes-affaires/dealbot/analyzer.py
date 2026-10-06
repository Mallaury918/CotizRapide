from __future__ import annotations

import statistics
import time

from .config import Settings, Watch
from .models import Deal, Listing
from .storage import Store
from .textutil import contains_term


def is_relevant(listing: Listing, watch: Watch) -> bool:
    """Écarte les annonces hors sujet (accessoires, pièces, mauvaise gamme de prix)."""
    title = listing.title
    if any(not contains_term(title, m) for m in watch.must_include):
        return False
    if any(contains_term(title, e) for e in watch.exclude):
        return False
    if watch.min_price is not None and listing.total < watch.min_price:
        return False
    if watch.max_price is not None and listing.total > watch.max_price:
        return False
    return listing.total > 0


def market_price(prices: list[float]) -> float | None:
    """Médiane après avoir retiré les valeurs aberrantes (méthode des quartiles).

    La médiane résiste aux annonces farfelues (1 € « pour voir », 9999 €…),
    et le filtre IQR évite qu'une poignée d'entre elles ne la tire.
    """
    if not prices:
        return None
    if len(prices) >= 4:
        q1, _, q3 = statistics.quantiles(prices, n=4)
        iqr = q3 - q1
        kept = [p for p in prices if q1 - 1.5 * iqr <= p <= q3 + 1.5 * iqr]
        prices = kept or prices
    return statistics.median(prices)


def _warnings(listing: Listing, discount: float) -> list[str]:
    w = []
    marketplace = listing.source in ("vinted", "leboncoin", "ebay")
    if marketplace and discount >= 0.6:
        w.append("Prix très bas sur une plateforme entre particuliers : méfiez-vous des "
                 "arnaques (paiement hors plateforme, vendeur sans avis).")
    if listing.shipping == 0 and listing.source == "vinted":
        w.append("Frais de port / protection acheteur Vinted non inclus.")
    return w


def analyze(watch: Watch, listings: list[Listing], store: Store, settings: Settings,
            now: float | None = None) -> list[Deal]:
    now = now or time.time()
    relevant = [l for l in listings if is_relevant(l, watch) and l.currency == settings.currency]

    # 1. Mémoriser les prix précédents AVANT d'enregistrer cette passe.
    previous = {l.key: store.previous_price(l.key) for l in relevant}
    for l in relevant:
        store.record(watch.name, l, now)

    # 2. Estimer le marché à partir de l'historique (toutes sources confondues).
    since = now - settings.market_window_days * 86400
    sample = store.market_prices(watch.name, since)
    market = market_price(sample) if len(sample) >= settings.min_samples else None
    reference = market or watch.reference_price
    ref_label = (f"médiane de {len(sample)} annonces" if market
                 else "prix de référence configuré")

    deals: list[Deal] = []
    for l in relevant:
        deal = None
        if reference:
            discount = 1 - l.total / reference
            if discount >= watch.error_discount:
                deal = Deal(l, watch.name, "erreur_prix", reference, discount,
                            f"{discount:.0%} sous le marché ({ref_label} : {reference:.2f} €)")
            elif discount >= watch.deal_discount:
                deal = Deal(l, watch.name, "sous_marche", reference, discount,
                            f"{discount:.0%} sous le marché ({ref_label} : {reference:.2f} €)")

        # 3. Baisse brutale du prix d'un même article (typique des erreurs de prix
        #    sur les sites marchands, même sans « marché » estimé).
        before = previous.get(l.key)
        if before and l.total < before:
            drop = 1 - l.total / before
            if drop >= settings.price_drop_alert and (deal is None or drop > deal.discount):
                kind = "erreur_prix" if drop >= watch.error_discount else "baisse_prix"
                deal = Deal(l, watch.name, kind, before, drop,
                            f"Prix passé de {before:.2f} € à {l.total:.2f} € (-{drop:.0%})")

        if deal and not store.already_alerted(l.key, l.total):
            deal.warnings = _warnings(l, deal.discount)
            deals.append(deal)

    deals.sort(key=lambda d: d.discount, reverse=True)
    return deals
