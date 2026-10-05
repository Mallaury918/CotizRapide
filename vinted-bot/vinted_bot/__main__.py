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

from .analyse import Affaire, Annonce, criteres_pour, evaluer, normaliser
from .client import VintedClient, VintedErreur, params_depuis_url
from .flux import Flux
from .notifications import Notificateur
from .stockage import Stockage

log = logging.getLogger("vinted_bot")


def charger_config(chemin):
    try:
        with open(chemin, "rb") as f:
            conf = tomllib.load(f)
    except FileNotFoundError:
        sys.exit(f"Fichier de configuration introuvable : {chemin}\n"
                 "Copie config.exemple.toml en config.toml puis adapte-le.")
    except tomllib.TOMLDecodeError as e:
        sys.exit(f"Erreur dans {chemin} : {e}")
    conf.setdefault("recherches", [])
    if not any(r.get("actif", True) for r in conf["recherches"]) and not conf.get("flux", {}).get("actif"):
        sys.exit("Rien à surveiller : active [flux] ou ajoute des [[recherches]] dans la configuration.")
    return conf


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


def sans_planter(nom, fonction, *args):
    """Le bot tourne en continu : une erreur est journalisée, puis on passe à la suite."""
    try:
        fonction(*args)
    except VintedErreur as e:
        log.error("[%s] %s", nom, e)
    except (requests.RequestException, OSError, ValueError) as e:
        log.error("[%s] Erreur réseau : %s", nom, e)
    except Exception:
        log.exception("[%s] Erreur inattendue", nom)


def passage_recherches(conf, client, stock, notif):
    for recherche in conf["recherches"]:
        if recherche.get("actif", True):
            sans_planter(recherche["nom"], traiter_recherche, recherche, conf, client, stock, notif)
    stock.nettoyer(conf.get("general", {}).get("historique_jours", 30))
    stock.valider()


def passage_flux(flux, client, stock, notif):
    sans_planter("Flux", flux.passage, client, stock, notif)
    stock.nettoyer_flux(flux.jours)
    stock.valider()


def boucle(conf, client, stock, notif, flux):
    """Fait tourner les recherches et le flux global, chacun à son rythme."""
    taches = []
    if any(r.get("actif", True) for r in conf["recherches"]):
        intervalle = conf.get("general", {}).get("intervalle_minutes", 5) * 60
        taches.append([0.0, intervalle, lambda: passage_recherches(conf, client, stock, notif)])
    if flux.actif:
        taches.append([0.0, flux.intervalle, lambda: passage_flux(flux, client, stock, notif)])
    while True:
        for tache in taches:
            if time.time() >= tache[0]:
                tache[2]()
                tache[0] = time.time() + tache[1] * random.uniform(0.85, 1.15)
        time.sleep(max(1.0, min(t[0] for t in taches) - time.time()))


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

    flux = Flux(conf)

    if args.une_fois:
        passage_recherches(conf, client, stock, notif)
        if flux.actif:
            passage_flux(flux, client, stock, notif)
        return

    actives = sum(r.get("actif", True) for r in conf["recherches"])
    log.info("Bot démarré : %s%d recherche(s) ciblée(s). Ctrl+C pour arrêter.",
             f"tout Vinted toutes les {flux.intervalle} s + " if flux.actif else "", actives)
    if flux.actif and stock.taille_flux() < 5000:
        log.info("[Flux] Les premières heures, le bot apprend les prix du marché : "
                 "les alertes arriveront au fur et à mesure.")
    try:
        boucle(conf, client, stock, notif, flux)
    except KeyboardInterrupt:
        log.info("Arrêt demandé, à bientôt !")


if __name__ == "__main__":
    main()
