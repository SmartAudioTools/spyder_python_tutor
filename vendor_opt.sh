#!/usr/bin/env bash
# Re-vendoring d'Online Python Tutor (OPT) dans le plugin spyder_python_tutor.
#
# A LANCER PAR L'UTILISATEUR (acces reseau requis pour git clone) :
#     bash /DATA/Python/SmartOS/Commun/spyder_plugins/spyder_python_tutor/vendor_opt.sh
#
# Les fichiers OPT sont deja vendores dans le depot : ce script ne sert qu'a les
# REGENERER (montee de version d'OPT, ou verification de provenance). Il clone OPT
# et recopie exactement les trois fichiers utiles, tous issus de v5-unity :
#
#   backend/pg_logger.py             tracage sous bdb (Python 3)
#   backend/pg_encoder.py            encodage de l'etat en trace JSON
#   frontend/js/pytutor-embed.bundle.js   bundle webpack tout-en-un (v5)
#
# ⚠ TOUT VIENT DE v5-unity, backend ET frontend : ils doivent CORRESPONDRE.
#   - le backend v3 est en Python 2 (print >>) : inutilisable ;
#   - le frontend v3 fait assert(!hideCode) et ouvre une alerte "Assertion Failure"
#     des qu'on masque le code (ce que fait ce greffon).
#
# ⚠ Le backend v5 fait « import imp », module retire en Python 3.12 : le shim est
#   deja en tete de backend/run_trace.py (ne PAS modifier pg_logger.py pour ca).
#
# Idempotent : re-cloner et re-copier ecrase proprement. Ne commite rien.

set -o pipefail

PLUGIN="$(dirname "$(realpath "${BASH_SOURCE[0]}")")/spyder_python_tutor/spyder"
VENV_PY="/DATA/Python/SmartPython/CachyOS/versions/SmartPythonEditor/bin/python"
SRC="/tmp/opt-src"
REPO="https://github.com/aphirak/visualization-online-python-tutor"

echo "=== 1. Clone d'OPT dans $SRC ==="
rm -rf "$SRC"
git clone --depth 1 "$REPO" "$SRC" || { echo "ECHEC du clone"; exit 1; }

V="$SRC/v5-unity"
for f in "$V/pg_logger.py" "$V/pg_encoder.py" "$V/build/pytutor-embed.bundle.js"; do
    [ -f "$f" ] || { echo "ERREUR : $f introuvable dans le depot clone." >&2; exit 1; }
done

echo
echo "=== 2. Backend (v5-unity) ==="
mkdir -p "$PLUGIN/backend"
cp -v "$V/pg_logger.py" "$V/pg_encoder.py" "$PLUGIN/backend/"

echo
echo "=== 3. Frontend : le bundle d'embarquement (v5-unity) ==="
mkdir -p "$PLUGIN/frontend/js"
cp -v "$V/build/pytutor-embed.bundle.js" "$PLUGIN/frontend/js/"

echo
echo "=== 4. Licence OPT (MIT) ==="
for L in LICENSE LICENSE.txt LICENSE.md COPYING; do
    if [ -f "$SRC/$L" ]; then
        cp -v "$SRC/$L" "$PLUGIN/backend/LICENSE-OPT.txt"
        cp -v "$SRC/$L" "$PLUGIN/frontend/LICENSE-OPT.txt"
        break
    fi
done

echo
echo "=== 5. Test du backend (trace non vide) ==="
DEMO=$(mktemp --suffix=.py); OUT=$(mktemp --suffix=.json)
printf 'x = [1, 2, 3]\ny = x\ny.append(4)\nprint(sum(x))\n' > "$DEMO"
if [ -x "$VENV_PY" ]; then
    if "$VENV_PY" "$PLUGIN/backend/run_trace.py" "$DEMO" "$OUT" \
       && "$VENV_PY" -c "import json,sys; d=json.load(open('$OUT')); sys.exit(0 if d.get('trace') else 1)"; then
        echo "OK : le backend produit bien une trace."
    else
        echo "ECHEC : le backend ne produit pas de trace exploitable." >&2
    fi
else
    echo "Python du venv Spyder introuvable ($VENV_PY) : test saute."
fi
rm -f "$DEMO" "$OUT"

echo
echo "=== Fichiers vendores ==="
ls -l "$PLUGIN/backend/pg_logger.py" "$PLUGIN/backend/pg_encoder.py" \
      "$PLUGIN/frontend/js/pytutor-embed.bundle.js"
