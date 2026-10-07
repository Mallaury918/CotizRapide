#!/bin/sh
# Lance DealBot (Mac / Linux). Usage : ./lancer.sh   ou   ./lancer.sh test
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 n'est pas installé : https://www.python.org/downloads/"; exit 1
fi
if [ ! -f config.toml ]; then
  cp config.example.toml config.toml
  echo "config.toml créé : ouvrez-le, renseignez [telegram] token et chat_id, puis relancez."
  exit 0
fi
if [ "$1" = "test" ]; then
  python3 -m dealbot test-telegram
elif [ "$1" = "sites" ]; then
  python3 -m dealbot sites
else
  echo "DealBot démarre (Ctrl+C pour arrêter)…"
  python3 -m dealbot run 2>&1 | tee -a dealbot.log
fi
