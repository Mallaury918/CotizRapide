"""Vérification du vendeur avant d'envoyer une alerte."""

import logging

from .analyse import Profil, vendeur_fiable

log = logging.getLogger(__name__)


def verifier_vendeur(aff, client, stock, crit) -> bool:
    """Complète `aff.profil` et dit si le vendeur respecte les critères (ventes, avis, note).

    Le profil n'est demandé au site que pour les bonnes affaires, puis gardé 24 h en mémoire.
    """
    if not any(crit.get(c) for c in ("vendeur_ventes_min", "vendeur_avis_min", "vendeur_note_min")):
        return True
    a = aff.annonce
    if not a.vendeur_id:
        log.info("Vendeur inconnu, affaire ignorée : %s", a.url)
        return False
    cle = f"{client.site}:{a.vendeur_id}"
    ligne = stock.profil_en_cache(cle)
    if ligne:
        profil = Profil(*ligne)
    else:
        try:
            profil = client.profil(a.vendeur_id)
        except Exception as e:  # sans profil vérifiable, on n'alerte pas
            log.warning("Profil de %s illisible (%s), affaire ignorée : %s", a.vendeur, e, a.url)
            return False
        stock.memoriser_profil(cle, profil)
    aff.profil = profil
    if vendeur_fiable(profil, crit):
        return True
    log.info("Vendeur écarté (%d vente(s), %d avis, note %.1f) : %s",
             profil.ventes, profil.avis, profil.note, a.url)
    return False
