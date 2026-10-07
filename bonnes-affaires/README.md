# DealBot — alertes bonnes affaires & erreurs de prix

Scanne en continu **tout le catalogue de ~50 enseignes fiables** et les annonces
eBay de **vendeurs professionnels bien notés** (aucun particulier), et vous envoie automatiquement sur
**Telegram** tout article :

- 💰 **sous le marché** : le même produit (même code-barres EAN) est bien moins
  cher que sur les autres sites, ou une annonce est sous la médiane du marché ;
- 🚨 **probablement mal étiqueté** (−60 % ou plus) ;
- 📉 dont le **prix vient de chuter brutalement** (le signe typique d'une erreur
  de prix chez un e-commerçant).

Aucune dépendance : Python 3.11+ suffit.

## Deux modes complémentaires

### 1. Catalogue : tous les articles, rien à configurer

Le bot parcourt **tous les produits** des boutiques listées dans
[`dealbot/data/sites.toml`](dealbot/data/sites.toml) : Fnac, Darty, Boulanger,
Cdiscount, LDLC, Materiel.net, Top Achat, Electro Dépôt, Apple (reconditionné),
Samsung, Back Market, Micromania, Auchan, Carrefour, E.Leclerc, IKEA,
Conforama, BUT, Leroy Merlin, Castorama, ManoMano, Decathlon, Intersport,
Nike, adidas, Foot Locker, Zalando, La Redoute, Sephora, Nocibé, Cultura,
King Jouet… (48 actives, `python3 -m dealbot sites` pour la liste et leur état).

**Uniquement des sites fiables** : des enseignes reconnues ou leur boutique
officielle, jamais de plateforme entre particuliers. Sur les sites qui
accueillent aussi des revendeurs tiers (Cdiscount, Fnac, Darty, Leroy Merlin…),
**seules les offres vendues par l'enseigne elle-même sont gardées**. Les
marketplaces gardées entières (Back Market, ManoMano, Zalando) sélectionnent
et contrôlent elles-mêmes leurs vendeurs professionnels.

Pour chaque site, le bot choisit tout seul la meilleure méthode :
- boutique **Shopify** ou **WooCommerce** → flux produits complet (jusqu'à 250 produits par requête) ;
- sinon → **plan du site** (sitemap), puis lecture des fiches produit
  (prix publiés pour Google, format schema.org). Les pages jamais vues
  passent en premier, puis celles modifiées récemment, puis les plus anciennes.

Il respecte le `robots.txt` de chaque site, ne fait qu'une requête toutes les
1,5 s par site, et **met en pause** (6 h, puis 12 h, 24 h…) un site qui bloque
les robots, plutôt que d'insister.

### 2. Recherches ciblées sur eBay (vendeurs pros uniquement)

Sur eBay, on définit des recherches (`[[watch]]` dans `config.toml`) : iPhone,
Switch, AirPods… Le bot compare chaque annonce à la médiane du marché.

**Les particuliers sont toujours exclus** : la recherche demande à eBay les
seuls vendeurs professionnels, et le statut est revérifié avant chaque alerte
(fiche complète de l'annonce si besoin). En plus, le vendeur pro doit avoir
**≥ 98 % d'avis positifs et ≥ 100 évaluations** (réglable dans `[trust]`).
Si le statut ou la note est inconnu, l'annonce n'est jamais envoyée.

Aucune plateforme entre particuliers n'est utilisée (ni Vinted, ni Leboncoin).

## Installation

```bash
cd bonnes-affaires
cp config.example.toml config.toml   # puis éditez config.toml
python3 -m dealbot test-telegram     # vérifie la connexion Telegram
python3 -m dealbot run --once        # une passe pour tester
python3 -m dealbot run               # en continu (toutes les 15 min par défaut)
python3 -m dealbot sites             # état de chaque boutique (ok, en pause…)
```

### Recevoir les alertes sur Telegram

1. Sur Telegram, écrivez à **@BotFather** → `/newbot` → récupérez le *token*.
2. Envoyez un message quelconque à votre nouveau bot.
3. Mettez le token dans `config.toml` (ou dans la variable d'environnement
   `DEALBOT_TELEGRAM_TOKEN`) et laissez `chat_id` vide : au lancement, le bot
   le récupère auprès de Telegram et l'enregistre dans `config.toml`.

### Le faire tourner 24h/24

Le bot doit tourner sur une machine allumée en permanence : un Raspberry Pi,
un petit VPS (~4 €/mois), ou votre PC. Lancez simplement le mode continu, qui
enchaîne les passes (une passe catalogue complète prend 20 à 30 minutes) :

```bash
nohup python3 -m dealbot run >> dealbot.log 2>&1 &
```

N'utilisez pas `cron` avec `--once` : deux passes risqueraient de se chevaucher.

## Limites à connaître

- **Certains grands sites bloquent les robots** (protections anti-robots
  comme DataDome ou Akamai). Le bot ne cherche pas à les contourner : il les met en pause
  et les signale dans `python3 -m dealbot sites`. Les autres continuent.
- **Couverture progressive** : un site de 500 000 produits ne se lit pas en
  une passe. Avec 150 pages par passe, le bot commence par les nouveautés et
  les pages modifiées, puis fait le tour du catalogue au fil des jours. Les
  boutiques Shopify/WooCommerce sont lues beaucoup plus vite.
- **La comparaison entre sites demande le code-barres** (EAN), publié par la
  plupart des grandes enseignes mais pas toutes. Sans lui, seules les chutes
  de prix d'un même produit sont détectées.
- Le bot ne peut pas toujours savoir qui vend sur une marketplace (certains
  sites ne l'indiquent pas dans leurs données) : l'alerte le précise alors,
  vérifiez « Vendu par » avant d'acheter.
- Un marchand peut annuler une commande passée sur une erreur de prix.
- Respectez les conditions d'utilisation des sites.

## Tests

```bash
python3 -m unittest discover -s tests
```
