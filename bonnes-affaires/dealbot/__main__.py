from __future__ import annotations

import argparse
import sys

from . import config
from .notifier import TelegramNotifier
from .runner import run


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="dealbot", description="Alertes bonnes affaires / erreurs de prix")
    p.add_argument("-c", "--config", default="config.toml", help="fichier de configuration")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="scanner en continu (ou une fois avec --once)")
    r.add_argument("--once", action="store_true", help="une seule passe puis quitter")
    sub.add_parser("test-telegram", help="envoyer un message de test sur Telegram")
    args = p.parse_args(argv)

    settings = config.load(args.config)
    if args.cmd == "test-telegram":
        if not (settings.telegram_token and settings.telegram_chat_id):
            print("Renseignez [telegram] token et chat_id dans la configuration.")
            return 1
        TelegramNotifier(settings.telegram_token, settings.telegram_chat_id).send_text(
            "✅ DealBot est bien connecté : les bonnes affaires arriveront ici.")
        print("Message envoyé.")
        return 0
    run(settings, loop=not args.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
