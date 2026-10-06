from __future__ import annotations

import html
import json

from .http import Session
from .models import Deal

LABELS = {
    "erreur_prix": "🚨 ERREUR DE PRIX PROBABLE",
    "sous_marche": "💰 Sous le prix du marché",
    "baisse_prix": "📉 Grosse baisse de prix",
}


def format_deal(d: Deal, rich: bool = True) -> str:
    l = d.listing
    esc = html.escape if rich else (lambda s: s)
    lines = [
        f"<b>{LABELS[d.kind]}</b>" if rich else LABELS[d.kind],
        f"{esc(l.title)}",
        f"Prix : {l.total:.2f} {l.currency}"
        + (f" (dont {l.shipping:.2f} de port)" if l.shipping else ""),
        f"{esc(d.reason)}",
        f"Source : {esc(l.source)} · Recherche : {esc(d.watch)}",
    ]
    if l.condition:
        lines.append(f"État : {esc(l.condition)}")
    if l.seller:
        detail = []
        if l.seller_rating is not None:
            detail.append(f"{l.seller_rating:.1f}/5")
        if l.seller_reviews is not None:
            detail.append(f"{l.seller_reviews} avis")
        lines.append(f"Vendeur : {esc(l.seller)}" + (f" ({', '.join(detail)})" if detail else "")
                     + (" ✅" if l.seller_checked or detail else ""))
    lines += [f"⚠️ {esc(w)}" for w in d.warnings]
    lines.append(f'<a href="{esc(l.url)}">Voir l\'annonce</a>' if rich else l.url)
    return "\n".join(lines)


class ConsoleNotifier:
    def send(self, deal: Deal) -> None:
        print("\n" + format_deal(deal, rich=False) + "\n" + "-" * 60, flush=True)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, session: Session | None = None):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.session = session or Session(min_delay=1.1)  # limite Telegram ~1 msg/s

    def send_text(self, text: str) -> None:
        self.session.request(
            self.url,
            data=json.dumps({"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                             "disable_web_page_preview": False}).encode(),
            headers={"Content-Type": "application/json"},
        )

    def send(self, deal: Deal) -> None:
        self.send_text(format_deal(deal))
