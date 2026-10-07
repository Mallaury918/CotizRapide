# Démarrer DealBot en 10 minutes

## 1. Installer Python (une seule fois)

- **Windows** : https://www.python.org/downloads/ → téléchargez, lancez
  l'installeur et **cochez « Add python.exe to PATH »** avant « Install Now ».
- **Mac** : même lien, installez le fichier `.pkg`.
- Il faut Python **3.11 ou plus récent**.

## 2. Créer votre bot Telegram (une seule fois)

1. Dans Telegram, cherchez **@BotFather** et envoyez `/newbot`.
2. Choisissez un nom (ex. « Mes bonnes affaires ») puis un identifiant
   finissant par `bot` (ex. `mes_affaires_bot`).
3. BotFather vous donne un **token** du type `7123456789:AAH...` : copiez-le.
4. Ouvrez votre nouveau bot et envoyez-lui un message (« salut »).
5. Dans votre navigateur, ouvrez (en remplaçant `VOTRE_TOKEN`) :
   `https://api.telegram.org/botVOTRE_TOKEN/getUpdates`
   Repérez `"chat":{"id":123456789` : ce nombre est votre **chat_id**.

## 3. Configurer

- **Windows** : double-cliquez sur `lancer.bat`. Il crée `config.toml` et
  l'ouvre dans le Bloc-notes.
- **Mac / Linux** : dans un terminal, dans ce dossier : `./lancer.sh`

Dans `config.toml`, remplissez seulement :

```toml
[telegram]
token = "7123456789:AAH..."
chat_id = "123456789"
```

Enregistrez. Le reste peut rester tel quel.

## 4. Tester Telegram

- **Windows** : double-cliquez sur `tester-telegram.bat`
- **Mac / Linux** : `./lancer.sh test`

Vous devez recevoir « ✅ DealBot est bien connecté ». Sinon, revérifiez le
token et le chat_id.

## 5. Lancer le bot

- **Windows** : double-cliquez sur `lancer.bat` (laissez la fenêtre ouverte)
- **Mac / Linux** : `./lancer.sh`

Le bot scanne les boutiques en continu. Les alertes arrivent sur Telegram.
Pour l'arrêter : fermez la fenêtre (ou Ctrl+C).

## 6. Après quelques heures

- **Windows** : double-cliquez sur `etat-des-sites.bat`
- **Mac / Linux** : `./lancer.sh sites`

Vous voyez quelles boutiques fonctionnent et lesquelles bloquent le bot.
Envoyez ce résultat pour qu'on ajuste.

## À savoir

- **Patience** : le premier jour, le bot découvre surtout les prix ; les
  alertes arrivent quand il revoit les produits ou les compare entre sites.
- **L'ordinateur doit rester allumé** (et ne pas se mettre en veille) pour que
  le bot tourne. Pour du 24h/24, un petit serveur ou un Raspberry Pi est idéal.
- **eBay est optionnel** : sans clé eBay, le bot ignore eBay (message
  « source ebay indisponible ») et ne scanne que les boutiques. Pour l'activer,
  créez une clé gratuite sur https://developer.ebay.com et remplissez `[ebay]`.
- Ne partagez jamais votre `config.toml` : il contient votre token.
