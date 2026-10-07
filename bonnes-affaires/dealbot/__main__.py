from __future__ import annotations

import argparse
import sys

from . import config
from .notifier import TelegramNotifier
from .runner import run


def show_sites(settings) -> None:
    import time

    from .storage import Store

    store = Store(settings.database)
    rows = store.all_sites()
    now = time.time()
    print(f"{len(settings.catalog.sites)} boutiques actives\n")
    for site in settings.catalog.sites:
        r = rows.get(site.domain, {})
        if not r:
            state = "pas encore scannée"
        elif r["blocked_until"] > now:
            hours = (r["blocked_until"] - now) / 3600
            state = f"EN PAUSE {hours:.0f} h — {r['last_error']}"
        elif r["last_ok"]:
            state = f"ok ({r['mode']}, {store.page_count(site.domain)} pages connues, " \
                    f"{r['products_seen']} relevés de prix)"
        else:
            state = r["last_error"] or "aucun produit lu pour l'instant"
        vendeurs = f" [vendeurs : {', '.join(site.sellers)}]" if site.sellers else ""
        print(f"- {site.name:<30} {site.category:<26} {state}{vendeurs}")
    store.close()


def auto_chat_id(settings, config_path) -> None:
    """chat_id vide : on le récupère auprès de Telegram et on l'enregistre."""
    from .telegram_setup import find_chat_id, save_chat_id

    print("chat_id vide : recherche automatique auprès de Telegram…")
    try:
        found = find_chat_id(settings.telegram_token)
    except Exception as e:
        print(f"Impossible de joindre Telegram ({e}). Vérifiez le token et votre connexion.")
        return
    if not found:
        print("\n>>> Ouvrez votre bot dans Telegram et envoyez-lui « salut » MAINTENANT.\n"
              ">>> J'attends votre message (2 minutes maximum)…")
        try:
            for _ in range(4):  # 4 x 30 s
                found = find_chat_id(settings.telegram_token, wait=30)
                if found:
                    break
        except Exception as e:
            print(f"Impossible de joindre Telegram ({e}).")
            return
    if not found:
        print("Toujours aucun message reçu. Vérifiez que vous écrivez bien au bot dont vous "
              "avez mis le token dans config.toml, puis relancez.")
        return
    chat_id, name = found
    settings.telegram_chat_id = chat_id
    if save_chat_id(config_path, chat_id):
        print(f"chat_id trouvé ({name}) : {chat_id} — enregistré dans {config_path}.")
    else:
        print(f"chat_id trouvé : {chat_id}. Copiez-le dans config.toml (chat_id = \"{chat_id}\").")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="dealbot", description="Alertes bonnes affaires / erreurs de prix")
    p.add_argument("-c", "--config", default="config.toml", help="fichier de configuration")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="scanner en continu (ou une fois avec --once)")
    r.add_argument("--once", action="store_true", help="une seule passe puis quitter")
    r.add_argument("--catalogue-seul", action="store_true", help="seulement le scan des boutiques")
    r.add_argument("--recherches-seules", action="store_true", help="seulement les [[watch]]")
    sub.add_parser("test-telegram", help="envoyer un message de test sur Telegram")
    sub.add_parser("sites", help="liste des boutiques scannées et leur état")
    args = p.parse_args(argv)

    settings = config.load(args.config)
    if settings.telegram_token and not settings.telegram_chat_id:
        auto_chat_id(settings, args.config)
    if args.cmd == "test-telegram":
        if not settings.telegram_token:
            print("Renseignez [telegram] token dans config.toml.")
            return 1
        if not settings.telegram_chat_id:
            return 1  # le message d'explication vient d'être affiché
        TelegramNotifier(settings.telegram_token, settings.telegram_chat_id).send_text(
            "✅ DealBot est bien connecté : les bonnes affaires arriveront ici.")
        print("Message envoyé.")
        return 0
    if args.cmd == "sites":
        show_sites(settings)
        return 0
    run(settings, loop=not args.once, catalog=not args.recherches_seules,
        watches=not args.catalogue_seul)
    return 0


if __name__ == "__main__":
    sys.exit(main())
