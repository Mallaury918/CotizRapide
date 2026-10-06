# 🛍️ Bot Vinted : chasseur de bonnes affaires

Ce bot surveille Vinted en continu. Il t'envoie sur **Telegram** (ou Discord) les nouvelles
annonces vendues **nettement moins cher que des annonces similaires**, pour acheter et revendre.

Il fonctionne de deux façons, utilisables ensemble :

- **Tout Vinted** (section `[flux]`, activée par défaut) : il lit en continu les nouvelles
  annonces de tout le site, sans mots-clés à écrire.
- **Recherches ciblées** (`[[recherches]]`, facultatives) : il suit de près les articles
  que tu choisis, avec un prix de référence plus fiable.

## Leboncoin (toute la France, livraison uniquement)

Le bot surveille aussi Leboncoin, avec des **recherches ciblées** (section `[leboncoin]` du
`config.toml`). Il ne garde que les **annonces avec livraison**, partout en France, pour
acheter sans te déplacer. Il fonctionne comme les recherches Vinted : il apprend les prix
de chaque recherche, puis t'alerte quand une nouvelle annonce est bien moins chère.

- **Pourquoi pas « tout Leboncoin » ?** Le site mélange voitures, logements, meubles…, et
  beaucoup d'annonces n'ont pas de marque. Comparer les prix sans recherche précise
  donnerait surtout de fausses alertes.
- **Frais réels :** pour chaque annonce, le bot prend les vrais frais acheteur et le mode
  de livraison le moins cher indiqués par Leboncoin.
- **Vendeurs :** Leboncoin n'affiche pas de nombre de ventes. Le bot exige à la place
  autant d'avis (5 avis et une note de 4/5 minimum avec les réglages par défaut).
- **Prudence :** Leboncoin est protégé par DataDome, très sensible aux robots. Le bot fait
  une lecture par recherche toutes les ~10 minutes. Garde peu de recherches, et s'il
  affiche « Leboncoin bloque le bot », arrête-le quelques heures.
- **curl_cffi est obligatoire** pour Leboncoin : il est dans `requirements.txt`.

## Le mode « tout Vinted »

Toutes les ~30 secondes, le bot lit les dernières annonces publiées sur tout le site.
Si le site publie plus vite qu'il ne lit, il lit jusqu'à 3 pages d'affilée. Pour chaque
annonce, il cherche dans sa mémoire des **articles vraiment semblables** :

- **la même marque** ;
- **un titre proche** : au moins 40 % de mots en commun, sans compter la marque, la taille
  ni les mots comme « très bon état » ;
- **le même type d'article** : des chaussettes Nike ne sont jamais comparées à des baskets
  Nike, ni une coque d'iPhone à un iPhone.

Il construit lui-même sa base de prix à partir de tout ce qu'il voit. **Les premières heures,
il apprend et alerte peu**, puis de plus en plus au fil des jours. Les articles sans marque
sont ignorés par défaut, car ils se comparent et se revendent mal. Un garde-fou limite les
alertes à 30 par heure.

Il ne peut pas voir 100 % des annonces : Vinted en publie plusieurs par seconde, et lire
plus vite exposerait le bot à un blocage. Il en voit une grande partie, en priorité les plus
fraîches, ce qui compte le plus pour acheter avant les autres.

## Comment il décide qu'une annonce est une bonne affaire

1. **Il étudie le marché.** En mode « tout Vinted », il mémorise les prix de toutes les
   annonces lues pendant 10 jours. Pour une recherche ciblée, il relève les prix d'environ
   300 annonces toutes les 6 h et garde un historique de 30 jours.
2. **Il compare ce qui est comparable.** Il prend d'abord les annonces de la même **marque
   et dans le même état**. S'il n'y en a pas assez, il prend la même marque, puis toute la
   recherche. Les prix aberrants sont écartés.
3. **Il compte le coût réel**, c'est-à-dire prix + protection acheteurs (0,70 € + 5 %) + livraison.
4. **Il t'alerte** si ce coût est au moins **35 % sous le prix du marché** *et* que la marge
   estimée dépasse **10 €**. Ces deux seuils se règlent.
5. **Il vérifie le vendeur.** Pour chaque bonne affaire, il consulte le profil : par défaut, il faut
   **au moins 5 ventes et une note d'au moins 4/5** (avec au moins 1 avis), sinon l'annonce
   est écartée. Ces seuils se règlent avec `vendeur_ventes_min`, `vendeur_note_min` et
   `vendeur_avis_min`. L'alerte affiche les ventes, la note et le nombre d'avis.
   Les profils restent 24 h en mémoire, pour ne pas les redemander à Vinted.
