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
    gtin: str = ""  # code-barres EAN/UPC : permet de comparer un produit entre sites
    seller: str = ""  # nom du vendeur quand la source le donne
    seller_id: str = ""
    seller_rating: float | None = None  # note du vendeur ramenée sur 5
    seller_reviews: int | None = None  # nombre d'avis du vendeur
    seller_checked: bool = False  # vendeur contrôlé (marketplace avec filtre)

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
