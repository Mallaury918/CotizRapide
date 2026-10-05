"""Normalisation des annonces et détection des bonnes affaires."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

# Protection acheteurs Vinted : 0,70 € + 5 % du prix (utilisée si l'API ne donne pas le total)
PROTECTION_FIXE = 0.70
PROTECTION_TAUX = 0.05


@dataclass
class Annonce:
    id: int
    titre: str
    prix: float          # prix affiché par le vendeur
    prix_total: float    # prix + protection acheteurs
    marque: str
    taille: str
    etat: str
    url: str
    photo: str
    vendeur: str
    favoris: int


@dataclass
class Affaire:
    annonce: Annonce
    reference: float      # prix de marché estimé
    nb_comparables: int
    groupe: str           # sur quoi porte la comparaison ("Nike · Très bon état", …)
    cout_total: float     # ce que l'achat coûte réellement, livraison comprise
    remise: float         # 0.45 = 45 % sous la référence
    benefice: float       # marge estimée à la revente
    suspect: bool         # prix "trop beau pour être vrai"


def _montant(valeur) -> Optional[float]:
    if valeur is None:
        return None
    if isinstance(valeur, dict):
        valeur = valeur.get("amount")
    try:
        return float(str(valeur).replace(",", "."))
    except ValueError:
        return None


def normaliser(item: dict) -> Optional[Annonce]:
    prix = _montant(item.get("price"))
    if prix is None or prix <= 0:
        return None
    total = _montant(item.get("total_item_price"))
    if total is None or total < prix:
        total = round(prix + PROTECTION_FIXE + prix * PROTECTION_TAUX, 2)
    photo = item.get("photo") or {}
    return Annonce(
        id=int(item["id"]),
        titre=(item.get("title") or "").strip(),
        prix=prix,
        prix_total=total,
        marque=(item.get("brand_title") or "").strip(),
        taille=(item.get("size_title") or "").strip(),
        etat=(item.get("status") or "").strip(),
        url=item.get("url") or f"https://www.vinted.fr/items/{item['id']}",
        photo=photo.get("url") or "",
        vendeur=(item.get("user") or {}).get("login", ""),
        favoris=int(item.get("favourite_count") or 0),
    )


def simplifier(texte: str) -> str:
    """Minuscules sans accents, pour comparer des mots-clés de façon tolérante."""
    texte = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in texte if not unicodedata.combining(c))


def contient_mot(titre: str, mot: str) -> bool:
    return re.search(r"\b" + re.escape(simplifier(mot)) + r"\b", simplifier(titre)) is not None


def passe_filtres(a: Annonce, crit: dict) -> bool:
    if any(contient_mot(a.titre, m) for m in crit.get("mots_exclus", [])):
        return False
    if any(not contient_mot(a.titre, m) for m in crit.get("mots_requis", [])):
        return False
    if a.prix < crit.get("prix_min", 0):
        return False
    if crit.get("prix_max") and a.prix > crit["prix_max"]:
        return False
    return True


def percentile(valeurs: list, p: float) -> float:
    v = sorted(valeurs)
    k = (len(v) - 1) * p / 100
    bas = int(k)
    haut = min(bas + 1, len(v) - 1)
    return v[bas] + (v[haut] - v[bas]) * (k - bas)


def sans_extremes(valeurs: list) -> list:
    """Écarte les prix aberrants (méthode de l'écart interquartile)."""
    if len(valeurs) < 8:
        return valeurs
    q1, q3 = percentile(valeurs, 25), percentile(valeurs, 75)
    marge = 1.5 * (q3 - q1)
    return [x for x in valeurs if q1 - marge <= x <= q3 + marge]


def prix_reference(a: Annonce, historique: list, crit: dict):
    """Cherche le groupe d'annonces comparables le plus précis ayant assez d'éléments.

    `historique` : liste de (id, prix, marque, etat). Renvoie (référence, nb, groupe) ou None.
    """
    mini = crit.get("comparables_min", 15)
    autres = [h for h in historique if h[0] != a.id]
    groupes = []
    if a.marque and a.etat:
        groupes.append((f"{a.marque} · {a.etat}",
                        [h[1] for h in autres if h[2] == a.marque and h[3] == a.etat]))
    if a.marque:
        groupes.append((a.marque, [h[1] for h in autres if h[2] == a.marque]))
    groupes.append(("toute la recherche", [h[1] for h in autres]))

    for nom, prix in groupes:
        prix = sans_extremes(prix)
        if len(prix) >= mini:
            return percentile(prix, crit.get("percentile_reference", 40)), len(prix), nom
    return None


def evaluer(a: Annonce, historique: list, crit: dict) -> Optional[Affaire]:
    if not passe_filtres(a, crit):
        return None
    ref = prix_reference(a, historique, crit)
    if ref is None:
        return None
    reference, nb, groupe = ref
    cout = a.prix_total + crit.get("frais_livraison_achat", 0)
    remise = 1 - cout / reference
    revente_nette = reference * (1 - crit.get("commission_revente", 0)) - crit.get("frais_envoi_revente", 0)
    benefice = revente_nette - cout
    if remise < crit.get("remise_min", 0.35) or benefice < crit.get("benefice_min", 10):
        return None
    return Affaire(
        annonce=a, reference=reference, nb_comparables=nb, groupe=groupe,
        cout_total=round(cout, 2), remise=remise, benefice=benefice,
        suspect=a.prix < reference * crit.get("ratio_suspect", 0.2),
    )
