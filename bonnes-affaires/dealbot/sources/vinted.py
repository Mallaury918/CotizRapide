from __future__ import annotations

from ..config import Watch
from ..http import HttpError, Session
from ..models import Listing
from .base import Source


class VintedSource(Source):
    """Catalogue public de Vinted (API non officielle utilisée par le site lui-même).

    Vinted n'offre pas d'API publique : ce format peut changer sans préavis.
    """

    name = "vinted"

    def __init__(self, session: Session, domain: str = "www.vinted.fr"):
        self.session = session
        self.base = f"https://{domain}"
        self._has_cookie = False

    def _warmup(self) -> None:
        # La page d'accueil dépose le cookie de session exigé par l'API.
        self.session.request(self.base + "/")
        self._has_cookie = True

    def search(self, watch: Watch) -> list[Listing]:
        params = {"search_text": watch.query, "order": "newest_first", "per_page": 96, "page": 1}
        if watch.min_price is not None:
            params["price_from"] = watch.min_price
        if watch.max_price is not None:
            params["price_to"] = watch.max_price
        if not self._has_cookie:
            self._warmup()
        try:
            data = self.session.get_json(self.base + "/api/v2/catalog/items", params=params)
        except HttpError as e:
            if e.status != 401:
                raise
            self._warmup()  # cookie expiré : on le renouvelle une fois
            data = self.session.get_json(self.base + "/api/v2/catalog/items", params=params)
        return [l for l in (parse_item(i, self.base) for i in data.get("items", [])) if l]

    def verify_seller(self, listing: Listing) -> None:
        # Le catalogue ne donne pas la note : on ne la demande que pour les
        # annonces qui vont déclencher une alerte (quelques requêtes par passe).
        if not listing.seller_id or listing.seller_rating is not None:
            return
        try:
            user = self.session.get_json(f"{self.base}/api/v2/users/{listing.seller_id}")["user"]
        except Exception as e:
            print(f"[vinted] note du vendeur {listing.seller_id} indisponible : {e}")
            return
        apply_user(listing, user)


def apply_user(listing: Listing, user: dict) -> None:
    reputation = user.get("feedback_reputation")
    if reputation is not None:
        listing.seller_rating = round(float(reputation) * 5, 2)  # 0..1 -> 0..5
    count = user.get("feedback_count")
    if count is not None:
        listing.seller_reviews = int(count)
    listing.seller = user.get("login", listing.seller)


def _amount(value) -> tuple[float, str] | None:
    """Vinted renvoie le prix soit en texte ("12.0"), soit en objet {amount, currency_code}."""
    if isinstance(value, dict):
        try:
            return float(value["amount"]), value.get("currency_code", "EUR")
        except (KeyError, TypeError, ValueError):
            return None
    try:
        return float(value), "EUR"
    except (TypeError, ValueError):
        return None


def parse_item(item: dict, base: str = "https://www.vinted.fr") -> Listing | None:
    parsed = _amount(item.get("price"))
    if not parsed:
        return None
    price, currency = parsed
    if isinstance(item.get("price"), str) and item.get("currency"):
        currency = item["currency"]
    photo = item.get("photo") or {}
    user = item.get("user") or {}
    url = item.get("url") or f"{base}/items/{item['id']}"
    if url.startswith("/"):
        url = base + url
    return Listing(
        source="vinted",
        item_id=str(item["id"]),
        title=" ".join(filter(None, [item.get("title", ""), item.get("brand_title", "")])),
        price=price,
        currency=currency,
        url=url,
        condition=item.get("status", ""),
        image=photo.get("url", ""),
        seller=user.get("login", ""),
        seller_id=str(user.get("id", "")),
    )
