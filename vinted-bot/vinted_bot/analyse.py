"""Normalisation des annonces et détection des bonnes affaires."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

# Protection acheteurs Vinted : 0,70 € + 5 % du prix (utilisée si l'API ne donne pas le total)
PROTECTION_FIXE = 0.70
PROTECTION_TAUX = 0.05

CRITERES_DEFAUT = {
    "remise_min": 0.35,
    "benefice_min": 10,
    "percentile_reference": 40,
    "comparables_min": 15,
    "frais_livraison_achat": 3.5,
    "frais_envoi_revente": 0,
    "commission_revente": 0,
    "ratio_suspect": 0.2,
    "prix_min": 0,
    "prix_max": 0,
    "mots_exclus": [],
    "mots_requis": [],
    "pages_reference": 3,
    "rafraichir_reference_heures": 6,
    "vendeur_ventes_min": 5,
    "vendeur_avis_min": 1,
    "vendeur_note_min": 4,
}


def criteres_pour(source: dict, conf: dict) -> dict:
    """Critères globaux de [criteres], remplacés par ceux de `source` (une recherche ou [flux])."""
    crit = {**CRITERES_DEFAUT, **conf.get("criteres", {})}
    for cle in CRITERES_DEFAUT:
        if cle in source:
            crit[cle] = source[cle]
    # Les mots exclus globaux s'ajoutent à ceux de la source
    crit["mots_exclus"] = list(conf.get("criteres", {}).get("mots_exclus", [])) + list(
        source.get("mots_exclus", []))
    return crit


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
    catalogue: int = 0   # catégorie Vinted, si l'API la fournit
    vendeur_id: int = 0


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
    profil: Optional["Profil"] = None


@dataclass
class Profil:
    ventes: int
    avis: int
    note: float           # sur 5
    ventes_connues: bool = True   # Leboncoin n'affiche pas de nombre de ventes


def _montant(valeur) -> Optional[float]:
    if valeur is None:
        return None
    if isinstance(valeur, dict):
        valeur = valeur.get("amount")
    try:
        return float(str(valeur).replace(",", "."))
    except ValueError:
        return None


ETATS = {"neuf avec etiquette", "neuf sans etiquette", "tres bon etat", "bon etat", "satisfaisant"}


def _texte(valeur) -> str:
    if isinstance(valeur, dict):
        valeur = valeur.get("title") or valeur.get("name") or ""
    return (valeur or "").strip() if isinstance(valeur, str) else ""


def _details_item_box(item: dict):
    """Depuis 2026, marque, taille et état sont dans le bloc « item_box » :
    first_line = marque (si elle diffère du titre), second_line = « taille · état »."""
    boite = item.get("item_box") or {}
    marque = _texte(boite.get("first_line"))
    taille = etat = ""
    for morceau in _texte(boite.get("second_line")).split("·"):
        morceau = morceau.strip()
        if simplifier(morceau) in ETATS:
            etat = morceau
        elif morceau and not taille:
            taille = morceau
    return marque, taille, etat


def normaliser(item: dict) -> Optional[Annonce]:
    prix = _montant(item.get("price"))
    if prix is None or prix <= 0 or not item.get("id"):
        return None
    total = _montant(item.get("total_item_price"))
    if total is None or total < prix:
        total = round(prix + PROTECTION_FIXE + prix * PROTECTION_TAUX, 2)
    photo = item.get("photo") or (item.get("photos") or [{}])[0] or {}
    user = item.get("user") or {}
    marque_box, taille_box, etat_box = _details_item_box(item)
    url = item.get("url") or f"/items/{item['id']}"
    if url.startswith("/"):
        url = "https://www.vinted.fr" + url
    return Annonce(
        id=int(item["id"]),
        titre=(item.get("title") or "").strip(),
        prix=prix,
        prix_total=total,
        marque=_texte(item.get("brand_title")) or _texte(item.get("brand")) or marque_box,
        taille=_texte(item.get("size_title")) or taille_box,
        etat=_texte(item.get("status")) or etat_box,
        url=url,
        photo=photo.get("url") or "",
        vendeur=user.get("login", ""),
        favoris=int(item.get("favourite_count") or 0),
        catalogue=int(item.get("catalog_id") or 0),
        vendeur_id=int(user.get("id") or 0),
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


def profil_depuis_api(user: dict) -> Profil:
    return Profil(
        ventes=int(user.get("given_item_count") or 0),
        avis=int(user.get("feedback_count") or 0),
        note=round(float(user.get("feedback_reputation") or 0) * 5, 1),
    )


def vendeur_fiable(p: Profil, crit: dict) -> bool:
    if not p.ventes_connues:  # sans nombre de ventes, on exige autant d'avis
        avis_min = max(crit.get("vendeur_avis_min", 0), crit.get("vendeur_ventes_min", 0))
        return p.avis >= avis_min and p.note >= crit.get("vendeur_note_min", 0)
    return (p.ventes >= crit.get("vendeur_ventes_min", 0)
            and p.avis >= crit.get("vendeur_avis_min", 0)
            and p.note >= crit.get("vendeur_note_min", 0))
