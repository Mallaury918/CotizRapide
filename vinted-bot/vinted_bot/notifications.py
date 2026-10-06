"""Envoi des alertes : console, Telegram et/ou Discord."""

import html
import logging
import re

import requests

log = logging.getLogger(__name__)


def euros(x: float) -> str:
    return f"{x:,.2f} €".replace(",", " ").replace(".", ",")


def note(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def resume_vendeur(nom: str, p) -> str:
    ventes = f"{p.ventes} vente(s) · " if p.ventes_connues else ""
    return f"{nom} · {ventes}⭐ {note(p.note)} ({p.avis} avis)"


def message(aff, recherche: str) -> str:
    a = aff.annonce
    lignes = [
        f"🔥 <b>-{aff.remise:.0%}</b> · {html.escape(a.titre)}",
        f"💶 <b>{euros(a.prix)}</b> (coût réel ≈ {euros(aff.cout_total)} avec protection + livraison)",
        f"📊 Prix du marché ≈ {euros(aff.reference)} "
        f"({aff.nb_comparables} annonces · {html.escape(aff.groupe)})",
        f"💰 Bénéfice estimé : <b>+{euros(aff.benefice)}</b>",
    ]
    details = " · ".join(x for x in (a.marque, a.taille and f"Taille {a.taille}", a.etat) if x)
    if details:
        lignes.append(f"🏷️ {html.escape(details)} · ❤️ {a.favoris}")
    if aff.profil:
        lignes.append(f"👤 {html.escape(resume_vendeur(a.vendeur, aff.profil))}")
    if aff.suspect:
        lignes.append("⚠️ <i>Prix anormalement bas : vérifie bien l'annonce (arnaque ? pièce manquante ?)</i>")
    lignes.append(f"🔎 {html.escape(recherche)}")
    lignes.append(f'<a href="{html.escape(a.url)}">👉 Voir l\'annonce</a>')
    return "\n".join(lignes)


class Notificateur:
    def __init__(self, conf: dict):
        self.console = conf.get("console", True)
        self.tg_token = conf.get("telegram_token", "").strip()
        self.tg_chat = str(conf.get("telegram_chat_id", "")).strip()
        self.discord = conf.get("discord_webhook", "").strip()

    def envoyer(self, aff, recherche: str):
        texte = message(aff, recherche)
        if self.console:
            print("\n" + re.sub(r"<[^>]+>", "", html.unescape(texte)) + "\n" + aff.annonce.url + "\n")
        if self.tg_token and self.tg_chat:
            self._telegram(texte, aff.annonce.photo)
        if self.discord:
            self._discord(aff, recherche)

    def texte_brut(self, texte: str):
        if self.console:
            print(texte)
        if self.tg_token and self.tg_chat:
            self._telegram(html.escape(texte), "")
        if self.discord:
            self._post(self.discord, {"content": texte})

    def _telegram(self, texte, photo):
        api = f"https://api.telegram.org/bot{self.tg_token}"
        if photo:
            ok = self._post(f"{api}/sendPhoto", {
                "chat_id": self.tg_chat, "photo": photo, "caption": texte[:1024], "parse_mode": "HTML"})
            if ok:
                return
        self._post(f"{api}/sendMessage", {
            "chat_id": self.tg_chat, "text": texte, "parse_mode": "HTML", "disable_web_page_preview": False})

    def _discord(self, aff, recherche):
        a = aff.annonce
        embed = {
            "title": f"-{aff.remise:.0%} · {a.titre}"[:256],
            "url": a.url,
            "color": 0xE67E22 if aff.suspect else 0x09B1BA,
            "fields": [
                {"name": "Prix", "value": euros(a.prix), "inline": True},
                {"name": "Marché", "value": euros(aff.reference), "inline": True},
                {"name": "Bénéfice estimé", "value": "+" + euros(aff.benefice), "inline": True},
                {"name": "Détails", "value": " · ".join(x for x in (a.marque, a.taille, a.etat) if x) or "—"},
            ],
            "footer": {"text": f"{recherche} · {aff.nb_comparables} comparables ({aff.groupe})"
                               + (" · ⚠️ prix suspect" if aff.suspect else "")},
        }
        if aff.profil:
            embed["fields"].append({"name": "Vendeur", "value": resume_vendeur(a.vendeur, aff.profil)})
        if a.photo:
            embed["thumbnail"] = {"url": a.photo}
        self._post(self.discord, {"embeds": [embed]})

    @staticmethod
    def _post(url, data) -> bool:
        try:
            r = requests.post(url, json=data, timeout=15)
            if r.ok:
                return True
            log.warning("Notification refusée (HTTP %s) : %s", r.status_code, r.text[:200])
        except requests.RequestException as e:
            log.warning("Notification impossible : %s", e)
        return False
