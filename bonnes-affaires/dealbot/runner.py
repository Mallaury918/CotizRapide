from __future__ import annotations

import time
import traceback

from .analyzer import analyze
from .config import Settings
from .http import Session
from .notifier import ConsoleNotifier, TelegramNotifier
from .sources import build_sources
from .storage import Store


def make_notifiers(settings: Settings) -> list:
    notifiers: list = [ConsoleNotifier()]
    if settings.telegram_token and settings.telegram_chat_id:
        notifiers.append(TelegramNotifier(settings.telegram_token, settings.telegram_chat_id))
    return notifiers


def run_once(settings: Settings, store: Store, sources: dict, notifiers: list) -> int:
    sent = 0
    for watch in settings.watches:
        listings = []
        for name in watch.sources:
            source = sources.get(name)
            if source is None:
                print(f"[{watch.name}] source « {name} » indisponible (clé API manquante ?)")
                continue
            try:
                found = source.search(watch)
                print(f"[{watch.name}] {name} : {len(found)} annonces")
                listings += found
            except Exception as e:  # une source en panne ne doit pas arrêter le bot
                print(f"[{watch.name}] {name} : erreur {e}")
        for deal in analyze(watch, listings, store, settings):
            delivered = False
            for n in notifiers:
                try:
                    n.send(deal)
                    delivered = True
                except Exception as e:
                    print(f"Envoi impossible via {type(n).__name__} : {e}")
            if delivered:
                store.mark_alerted(deal.listing.key, deal.listing.total)
                sent += 1
        store.commit()
    return sent


def run(settings: Settings, loop: bool = True) -> None:
    store = Store(settings.database)
    sources = build_sources(settings, Session())
    notifiers = make_notifiers(settings)
    try:
        while True:
            started = time.strftime("%H:%M:%S")
            try:
                n = run_once(settings, store, sources, notifiers)
                print(f"[{started}] passe terminée : {n} alerte(s) envoyée(s)")
            except Exception:
                traceback.print_exc()
            if not loop:
                break
            time.sleep(settings.interval_minutes * 60)
    finally:
        store.close()
