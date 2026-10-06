from __future__ import annotations

from .config import Trust
from .models import Listing


def untrusted_reason(listing: Listing, trust: Trust) -> str | None:
    """Pourquoi ce vendeur n'est pas jugé fiable (None = fiable ou non concerné).

    eBay : uniquement des vendeurs professionnels, avec une note ET un nombre
    d'avis suffisants. Un vendeur dont on ne connaît pas le statut ou la note
    est refusé.
    """
    if listing.source == "ebay":
        if listing.seller_pro is not True:
            return ("vendeur eBay particulier" if listing.seller_pro is False
                    else "statut du vendeur eBay inconnu (pro ou particulier)")
        if listing.seller_rating is None or listing.seller_reviews is None:
            return "vendeur eBay sans évaluations connues"
        percent = listing.seller_rating * 20
        if percent < trust.ebay_min_feedback_percent:
            return f"vendeur eBay à {percent:.1f} % d'avis positifs"
        if listing.seller_reviews < trust.ebay_min_feedback_score:
            return f"vendeur eBay avec seulement {listing.seller_reviews} évaluations"
    return None
