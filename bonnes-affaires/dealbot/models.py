from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Listing:
    """Une annonce / un produit trouvé sur une source."""

    source: str  # "ebay", "vinted", "site:fnac.com"...
    item_id: str  # identifiant unique dans la source
    title: str
    price: float  # prix de l'article
    currency: str
    url: str
    shipping: float = 0.0  # frais de port connus (0 si inconnus)
    condition: str = ""  # "neuf", "très bon état"...
    image: str = ""

    @property
    def total(self) -> float:
        return round(self.price + self.shipping, 2)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.item_id}"


@dataclass
class Deal:
    """Une annonce jugée intéressante, prête à être envoyée."""

    listing: Listing
    watch: str
    kind: str  # "erreur_prix", "sous_marche", "baisse_prix"
    reference: float  # prix de référence utilisé pour la comparaison
    discount: float  # 0.35 = 35 % moins cher que la référence
    reason: str
    warnings: list[str] = field(default_factory=list)
