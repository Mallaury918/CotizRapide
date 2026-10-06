from __future__ import annotations

from .config import Trust
from .models import Listing


def untrusted_reason(listing: Listing, trust: Trust) -> str | None:
    """Pourquoi ce vendeur n'est pas jugé fiable (None = fiable ou non concerné).

    Plateformes entre particuliers / revendeurs : il faut une note ET un nombre
    d'avis suffisants. Un vendeur dont on ne connaît pas la note est refusé.
    """
    if listing.source == "ebay":
        if listing.seller_rating is None or listing.seller_reviews is None:
            return "vendeur eBay sans évaluations connues"
        percent = listing.seller_rating * 20
        if percent < trust.ebay_min_feedback_percent:
            return f"vendeur eBay à {percent:.1f} % d'avis positifs"
        if listing.seller_reviews < trust.ebay_min_feedback_score:
            return f"vendeur eBay avec seulement {listing.seller_reviews} évaluations"
    elif listing.source == "vinted":
        if listing.seller_rating is None or listing.seller_reviews is None:
            return "note du vendeur Vinted inconnue"
        if listing.seller_rating < trust.vinted_min_rating:
            return f"vendeur Vinted noté {listing.seller_rating:.1f}/5"
        if listing.seller_reviews < trust.vinted_min_reviews:
            return f"vendeur Vinted avec seulement {listing.seller_reviews} avis"
    return None
