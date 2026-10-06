# DealBot — alertes bonnes affaires & erreurs de prix

Scanne en continu des annonces et des boutiques en ligne, estime le **prix du
marché** de chaque produit surveillé, et vous envoie automatiquement sur
**Telegram** tout article :

- 💰 **sous le marché** (par défaut −30 % sous la médiane des annonces vues) ;
- 🚨 **probablement mal étiqueté** (−60 % ou plus) ;
- 📉 dont le **prix vient de chuter brutalement** (même produit, −30 % d'un coup :
  le signe typique d'une erreur de prix chez un e-commerçant).

Aucune dépendance : Python 3.11+ suffit.

## Sources

| Source   | Ce qu'elle couvre | Remarque |
|----------|-------------------|----------|
| `ebay`   | eBay (achat immédiat) | API officielle, clé gratuite sur [developer.ebay.com](https://developer.ebay.com) |
| `vinted` | Vinted | API interne du site, non officielle : peut casser si Vinted la modifie |
| `sites`  | **N'importe quel site marchand** (Fnac, Darty, Cdiscount, Boulanger, boutiques Shopify/WooCommerce/PrestaShop…) | Lit les prix publiés pour Google (schema.org). Collez des pages produit ou catégorie |

Leboncoin n'est pas inclus : le site bloque activement les robots (DataDome).

## Installation

```bash
cd bonnes-affaires
cp config.example.toml config.toml   # puis éditez config.toml
python3 -m dealbot test-telegram     # vérifie la connexion Telegram
python3 -m dealbot run --once        # une passe pour tester
python3 -m dealbot run               # en continu (toutes les 15 min par défaut)
```

### Recevoir les alertes sur Telegram

1. Sur Telegram, écrivez à **@BotFather** → `/newbot` → récupérez le *token*.
2. Envoyez un message quelconque à votre nouveau bot.
3. Ouvrez `https://api.telegram.org/bot<TOKEN>/getUpdates` : le champ
   `"chat":{"id": ...}` est votre `chat_id`.
4. Mettez les deux dans `config.toml` (ou dans les variables d'environnement
   `DEALBOT_TELEGRAM_TOKEN` / `DEALBOT_TELEGRAM_CHAT_ID`).

### Le faire tourner 24h/24

Le bot doit tourner sur une machine allumée en permanence : un Raspberry Pi,
un petit VPS (~4 €/mois), ou votre PC. Par exemple avec `cron` :

```
*/15 * * * * cd ~/bonnes-affaires && python3 -m dealbot run --once >> dealbot.log 2>&1
```

## Comment le « prix du marché » est calculé

Pour chaque surveillance, le bot garde en base (SQLite) le dernier prix de
chaque annonce vue sur les 30 derniers jours, toutes sources confondues.
Le prix du marché est la **médiane** de ces prix, après retrait des valeurs
aberrantes. Tant qu'il n'a pas vu au moins 8 annonces, il utilise le
`reference_price` que vous avez fixé (ex. le prix neuf).

La qualité des alertes dépend surtout des filtres : `must_include` (mots
obligatoires) et `exclude` (mots interdits) évitent de comparer un iPhone à une
coque d'iPhone. Une liste d'exclusions courantes (coque, HS, pour pièces,
boîte vide, réplique…) est appliquée par défaut.

## Limites à connaître

- Le bot ne scanne pas « tout Internet » d'un coup : il surveille les produits
  que vous lui listez, sur les sources configurées. C'est volontaire : sans
  produit cible, impossible de savoir ce qu'est un « bon prix ».
- Un prix très bas entre particuliers est souvent une **arnaque** : le bot
  l'indique dans l'alerte. Ne payez jamais hors plateforme.
- Respectez les conditions d'utilisation des sites ; le bot espace ses
  requêtes (1,5 s minimum) pour rester discret et poli.

## Tests

```bash
python3 -m unittest discover -s tests
```
