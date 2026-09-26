# 💰 Coin Rush — jeu Roblox monétisé

Un « simulateur » simple et addictif : on ramasse des pièces sur la carte, on clique pour en gagner,
on achète des améliorations, on fait des renaissances… et on peut acheter des avantages en **Robux**.

## Ce qu'il y a dans le jeu

| Élément | Détail |
|---|---|
| 🗺️ Carte | Générée automatiquement : sol, arbres, point d'apparition, murs invisibles |
| 🪙 Pièces au sol | 45 pièces qui réapparaissent, 6 % de pièces dorées (x10) |
| 👆 Bouton « CLIQUE ! » | Gagne des pièces à chaque clic (anti-autoclicker côté serveur) |
| ⬆ Améliorations | Puissance de clic, valeur des pièces, vitesse de marche |
| ♻ Renaissance | Remet à zéro contre +50 % de gains permanents (garde les joueurs longtemps) |
| 💾 Sauvegarde | DataStore : chargement avec réessais, sauvegarde auto, à la sortie et à l'arrêt du serveur |
| 🏆 Classement | `leaderstats` Coins + Rebirths visibles dans la liste des joueurs |

### 💸 Ce qui rapporte des Robux

**Game Passes** (achat unique) :
- **x2 Pièces** — double tous les gains
- **VIP** — +50 % de gains, +30 % de vitesse, tag `[VIP]` doré dans le chat
- **Auto-Clicker** — 2 clics/seconde automatiques, même AFK

**Produits de développeur** (achetables à l'infini — c'est là que se fait l'essentiel des revenus) :
- Petit sac / Coffre / Trésor de pièces (montant multiplié par les renaissances, donc toujours utile)
- Boost x3 pendant 15 min (cumulable)

Les achats sont traités de façon sûre : un achat n'est validé auprès de Roblox qu'une fois crédité
**et sauvegardé**, et un même reçu n'est jamais crédité deux fois.

## 🚀 Mise en route (15 minutes)

### 1. Ouvrir le jeu dans Roblox Studio
Double-clique sur **`CoinRush.rbxlx`** (ou Studio > Fichier > Ouvrir). Appuie sur **Play** : le jeu
fonctionne déjà (la boutique affiche « Bientôt » tant que les IDs ne sont pas configurés).

### 2. Publier l'expérience
Fichier > **Publier sur Roblox**. Puis dans *Paramètres du jeu* :
- **Sécurité** → active **Enable Studio Access to API Services** (sinon pas de sauvegarde en test)
- **Autorisations** → mets le jeu en **Public** quand tu es prêt·e

### 3. Créer les objets à vendre
Sur <https://create.roblox.com> → *Créations* → ton expérience → **Monétisation** :
- **Passes** : crée `x2 Pièces`, `VIP`, `Auto-Clicker` (avec une image), mets-les **en vente** avec un prix
- **Produits de développeur** : crée `Petit sac`, `Coffre`, `Trésor`, `Boost x3`

Prix de départ conseillés : x2 Pièces 199 R$, VIP 399 R$, Auto-Clicker 149 R$,
packs 25 / 99 / 399 R$, Boost 49 R$.

### 4. Coller les IDs
Ouvre `ReplicatedStorage > Shared > Config` et remplace chaque `Id = 0` par l'ID copié
depuis la page du pass/produit. Republie (Fichier > Publier). C'est tout ✅

> Les prix affichés dans la boutique du jeu sont lus directement chez Roblox, pas besoin de les recopier.

## 🛠️ Structure du code

```
src/
  shared/   → ReplicatedStorage.Shared
    Config.luau              IDs Robux, prix, équilibrage (le seul fichier à modifier)
    Economy.luau             formules (coûts, multiplicateurs, formatage 1.2K / 3.4M)
  server/   → ServerScriptService.Server
    Main.server.luau         logique du jeu, remotes, anti-triche
    DataService.luau         sauvegarde DataStore
    MonetizationService.luau Game Passes + ProcessReceipt
    World.luau               carte + apparition des pièces
  client/   → StarterPlayer.StarterPlayerScripts.Client
    UI.client.luau           toute l'interface (générée en code)
    ChatTags.client.luau     tag [VIP] dans le chat
    CoinSpin.client.luau     animation des pièces
```

Tu préfères travailler dans VS Code ? Installe [Rojo](https://rojo.space) puis `rojo serve`
dans ce dossier et connecte le plugin Rojo dans Studio. Pour régénérer le fichier de place :
`rojo build default.project.json -o CoinRush.rbxlx`.

## 📈 Conseils pour que ça rapporte vraiment

- **Une bonne icône et 3 miniatures** comptent plus que tout : c'est ce qui fait cliquer.
- Fais un peu de **pub** (Créations > Publicité / Sponsors) avec quelques centaines de Robux au lancement.
- Ajoute régulièrement du contenu (nouvelle zone, événement) : les mises à jour relancent le jeu dans l'algorithme.
- Regarde **Analytics > Monétisation** dans le Creator Dashboard et ajuste les prix.
- Active les **Premium Payouts** : tu es aussi payé·e quand des joueurs Premium passent du temps dans ton jeu.

⚠️ À savoir :
- Roblox garde environ 30 % sur chaque vente.
- Pour convertir des Robux en vrais euros il faut passer par le programme **DevEx**
  (âge minimum, seuil minimum de Robux gagnés et vérification d'identité — voir les conditions à jour sur
  <https://create.roblox.com/docs/production/earning-on-roblox>).
- Respecte les règles Roblox : pas de « loot box » payante au hasard sans afficher les chances, pas de promesses trompeuses.
