from __future__ import annotations

import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from .analyzer import analyze, analyze_catalog
from .catalog.crawler import Crawler, SiteResult, SiteState, source_name
from .config import Settings
from .http import Session
from .notifier import ConsoleNotifier, TelegramNotifier
from .sources import build_sources
from .storage import Store
from .trust import untrusted_reason

BLOCK_BASE = 6 * 3600  # pause après un blocage : 6 h, puis 12 h, 24 h… (max 7 jours)
BLOCK_MAX = 7 * 86400


def make_notifiers(settings: Settings) -> list:
    notifiers: list = [ConsoleNotifier()]
    if settings.telegram_token and settings.telegram_chat_id:
        notifiers.append(TelegramNotifier(settings.telegram_token, settings.telegram_chat_id))
    return notifiers


def deliver(deals, store: Store, notifiers: list) -> int:
    sent = 0
    for deal in deals:
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
    return sent


def run_watches(settings: Settings, store: Store, sources: dict, notifiers: list) -> int:
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
        trusted = []
        for deal in analyze(watch, listings, store, settings):
            verify = getattr(sources.get(deal.listing.source), "verify_seller", None)
            if verify:
                verify(deal.listing)
            reason = untrusted_reason(deal.listing, settings.trust)
            if reason:
                print(f"[{watch.name}] ignorée ({reason}) : {deal.listing.url}")
                # Mémorisée pour ne pas la réexaminer à chaque passe.
                store.mark_alerted(deal.listing.key, deal.listing.total)
            else:
                trusted.append(deal)
        sent += deliver(trusted, store, notifiers)
        store.commit()
    return sent


def _apply_site_result(store: Store, r: SiteResult, now: float) -> None:
    domain = r.site.domain
    if r.pages is not None:
        store.save_pages(domain, r.pages)
        store.update_site(domain, sitemap_at=now)
    store.mark_checked(domain, r.checked, now)
    row = store.site_row(domain)
    if r.blocked:
        failures = row["failures"] + 1
        pause = min(BLOCK_BASE * 2 ** (failures - 1), BLOCK_MAX)
        store.update_site(domain, mode=r.mode, failures=failures, blocked_until=now + pause,
                          last_error=r.error)
    else:
        fields = {"mode": r.mode, "cursor": r.cursor, "last_error": r.error or r.note}
        if r.listings:
            fields.update(failures=0, last_ok=now, products_seen=row["products_seen"] + len(r.listings))
        elif r.error:
            # Site qui ne répond pas (délai dépassé…) : pause après 3 passes en échec.
            failures = row["failures"] + 1
            fields["failures"] = failures
            if failures >= 3:
                fields["blocked_until"] = now + min(BLOCK_BASE * 2 ** (failures - 3), BLOCK_MAX)
        store.update_site(domain, **fields)


def run_catalog(settings: Settings, store: Store, notifiers: list,
                session_factory=lambda: Session(min_delay=1.5)) -> int:
    cat = settings.catalog
    if not cat.enabled or not cat.sites:
        return 0
    now = time.time()
    by_source = {source_name(s): s for s in cat.sites}
    jobs = []
    for site in cat.sites:
        row = store.site_row(site.domain)
        if row["blocked_until"] > now:
            continue
        state = SiteState(mode=row["mode"], cursor=row["cursor"], sitemap_at=row["sitemap_at"])
        to_check = store.pages_to_check(site.domain, cat.pages_per_site)
        jobs.append((Crawler(site, state, cat.pages_per_site, session_factory()), to_check))
    store.commit()

    sent = 0
    # Un thread par site : chaque site garde son propre rythme (1 requête / 1,5 s).
    with ThreadPoolExecutor(max_workers=max(1, cat.workers)) as pool:
        futures = [pool.submit(c.run, urls) for c, urls in jobs]
        for fut in as_completed(futures):
            r = fut.result()
            _apply_site_result(store, r, time.time())
            if r.blocked:
                status = f"bloqué ({r.error}), mis en pause"
            elif r.error:
                status = f"erreur ({r.error})"
                if "timed out" in r.error:
                    status = "ne répond pas (délai dépassé) — souvent un blocage des robots"
            elif not r.listings:
                status = f"aucun produit — {r.note}"
            else:
                status = "ok"
            print(f"[catalogue] {r.site.name} : {len(r.listings)} produits, "
                  f"{r.requests} pages ({r.mode or '?'}) — {status}")
            deals = analyze_catalog(r.listings, store, settings, by_source)
            sent += deliver(deals, store, notifiers)
            store.commit()
    return sent


def run(settings: Settings, loop: bool = True, catalog: bool = True, watches: bool = True) -> None:
    store = Store(settings.database)
    sources = build_sources(settings, Session())
    notifiers = make_notifiers(settings)
    try:
        while True:
            started = time.strftime("%H:%M:%S")
            n = 0
            try:
                if watches:
                    n += run_watches(settings, store, sources, notifiers)
                if catalog:
                    n += run_catalog(settings, store, notifiers)
                print(f"[{started}] passe terminée : {n} alerte(s) envoyée(s)")
            except Exception:
                traceback.print_exc()
            if not loop:
                break
            time.sleep(settings.interval_minutes * 60)
    finally:
        store.close()
