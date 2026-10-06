from __future__ import annotations

import base64
import time

from ..config import Watch
from ..http import Session
from ..models import Listing
from .base import Source

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


class EbaySource(Source):
    """API officielle eBay « Browse » (clé gratuite sur developer.ebay.com)."""

    name = "ebay"

    def __init__(self, session: Session, client_id: str, client_secret: str,
                 marketplace: str = "EBAY_FR"):
        self.session = session
        self.basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self.marketplace = marketplace
        self._token = ""
        self._expires = 0.0

    def _auth(self) -> str:
        if time.time() < self._expires - 60:
            return self._token
        data = self.session.get_json(
            TOKEN_URL,
            headers={"Authorization": f"Basic {self.basic}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials",
                  "scope": "https://api.ebay.com/oauth/api_scope"},
        )
        self._token = data["access_token"]
        self._expires = time.time() + int(data.get("expires_in", 7200))
        return self._token

    def search(self, watch: Watch) -> list[Listing]:
        # Achat immédiat uniquement : le prix d'une enchère en cours ne veut rien dire.
        filters = ["buyingOptions:{FIXED_PRICE}"]
        if watch.min_price is not None or watch.max_price is not None:
            lo = watch.min_price if watch.min_price is not None else ""
            hi = watch.max_price if watch.max_price is not None else ""
            filters += [f"price:[{lo}..{hi}]", "priceCurrency:EUR"]
        data = self.session.get_json(
            SEARCH_URL,
            params={"q": watch.query, "limit": 200, "sort": "newlyListed",
                    "filter": ",".join(filters)},
            headers={"Authorization": f"Bearer {self._auth()}",
                     "X-EBAY-C-MARKETPLACE-ID": self.marketplace},
        )
        return [l for l in map(parse_item, data.get("itemSummaries", [])) if l]


def parse_item(item: dict) -> Listing | None:
    price = item.get("price") or {}
    try:
        value = float(price["value"])
    except (KeyError, TypeError, ValueError):
        return None
    shipping = 0.0
    for opt in item.get("shippingOptions") or []:
        cost = (opt.get("shippingCost") or {}).get("value")
        if cost is not None:
            shipping = float(cost)
            break
    return Listing(
        source="ebay",
        item_id=item["itemId"],
        title=item.get("title", ""),
        price=value,
        currency=price.get("currency", "EUR"),
        url=item.get("itemWebUrl", ""),
        shipping=shipping,
        condition=item.get("condition", ""),
        image=(item.get("image") or {}).get("imageUrl", ""),
    )