6. Si le prix est vraiment trop bas (< 20 % du marché), l'alerte est marquée ⚠️. C'est
   souvent une arnaque, un article cassé ou une boîte vide.

Au **premier lancement**, il mémorise les annonces déjà en ligne sans t'alerter. Les alertes
commencent au passage suivant, pour les nouvelles annonces uniquement.

## Installation (une seule fois)

Il faut **Python 3.11 ou plus récent** : https://www.python.org/downloads/
(sous Windows, coche « Add Python to PATH » pendant l'installation).

Ouvre un terminal dans le dossier `vinted-bot`, puis :

```bash
pip install -r requirements.txt
cp config.exemple.toml config.toml      # Windows : copy config.exemple.toml config.toml
```

## Recevoir les alertes sur Telegram (recommandé)

1. Sur Telegram, écris à **@BotFather**, envoie `/newbot` et suis les instructions.
   Il te donne un **token**, à copier dans `telegram_token` de `config.toml`.
2. Ouvre la conversation avec ton nouveau bot et envoie-lui n'importe quel message.
3. Lance `python -m vinted_bot --telegram-id` et copie la ligne affichée dans `config.toml`.
4. Vérifie avec `python -m vinted_bot --test-notif` : tu dois recevoir une alerte de test.

## Configurer tes recherches (facultatif)

Dans `config.toml`, chaque bloc `[[recherches]]` est une veille. Le plus simple :

1. Fais ta recherche sur vinted.fr avec les filtres voulus (catégorie, marque, taille, état…).
2. Copie l'URL de la page dans `url = "…"`.

```toml
[[recherches]]
nom = "Nike Dunk Low"
url = "https://www.vinted.fr/catalog?search_text=nike%20dunk%20low&brand_ids[]=53"
prix_min = 20
prix_max = 90
mots_requis = ["dunk"]            # le titre doit contenir ces mots
mots_exclus = ["enfant"]          # ignore les titres contenant ces mots
remise_min = 0.30                 # remplace le réglage global pour cette recherche
benefice_min = 15
```

💡 **Le conseil le plus important : sois précis.** Une recherche « iphone » mélange coques
à 5 € et téléphones à 400 €, et le prix de référence ne veut alors plus rien dire. Choisis
une catégorie sur Vinted et utilise `prix_min`, `mots_requis` et `mots_exclus`.

## Lancer le bot

```bash
python -m vinted_bot              # tourne en continu (Ctrl+C pour arrêter)
python -m vinted_bot --une-fois   # un seul passage
python -m vinted_bot -v           # avec plus de détails
```

Pour qu'il tourne 24 h/24, laisse ton PC allumé ou installe-le sur un Raspberry Pi
ou un petit serveur (VPS à ~4 €/mois). Les alertes envoyées sont aussi enregistrées dans
la table `affaires` du fichier `vinted_bot.db`.

## Limites à connaître

- **Prix du marché ≠ prix de vente.** Vinted ne publie pas les prix des ventes conclues :
  le bot se base sur les annonces en ligne. Celles qui sont trop chères restent en ligne
  plus longtemps, ce qui gonfle la moyenne. C'est pourquoi la référence par défaut est le
  40ᵉ percentile plutôt que la médiane (`percentile_reference`). Vérifie toujours avant d'acheter.
- **Anti-robot.** Vinted peut bloquer temporairement les requêtes trop nombreuses. Le mode
  « tout Vinted » fait déjà 2 à 6 requêtes par minute. Ne baisse pas `intervalle_secondes`
  sous 20, n'active pas trop de recherches en plus, et installe `curl_cffi`. Si tu vois des
  erreurs HTTP 403 ou 429, ralentis (par exemple `intervalle_secondes = 60`).
- **Place sur le disque.** La mémoire des prix du mode « tout Vinted » occupe quelques
  centaines de Mo, jusqu'à environ 1,5 Go. Réduis `historique_jours` si besoin.
- **Conditions d'utilisation.** Vinted n'autorise pas officiellement l'accès automatisé à
  son site. Utilise ce bot pour un usage personnel et raisonnable. Côté fiscal, l'achat-revente
  régulier dans un but lucratif est une activité commerciale à déclarer (micro-entreprise).

## En cas de problème

```bash
python -m vinted_bot --diagnostic
```

Cette commande teste la connexion à Vinted (puis à Leboncoin s'il est activé), la lecture des annonces et celle d'un profil
vendeur. Elle enregistre la réponse brute dans `diagnostic.json`, sans ton jeton de session.
Vinted modifie son API sans prévenir : en septembre 2026, le catalogue est passé sur
`api.vinted.fr/svc-catalogue/items`. Si quelque chose casse, c'est par là qu'il faut regarder.

## Tests

```bash
python -m unittest discover tests
```
