"""Bot de veille Vinted : repère les annonces nettement sous le prix du marché.

Usage :
    python -m vinted_bot                  # tourne en continu
    python -m vinted_bot --une-fois       # un seul passage
    python -m vinted_bot --test-notif     # envoie une alerte de test
    python -m vinted_bot --telegram-id    # affiche ton chat_id Telegram
    python -m vinted_bot --diagnostic     # vérifie la connexion à Vinted
"""

import argparse
import json
import logging
import random
import sys
import time
import tomllib

import requests

from .analyse import Affaire, Annonce, Profil, profil_depuis_api, criteres_pour, evaluer, normaliser
from .client import ErreurSite, VintedClient
from .flux import Flux
from .leboncoin import LeboncoinClient, normaliser_lbc, requete_recherche
from .notifications import Notificateur
from .stockage import Stockage
from .vendeurs import verifier_vendeur

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
    if not (any(r.get("actif", True) for r in conf["recherches"]) or conf.get("flux", {}).get("actif")
            or recherches_leboncoin(conf)):
        sys.exit("Rien à surveiller : active [flux], [leboncoin] ou des [[recherches]] dans la configuration.")
    return conf


def recherches_leboncoin(conf) -> list:
    section = conf.get("leboncoin", {})
    if not section.get("actif"):
        return []
    return [r for r in section.get("recherches", []) if r.get("actif", True)]


def criteres_leboncoin(recherche, conf) -> dict:
    """Critères globaux, puis ceux de [leboncoin], puis ceux de la recherche."""
    section = {k: v for k, v in conf.get("leboncoin", {}).items() if k != "recherches"}
    source = {**section, **recherche}
    source["mots_exclus"] = list(section.get("mots_exclus", [])) + list(recherche.get("mots_exclus", []))
    return criteres_pour(source, conf)


def traiter_recherche(recherche, conf, client, stock, notif, crit=None) -> int:
    # Nom affiché et clé en mémoire (les recherches Vinted gardent leur nom d'origine)
    nom = recherche["nom"] if client.site == "vinted" else f"Leboncoin · {recherche['nom']}"
    crit = crit or criteres_pour(recherche, conf)

    # 1) Échantillon du marché (annonces "pertinentes"), rafraîchi de temps en temps
    if stock.echantillon_a_rafraichir(nom, crit["rafraichir_reference_heures"]):
        log.info("[%s] Mise à jour des prix de référence…", nom)
        for page in range(1, crit["pages_reference"] + 1):
            annonces = client.annonces(recherche, crit, recentes=False, page=page)
            stock.enregistrer_prix(annonces, nom)
            if len(annonces) < client.par_page:
                break
        stock.echantillon_fait(nom)

    # 2) Les annonces les plus récentes
    nouvelles = client.annonces(recherche, crit, recentes=True)
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
        if aff and verifier_vendeur(aff, client, stock, crit):
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
    except ErreurSite as e:
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


def passage_leboncoin(conf, client, stock, notif):
    for recherche in recherches_leboncoin(conf):
        sans_planter(f"Leboncoin · {recherche['nom']}", traiter_recherche, recherche, conf, client,
                     stock, notif, criteres_leboncoin(recherche, conf))
    stock.valider()


def passage_flux(flux, client, stock, notif):
    sans_planter("Flux", flux.passage, client, stock, notif)
    stock.nettoyer_flux(flux.jours)
    stock.valider()


def boucle(conf, client, stock, notif, flux, lbc=None):
    """Fait tourner les recherches, le flux global et Leboncoin, chacun à son rythme."""
    taches = []
    if any(r.get("actif", True) for r in conf["recherches"]):
        intervalle = conf.get("general", {}).get("intervalle_minutes", 5) * 60
        taches.append([0.0, intervalle, lambda: passage_recherches(conf, client, stock, notif)])
    if flux.actif:
        taches.append([0.0, flux.intervalle, lambda: passage_flux(flux, client, stock, notif)])
    if lbc:
        intervalle = conf["leboncoin"].get("intervalle_minutes", 10) * 60
        taches.append([0.0, intervalle, lambda: passage_leboncoin(conf, lbc, stock, notif)])
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
                          cout_total=30.45, remise=0.565, benefice=39.55, suspect=False,
                          profil=Profil(ventes=48, avis=31, note=4.9)), "Test")


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


