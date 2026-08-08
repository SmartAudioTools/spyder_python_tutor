#!/bin/bash
# Installation de CE greffon dans le venv Spyder d'une machine SmartOS (mecanisme .pth
# "editable" : le greffon reste dans ce depot, seul un pointeur part dans site-packages).
# Sorti d'installation_SmartPythonEditor.sh le 08/08/2026 (demande utilisateur : les notes et
# verifications de chaque greffon vivent dans SON depot) - le script SmartOS n'est plus qu'un
# appel d'une ligne vers ce fichier. L'installation DISTRIBUEE (install.sh du fork
# SmartPythonEditor) n'utilise PAS ce script : elle passe par pip.
#
# Usage : installer_dans_venv.sh <python du venv Spyder> <sans_tests true|false> \
#                                <install_spyder_plugin.py> <spyder_config_set.py> <spyder.ini>
set -u
SPYDER_PYTHON="${1:?python du venv Spyder}"
SANS_TESTS="${2:-true}"
OUTIL_INSTALL="${3:?chemin de install_spyder_plugin.py}"
OUTIL_CONFIG="${4:?chemin de spyder_config_set.py}"
SPYDER_INI="${5:?chemin du spyder.ini}"
PLUGIN_DIR="$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")/.." && pwd)"

# =============================================================================
# Plugin Spyder "Python Tutor" (TODO - Spyder - plugin Python Tutor.txt)
# =============================================================================
# Installe dans l'environnement pyenv de Spyder le plugin versionne dans
# ce depot (spyder_python_tutor/, qui ajoute UN panneau
# "Python Tutor" visualisant l'execution pas a pas du fichier courant.
#
# CE QUE FAIT LE GREFFON
#   Un bouton "Lancer Python Tutor" (barre d'outils APPLICATIVE, comme la barre du
#   debogueur) trace le fichier actif avec pg_logger (Online Python Tutor, vendore)
#   dans un process separe, puis affiche le schema memoire (pile/tas/fleches) d'OPT
#   dans un QWebEngineView embarque. Les boutons Debut/Precedent/Suivant/Fin/Arreter
#   se DEPLOIENT une fois lance et pilotent l'avancement ; a chaque pas, une fleche
#   turquoise (dans la marge du DebuggerPanel) suit la ligne courante dans l'editeur.
#
# POURQUOI PAS DE "pip install" DE DEPENDANCE
#   Le backend (pg_logger/pg_encoder) ET le frontend (bundle pytutor-embed v5) sont
#   VENDORES dans le plugin (backend/ et frontend/, licence MIT incluse). Aucune
#   dependance PyPI : le greffon n'importe que qtpy et qtawesome, deja presents.
#
# ⚠ PREREQUIS : UN QtWebEngine RECENT (le schema est rendu dans un QWebEngineView)
#   Le QtWebEngine de PyQt5 est fige sur Chromium 87 (fin 2020), sur lequel les vues
#   web modernes meurent au chargement. Les trois installation_SmartPythonEditor.sh basculent donc le
#   venv sur PyQt6 + PyQt6-WebEngine (Chromium ~130).
#   Sur RaspberryPi5 et UbuntuStudio, cette bascule est TOLERANTE A L'ECHEC : elle
#   n'installe PyQt6 qu'en cas de succes et laisse sinon PyQt5 en place avec un
#   avertissement, la disponibilite d'une roue PyQt6-WebEngine pour leur architecture
#   (aarch64 notamment) n'etant pas garantie. Si elle echoue, le greffon s'installe
#   quand meme mais la VISUALISATION restera vide — meme limite que la timeline
#   Perfetto de spyder_viztracer.
#   Niveau de preuve : verifie en direct sur CachyOS uniquement ; PORTE MAIS JAMAIS
#   TESTE sur RaspberryPi5 et UbuntuStudio (pas de machine de test disponible).
#
# DEUX PIEGES RESOLUS (2026-07-23), ne pas re-casser
#   - Frontend = bundle v5 (PAS la v3) : la v3 de pytutor.js fait assert(!hideCode)
#     et signale l'echec par alert("Assertion Failure ...") des qu'on masque le code.
#   - javaScriptAlert est INTERCEPTE dans le greffon : cet alert() ouvre un dialogue
#     MODAL depuis l'interieur d'un runJavaScript(), et cette re-entrance a fait
#     planter tout Spyder (SIGSEGV dans libQt6WebEngineCore). Verifie par test
#     isolant : alert() intercepte + frontend v5, le chargement file:// remarche
#     sans planter. Le schema d'URL n'etait PAS en cause (une premiere hypothese
#     avait fait passer par un serveur HTTP local, depuis supprime).
#
# Invocation : installation_SmartPythonEditor.sh --greffon python_tutor
# =============================================================================

# PAS de "set -e" : error_handler.sh installe un trap ERR interactif, incompatible
# avec errexit (cf. l'explication detaillee en tete de installation_SmartPythonEditor.sh).

if [ ! -f "$PLUGIN_DIR/pyproject.toml" ]; then
  echo "ERREUR : plugin introuvable dans $PLUGIN_DIR - abandon." >&2
  exit 1
fi

if [ ! -x "$SPYDER_PYTHON" ]; then
  echo "ERREUR : $SPYDER_PYTHON introuvable." >&2
  echo "         Installez d'abord Spyder (./installation_SmartPythonEditor.sh)." >&2
  exit 1
fi
echo "Environnement Spyder cible : $SPYDER_PYTHON"

