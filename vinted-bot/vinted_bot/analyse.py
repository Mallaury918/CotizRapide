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
    livraison: Optional[float] = None   # prix réel du port s'il est connu (Leboncoin)


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
    fourchette: tuple = ()  # (prix le plus bas, prix le plus haut) des annonces comparées


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


# Toujours écartés, quels que soient les réglages : ce ne sont jamais de vraies affaires
MOTS_EXCLUS_TOUJOURS = ["flacon vide", "flacons vides", "échantillon", "échantillons",
                        "décant", "décants", "decant", "fond de flacon"]


def passe_filtres(a: Annonce, crit: dict) -> bool:
    if any(contient_mot(a.titre, m) for m in MOTS_EXCLUS_TOUJOURS + crit.get("mots_exclus", [])):
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


def niveau_etat(etat: str) -> str:
    """Regroupe les états proches : « neuf », « occasion » (très bon / bon) ou « usé »."""
    e = simplifier(etat)
    if "neuf" in e:
        return "neuf"
    if "satisfaisant" in e or "abime" in e or "pieces" in e:
        return "usé"
    if "bon" in e:
        return "occasion"
    return ""


_TAILLE_ENFANT = re.compile(r"\b(ans|an|mois|cm)\b")


def gabarit(taille: str) -> str:
    """« enfant » ou « adulte » d'après la taille ou la pointure (« » si inconnue)."""
    t = simplifier(taille or "")
    if not t:
        return ""
    if _TAILLE_ENFANT.search(t):
        return "enfant"
    nombre = re.fullmatch(r"\s*(\d{2})(?:[.,]5)?\s*", t)
    if nombre:
        return "enfant" if int(nombre.group(1)) < 34 else "adulte"
    return "adulte"


def tailles_compatibles(ta: str, tb) -> bool:
    """Même gabarit (enfant/adulte) ; tailles chiffrées à 2 points d'écart au plus.

    `tb` vaut None pour les annonces mémorisées avant que le bot ne retienne la taille :
    on ne les compare qu'aux articles sans taille."""
    if tb is None:
        return not ta
    ga, gb = gabarit(ta), gabarit(tb)
    if ga and gb and ga != gb:
        return False
    na = re.fullmatch(r"\s*(\d{2}(?:[.,]5)?)\s*", ta or "")
    nb = re.fullmatch(r"\s*(\d{2}(?:[.,]5)?)\s*", tb or "")
    if na and nb:
        return abs(float(na.group(1).replace(",", ".")) - float(nb.group(1).replace(",", "."))) <= 2
    return True


def prix_reference(a: Annonce, historique: list, crit: dict):
    """Cherche le groupe d'annonces comparables le plus précis ayant assez d'éléments.

    `historique` : liste de (id, prix, marque, etat). On ne mélange jamais des états
    éloignés : un article usé n'est pas comparé à des articles neufs.
    Renvoie (référence, nb, groupe, (prix min, prix max)) ou None.
    """
    mini = crit.get("comparables_min", 15)
    niveau = niveau_etat(a.etat)
    autres = [h for h in historique if h[0] != a.id and niveau_etat(h[3]) == niveau]
    libelle_niveau = {"neuf": "neuf", "occasion": "bon état", "usé": "état usé"}.get(niveau, "état inconnu")
    meme_marque = [h for h in autres if h[2] == a.marque] if a.marque else []
    groupes = []
    if a.marque and a.etat:
        groupes.append((f"{a.marque} · {a.etat}", [h[1] for h in meme_marque if h[3] == a.etat]))
    if a.marque:
        groupes.append((f"{a.marque} · {libelle_niveau}", [h[1] for h in meme_marque]))
    groupes.append((libelle_niveau, [h[1] for h in autres]))

    for nom, prix in groupes:
        prix = sans_extremes(prix)
        if len(prix) >= mini:
            return (percentile(prix, crit.get("percentile_reference", 40)), len(prix), nom,
                    (min(prix), max(prix)))
    return None


def evaluer(a: Annonce, historique: list, crit: dict) -> Optional[Affaire]:
    if not passe_filtres(a, crit):
        return None
    ref = prix_reference(a, historique, crit)
    if ref is None:
        return None
    reference, nb, groupe, fourchette = ref
    port = a.livraison if a.livraison is not None else crit.get("frais_livraison_achat", 0)
    cout = a.prix_total + port
    remise = 1 - cout / reference
    revente_nette = reference * (1 - crit.get("commission_revente", 0)) - crit.get("frais_envoi_revente", 0)
    benefice = revente_nette - cout
    if remise < crit.get("remise_min", 0.35) or benefice < crit.get("benefice_min", 10):
        return None
    return Affaire(
        annonce=a, reference=reference, nb_comparables=nb, groupe=groupe,
        cout_total=round(cout, 2), remise=remise, benefice=benefice,
        suspect=a.prix < reference * crit.get("ratio_suspect", 0.2),
        fourchette=fourchette,
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
