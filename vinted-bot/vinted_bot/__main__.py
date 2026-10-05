"""Bot de veille Vinted : repère les annonces nettement sous le prix du marché.

Usage :
    python -m vinted_bot                  # tourne en continu
    python -m vinted_bot --une-fois       # un seul passage
    python -m vinted_bot --test-notif     # envoie une alerte de test
    python -m vinted_bot --telegram-id    # affiche ton chat_id Telegram
"""

import argparse
import logging
import random
import sys
import time
import tomllib

import requests

from .analyse import Affaire, Annonce, evaluer, normaliser
from .client import VintedClient, VintedErreur, params_depuis_url
from .notifications import Notificateur
from .stockage import Stockage

log = logging.getLogger("vinted_bot")

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
}


def charger_config(chemin):
    try:
        with open(chemin, "rb") as f:
            conf = tomllib.load(f)
    except FileNotFoundError:
        sys.exit(f"Fichier de configuration introuvable : {chemin}\n"
                 "Copie config.exemple.toml en config.toml puis adapte-le.")
    except tomllib.TOMLDecodeError as e:
        sys.exit(f"Erreur dans {chemin} : {e}")
    if not conf.get("recherches"):
        sys.exit("Aucune [[recherches]] dans la configuration.")
    return conf


def criteres_pour(recherche: dict, conf: dict) -> dict:
    crit = {**CRITERES_DEFAUT, **conf.get("criteres", {})}
    for cle in CRITERES_DEFAUT:
        if cle in recherche:
            crit[cle] = recherche[cle]
    # Les mots exclus globaux s'ajoutent à ceux de la recherche
    crit["mots_exclus"] = list(conf.get("criteres", {}).get("mots_exclus", [])) + list(
        recherche.get("mots_exclus", []))
    return crit


def params_pour(recherche: dict, crit: dict) -> dict:
    params = params_depuis_url(recherche["url"]) if recherche.get("url") else {}
    if recherche.get("mots_cles"):
        params["search_text"] = recherche["mots_cles"]
    if crit["prix_min"]:
        params["price_from"] = crit["prix_min"]
    if crit["prix_max"]:
        params["price_to"] = crit["prix_max"]
    params.setdefault("currency", "EUR")
    return params


def traiter_recherche(recherche, conf, client, stock, notif) -> int:
    nom = recherche["nom"]
    crit = criteres_pour(recherche, conf)
    params = params_pour(recherche, crit)

    # 1) Échantillon du marché (annonces "pertinentes"), rafraîchi de temps en temps
    if stock.echantillon_a_rafraichir(nom, crit["rafraichir_reference_heures"]):
        log.info("[%s] Mise à jour des prix de référence…", nom)
        for page in range(1, crit["pages_reference"] + 1):
            items = client.rechercher(params, ordre="relevance", page=page)
            stock.enregistrer_prix([a for a in map(normaliser, items) if a], nom)
            if len(items) < 96:
                break
        stock.echantillon_fait(nom)

    # 2) Les annonces les plus récentes
    nouvelles = [a for a in map(normaliser, client.rechercher(params, ordre="newest_first")) if a]
    stock.enregistrer_prix(nouvelles, nom)
    historique = stock.historique(nom, conf.get("general", {}).get("historique_jours", 30))

    # Premier passage : on mémorise tout sans alerter, sinon on recevrait 96 vieilles annonces
    premier_passage = not stock.connait_recherche(nom)
    trouvees = 0
    for a in nouvelles:
        if stock.deja_vue(a.id, nom):
            continue
        stock.marquer_vue(a.id, nom)
        if premier_passage:
            continue
        aff = evaluer(a, historique, crit)
        if aff:
            notif.envoyer(aff, nom)
            stock.noter_affaire(aff, nom)
            trouvees += 1
    stock.valider()
    if premier_passage:
        log.info("[%s] Initialisation : %d annonces mémorisées, %d prix en référence.",
                 nom, len(nouvelles), len(historique))
    else:
        log.info("[%s] %d prix en référence, %d bonne(s) affaire(s).", nom, len(historique), trouvees)
    return trouvees


def un_passage(conf, client, stock, notif):
    for recherche in conf["recherches"]:
        if not recherche.get("actif", True):
            continue
        try:
            traiter_recherche(recherche, conf, client, stock, notif)
        except VintedErreur as e:
            log.error("[%s] %s", recherche["nom"], e)
        except (requests.RequestException, OSError, ValueError) as e:
            log.error("[%s] Erreur réseau : %s", recherche["nom"], e)
        except Exception:  # le bot tourne en continu : on journalise et on passe à la suite
            log.exception("[%s] Erreur inattendue", recherche["nom"])
    stock.nettoyer(conf.get("general", {}).get("historique_jours", 30))
    stock.valider()


def test_notif(notif):
    a = Annonce(id=0, titre="Nike Dunk Low Panda (TEST)", prix=25.0, prix_total=26.95,
                marque="Nike", taille="42", etat="Très bon état",
                url="https://www.vinted.fr/", photo="", vendeur="test", favoris=3)
    notif.envoyer(Affaire(annonce=a, reference=70.0, nb_comparables=54, groupe="Nike · Très bon état",
                          cout_total=30.45, remise=0.565, benefice=39.55, suspect=False), "Test")


def telegram_id(conf):
    token = conf.get("notifications", {}).get("telegram_token", "")
    if not token:
        sys.exit("Renseigne d'abord telegram_token dans config.toml.")
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15).json()
    chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name", "")
             for u in r.get("result", []) if "message" in u}
    if not chats:
        print("Aucun message reçu : envoie un message à ton bot sur Telegram, puis relance.")
    for cid, nom in chats.items():
        print(f"telegram_chat_id = \"{cid}\"   ({nom})")


def main():
    p = argparse.ArgumentParser(description="Veille des bonnes affaires Vinted")
    p.add_argument("-c", "--config", default="config.toml")
    p.add_argument("--une-fois", action="store_true", help="un seul passage puis quitter")
    p.add_argument("--test-notif", action="store_true", help="envoyer une alerte de test")
    p.add_argument("--telegram-id", action="store_true", help="trouver son chat_id Telegram")
    p.add_argument("-v", "--verbeux", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbeux else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    conf = charger_config(args.config)
    notif = Notificateur(conf.get("notifications", {}))

    if args.telegram_id:
        return telegram_id(conf)
    if args.test_notif:
        return test_notif(notif)

    g = conf.get("general", {})
    client = VintedClient(g.get("domaine", "www.vinted.fr"), tuple(g.get("pause_entre_requetes", [2, 5])))
    stock = Stockage(g.get("base_de_donnees", "vinted_bot.db"))

    if args.une_fois:
        return un_passage(conf, client, stock, notif)

    intervalle = g.get("intervalle_minutes", 5) * 60
    log.info("Bot démarré : %d recherche(s), passage toutes les %d min. Ctrl+C pour arrêter.",
             len(conf["recherches"]), intervalle // 60)
    try:
        while True:
            un_passage(conf, client, stock, notif)
            time.sleep(intervalle * random.uniform(0.85, 1.15))
    except KeyboardInterrupt:
        log.info("Arrêt demandé, à bientôt !")


if __name__ == "__main__":
    main()