def diagnostic(client):
    """Teste chaque étape de la connexion à Vinted et garde la réponse brute dans un fichier."""
    rapport = {}

    def etape(nom, fonction):
        try:
            resultat = fonction()
            print(f"✅ {nom}")
            return resultat
        except Exception as e:
            print(f"❌ {nom} : {e}")
            rapport[nom] = str(e)
            return None

    if etape("Connexion au site", client._nouvelle_session) is None and client.session is None:
        return
    print(f"   cookies reçus : {', '.join(sorted(client.session.cookies.keys()))}")
    print(f"   identifiant anonyme : {'oui' if 'X-Anon-Id' in client.entetes_api else 'non'}"
          f" · jeton CSRF : {'oui' if 'X-Csrf-Token' in client.entetes_api else 'non'}")
    brut = etape("Lecture des nouvelles annonces", lambda: client.requete(
        client.api + "/svc-catalogue/items",
        {"order": "newest_first", "page": 1, "per_page": 5, "currency": "EUR", "time": int(time.time())}))
    if brut:
        rapport["catalogue"] = brut
        items = brut.get("items") or (brut.get("data") or {}).get("items") or []
        print(f"   clés de la réponse : {', '.join(brut.keys())} · {len(items)} annonce(s)")
        if items:
            print(f"   champs d'une annonce : {', '.join(items[0].keys())}")
            a = normaliser(items[0])
            print(f"   lue comme : {a}")
            if a and a.vendeur_id:
                user = etape("Lecture d'un profil vendeur", lambda: client.utilisateur(a.vendeur_id))
                if user:
                    rapport["profil"] = {k: user.get(k) for k in (
                        "given_item_count", "feedback_count", "feedback_reputation",
                        "positive_feedback_count", "item_count")}
                    print(f"   champs du profil : {', '.join(list(user.keys())[:40])}")
                    print(f"   lu comme : {profil_depuis_api(user)}")
    with open("diagnostic.json", "w", encoding="utf-8") as f:
        json.dump(rapport, f, ensure_ascii=False, indent=2)
    print("\nRésultat complet enregistré dans diagnostic.json")


def diagnostic_leboncoin(lbc):
    """Même test que pour Vinted : recherche « switch » avec livraison, puis un profil."""
    print("\n── Leboncoin ──")
    rapport = {}
    try:
        lbc._nouvelle_session()
        print(f"✅ Connexion au site · cookies : {', '.join(sorted(lbc.session.cookies.keys()))}")
        brut = lbc.requete("POST", "https://api.leboncoin.fr/finder/search", requete_recherche(
            {"mots_cles": "switch"}, {}, recentes=True, page=1, par_page=5, livraison=True))
        ads = brut.get("ads") or []
        rapport["recherche"] = brut
        print(f"✅ Lecture des annonces · clés : {', '.join(brut.keys())} · {len(ads)} annonce(s)")
        if ads:
            print(f"   champs d'une annonce : {', '.join(ads[0].keys())}")
            print(f"   attributs : {', '.join(a.get('key', '?') for a in ads[0].get('attributes') or [])}")
            a = normaliser_lbc(ads[0])
            print(f"   lue comme : {a}")
            if a and a.vendeur_id:
                print(f"✅ Lecture d'un profil vendeur · lu comme : {lbc.profil(a.vendeur_id)}")
    except Exception as e:
        print(f"❌ {e}")
        rapport["erreur"] = str(e)
    with open("diagnostic_leboncoin.json", "w", encoding="utf-8") as f:
        json.dump(rapport, f, ensure_ascii=False, indent=2)
    print("Résultat complet enregistré dans diagnostic_leboncoin.json")


def main():
    p = argparse.ArgumentParser(description="Veille des bonnes affaires Vinted")
    p.add_argument("-c", "--config", default="config.toml")
    p.add_argument("--une-fois", action="store_true", help="un seul passage puis quitter")
    p.add_argument("--test-notif", action="store_true", help="envoyer une alerte de test")
    p.add_argument("--telegram-id", action="store_true", help="trouver son chat_id Telegram")
    p.add_argument("--diagnostic", action="store_true", help="vérifier la connexion à Vinted")
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
    lbc = None
    if recherches_leboncoin(conf) or (args.diagnostic and conf.get("leboncoin", {}).get("actif")):
        try:
            lbc = LeboncoinClient(tuple(conf["leboncoin"].get("pause_entre_requetes", [4, 9])),
                                  conf["leboncoin"].get("livraison_uniquement", True))
        except ErreurSite as e:
            log.error("[Leboncoin] %s", e)
    if args.diagnostic:
        diagnostic(client)
        if lbc:
            diagnostic_leboncoin(lbc)
        return
    stock = Stockage(g.get("base_de_donnees", "vinted_bot.db"))

    flux = Flux(conf)

    if args.une_fois:
        passage_recherches(conf, client, stock, notif)
        if flux.actif:
            passage_flux(flux, client, stock, notif)
        if lbc:
            passage_leboncoin(conf, lbc, stock, notif)
        return

    actives = sum(r.get("actif", True) for r in conf["recherches"])
    log.info("Bot démarré : %s%d recherche(s) Vinted ciblée(s)%s. Ctrl+C pour arrêter.",
             f"tout Vinted toutes les {flux.intervalle} s + " if flux.actif else "", actives,
             f" + {len(recherches_leboncoin(conf))} recherche(s) Leboncoin" if lbc else "")
    if flux.actif and stock.taille_flux() < 5000:
        log.info("[Flux] Les premières heures, le bot apprend les prix du marché : "
                 "les alertes arriveront au fur et à mesure.")
    try:
        boucle(conf, client, stock, notif, flux, lbc)
    except KeyboardInterrupt:
        log.info("Arrêt demandé, à bientôt !")


if __name__ == "__main__":
    main()
