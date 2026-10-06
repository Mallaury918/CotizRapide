from __future__ import annotations

from ..config import Settings
from ..http import Session
from .base import Source
from .ebay import EbaySource
from .sites import SitesSource


def build_sources(settings: Settings, session: Session) -> dict[str, Source]:
    sources: dict[str, Source] = {
        "sites": SitesSource(session),
    }
    if settings.ebay_client_id and settings.ebay_client_secret:
        sources["ebay"] = EbaySource(session, settings.ebay_client_id,
                                     settings.ebay_client_secret, settings.ebay_marketplace)
    return sources