# --- Verification du vendoring OPT ------------------------------------------
# Le greffon est inerte sans ces fichiers (backend/frontend tierces, vendores).
if [ ! -f "$PLUGIN_DIR/spyder_python_tutor/spyder/backend/pg_logger.py" ] \
   || [ ! -f "$PLUGIN_DIR/spyder_python_tutor/spyder/frontend/js/pytutor-embed.bundle.js" ]; then
  echo "ERREUR : fichiers Online Python Tutor absents (backend/ ou frontend/)." >&2
  echo "         Voir les VENDORING.txt du plugin." >&2
  exit 1
fi

# --- Smoke-test --------------------------------------------------------------
# On verifie ce que Spyder fera au demarrage : les modules du greffon s'importent,
# les icones qta se valident (une icone invalide leve dans setup(), et Spyder AVALE
# l'exception -> greffon absent du menu), le point d'entree se decouvre, et le
# backend pg_logger produit bien une trace (shim `imp` de Py3.12 inclus).
# QT_QPA_PLATFORM=offscreen : la validation qta.icon exige une QApplication.
if [ "$SANS_TESTS" = false ]; then
  echo
  echo "--- Smoke-test : imports, icones, point d'entree, backend pg_logger ---"
  if ! QT_QPA_PLATFORM=offscreen PYTHONPATH="$PLUGIN_DIR" "$SPYDER_PYTHON" - <<'PYEOF'
from qtpy.QtWidgets import QApplication
app = QApplication([])  # requis pour que qtawesome valide les noms d'icones
import qtawesome as qta
from spyder_python_tutor.spyder.plugin import PythonTutorPlugin
from spyder_python_tutor.spyder.panels import install_tutor_arrow
# Icones utilisees par le greffon (get_icon, actions de la barre, fleche marge).
for name in ("mdi.school-outline", "mdi.play-circle-outline", "mdi.skip-backward",
             "mdi.menu-left", "mdi.menu-right", "mdi.skip-forward",
             "mdi.stop", "mdi.arrow-right-bold"):
    qta.icon(name)
assert PythonTutorPlugin.NAME == "python_tutor", "NAME inattendu"
install_tutor_arrow()  # le monkeypatch du DebuggerPanel doit s'appliquer sans erreur
print("OK  imports + icones + point d'entree ; NAME =", PythonTutorPlugin.NAME)
PYEOF
  then
    echo "ERREUR : le greffon ne se charge pas - installation annulee." >&2
    exit 1
  fi

  # Backend : pg_logger doit produire une trace non vide sur un petit script.
  echo "--- Smoke-test backend : pg_logger produit une trace ---"
  TMP_SRC=$(mktemp --suffix=.py)
  TMP_OUT=$(mktemp --suffix=.json)
  printf 'x = [1, 2, 3]\ny = x\ny.append(4)\nprint(sum(x))\n' > "$TMP_SRC"
  if ! "$SPYDER_PYTHON" \
        "$PLUGIN_DIR/spyder_python_tutor/spyder/backend/run_trace.py" \
        "$TMP_SRC" "$TMP_OUT" \
     || ! "$SPYDER_PYTHON" -c "import json,sys; d=json.load(open('$TMP_OUT')); sys.exit(0 if d.get('trace') else 1)"; then
    echo "ERREUR : le backend pg_logger n'a pas produit de trace exploitable." >&2
    rm -f "$TMP_SRC" "$TMP_OUT"
    exit 1
  fi
  rm -f "$TMP_SRC" "$TMP_OUT"
  echo "OK  backend pg_logger fonctionnel."
fi

# --- Installation ------------------------------------------------------------
echo
# ⚠ PAS de "pip install" ici : le venv pyenv de Spyder est construit a partir d'un
# requirements fige qui NE CONTIENT PAS setuptools. install_spyder_plugin.py ecrit
# directement ce que produirait une installation "editable" (un .pth + un .dist-info
# portant le point d'entree). Le plugin reste dans le depot Mercurial : une
# correction y est active au prochain lancement de Spyder, sans reinstallation.
# Cf. l'en-tete de install_spyder_plugin.py.
python3 "$OUTIL_INSTALL" \
    "$PLUGIN_DIR" "$SPYDER_PYTHON" || {
  echo "ERREUR : l'installation du plugin a echoue." >&2; exit 1; }

# --- Barre visible des le PREMIER demarrage (25/07/2026, demande utilisateur) -------
# Meme raison que pour le greffon "Interpreteur" : Spyder n'affiche au demarrage que les barres
# listees dans toolbar/last_visible_toolbars (toolbar/container.py:load_last_visible_toolbars), et
# le spyder.ini de reference ne connait que les six barres d'origine. Sans cette ligne, la barre
# Python Tutor - qui porte TOUS ses controles (Lancer, Debut/Precedent/Suivant/Fin, Arreter) -
# restait masquee, et le panneau se pilotait donc a la souris depuis nulle part.
# "+=" ajoute a la liste sans toucher aux barres deja activees par l'utilisateur.
python3 "$OUTIL_CONFIG" \
    "$SPYDER_INI" \
    toolbar/last_visible_toolbars+=python_tutor_toolbar

echo
echo "Plugin 'Python Tutor' installe (un panneau + barre d'outils applicative)."
echo "Dans Spyder : menu Fenetre > Panneaux > Python Tutor."
echo "Ouvrez un petit script, cliquez 'Lancer Python Tutor' : le schema memoire"
echo "s'affiche, les boutons de navigation se deploient, une fleche turquoise suit"
echo "la ligne courante dans l'editeur."
