from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import Watch
from ..models import Listing


class Source(ABC):
    name: str

    @abstractmethod
    def search(self, watch: Watch) -> list[Listing]:
        """Renvoie les annonces/produits correspondant à la surveillance."""
