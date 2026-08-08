# -*- coding: utf-8 -*-
"""Dock « Python Tutor » : visualise pas a pas l'execution du fichier courant.

Modele (cf. CachyOS/Documentation/TODO - Spyder - plugin Python Tutor.txt) :

  - BACKEND : pg_logger (Online Python Tutor, vendore dans backend/) trace le
    fichier courant dans un process separe (tracer.py) et produit une trace JSON
    {"code": ..., "trace": [...]}. Le Python connait donc len(trace) et la ligne
    de CHAQUE pas : c'est LUI qui pilote l'avancement (self._cur), pas la vue web.

  - FRONTEND : ExecutionVisualizer, via le bundle d'embarquement v5
    (frontend/js/pytutor-embed.bundle.js, tout-en-un) charge en file:// dans un
    QWebEngineView, options hideCode:true + controles OPT masques -> il ne reste
    que le schema memoire (pile / tas / fleches de references). Le code source
    n'apparait QUE dans l'editeur Spyder : pas de double affichage.

  - BARRE D'OUTILS calquee sur le debogueur de Spyder (DebuggerWidget) : une
    action « Lancer » TOUJOURS visible, puis Debut / Precedent / Suivant / Fin /
    Arreter qui se DEPLOIENT une fois la trace prete — c'est-a-dire ajoutees pour
    de vrai a la barre (pas un simple grisage) — et se replient a l'arret. Voir
    _deploy_controls, transposition de
    DebuggerWidget._set_visible_control_debugger_buttons.

La vue web est creee A LA DEMANDE au premier lancement : instancier QtWebEngine
(pile Chromium) au demarrage de Spyder l'alourdirait pour rien (idem viztracer).
"""

import json
import os

import qtawesome as qta

from qtpy.QtCore import Qt, QSize, Signal, QUrl
from qtpy.QtGui import QIcon, QPainter, QPixmap
from qtpy.QtSvg import QSvgRenderer
from qtpy.QtWidgets import QPlainTextEdit, QStackedWidget, QVBoxLayout

from spyder.api.plugins import Plugins
from spyder.api.widgets.main_widget import PluginMainWidget

from spyder_python_tutor.spyder.tracer import TutorRunner
from spyder_python_tutor.spyder.translations import _

_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
_VIZ_HTML = os.path.join(_FRONTEND_DIR, "viz.html")

# Icones du bouton « Lancer », VENDOREES DANS LE PAQUET (spyder/images/), a cote de
# backend/ et frontend/ : elles voyagent avec le greffon (commit, portage Commun/)
# et sont resolues relativement a __file__ — aucun chemin absolu a maintenir.
_ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "images")


def _find_icon(basename):
    """Chemin de l'icone `basename` dans spyder/images/, ou None si absente."""
    candidate = os.path.join(_ICON_DIR, basename)
    return candidate if os.path.isfile(candidate) else None

# Turquoise de l'icone Python_tutor_start.svg : les boutons de navigation le
# reprennent (barre d'outils assortie a l'icone et a la fleche de marge).
_NAV_COLOR = "#40b3c0"

def _build_launch_icon():
    """Icone du bouton « Lancer » : SVG turquoise (Normal) + SVG gris (Disabled).

    Le bouton se desactive pendant le tracage (update_actions). Par defaut Qt
    grise alors l'icone en CLAIR ; on fournit a la place le SVG desactive dedie
    (Python_tutor_start_disabled.svg) pour l'etat Disabled. Repli sur une icone
    qtawesome si le SVG normal est introuvable.
    """
    normal = _find_icon("Python_tutor_start.svg")
    if normal is None:
        return qta.icon("mdi.play-circle-outline", color=_NAV_COLOR)
    disabled = _find_icon("Python_tutor_start_disabled.svg")
    if disabled is None:
        return QIcon(normal)  # pas de SVG desactive : grise auto de Qt

    # ⚠ On construit l'icone UNIQUEMENT a partir de pixmaps rendus, pour les DEUX
    # etats. Avec QIcon(svg) + addPixmap, le moteur SVG re-rend l'icone NORMALE et
    # la grise lui-meme des qu'on lui demande une taille absente des pixmaps
    # ajoutes (mesure : 182,182,182 au lieu du gris du SVG dedie) — le SVG
    # desactive etait alors ignore. Avec un QIcon vide, aucun moteur SVG : Qt
    # prend le pixmap le plus proche de chaque etat.
    icon = QIcon()
    for path, mode in ((normal, QIcon.Normal), (disabled, QIcon.Disabled)):
        renderer = QSvgRenderer(path)
        for px in (16, 20, 22, 24, 28, 32, 40, 48, 64):
            pixmap = QPixmap(QSize(px, px))
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            icon.addPixmap(pixmap, mode)
    return icon

# Identifiant de la barre d'outils APPLICATIVE (en haut de la fenetre Spyder, pas
# dans le dock) — comme la « Debug toolbar » du debogueur. Cree par le greffon
# (plugin.py, on_toolbar_available), rempli avec les actions ci-dessous.
PYTHON_TUTOR_TOOLBAR = "python_tutor_toolbar"

# Journal de diagnostic de la vue web (messages console JS, crash du rendu). Lu
# depuis l'exterieur pour diagnostiquer (l'assertion ne part ni dans le core-dump
# ni dans stderr). Remis a zero a chaque « Lancer » (voir launch()).
_WEB_DEBUG_LOG = "/DATA/Python/SmartOS/HGIGNORED/python_tutor_web.log"


def _web_debug(msg):
    try:
        with open(_WEB_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass


class PythonTutorActions:
    """Identifiants des actions de la barre d'outils."""

    Launch = "python_tutor_launch"
    First = "python_tutor_first"
    Prev = "python_tutor_prev"
    Next = "python_tutor_next"
    Last = "python_tutor_last"
    Stop = "python_tutor_stop"


class PythonTutorWidget(PluginMainWidget):
    """Afficheur (journal + schema web) et pilote de l'avancement."""

    # Le greffon connecte ces signaux : lui seul lit le fichier courant de
    # l'editeur et sait y surligner une ligne.
    sig_launch_requested = Signal()
    sig_goto_requested = Signal(str, int)   # (fichier, ligne)
    sig_session_stopped = Signal()          # fin de session : nettoyer la bande

    def __init__(self, name=None, plugin=None, parent=None):
        super().__init__(name, plugin, parent)

        # Etat de session (le Python est maitre de l'avancement). La ligne d'un pas
        # se lit dans la trace elle-meme (_trace[i]["line"]) : pas de liste parallele.
        self._trace = []            # liste des pas (dict OPT)
        self._cur = 0               # index du pas courant
        self._filename = None       # fichier trace (pour le surlignage editeur)
        self._active = False        # session en cours (boutons deployes)
        self._web = None            # QWebEngineView, cree a la demande
        self._web_ready = False     # viz.html charge et renderTrace possible
        self._pending_trace = None  # trace en attente du chargement de la vue

        # Renseignes par setup() puis on_toolbar_rendered. Initialises ici pour que
        # l'etat soit explicite : les methodes n'ont pas a se defendre de leur
        # propre ordre d'initialisation (plus de hasattr/getattr defensifs).
        self._launch_action = None
        self._control_actions = []
        self._toolbar = None

        # --- page JOURNAL ---
        self._log = QPlainTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setPlaceholderText(
            _("Cliquer sur « Lancer Python Tutor » pour tracer le fichier "
              "courant et visualiser son execution pas a pas."))

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._log)   # index 0

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)
        self.setLayout(layout)

        self._runner = TutorRunner(self)
        self._runner.sig_started.connect(
            lambda f: self._append(_("Tracage en cours… ({}).").format(f)))
        self._runner.sig_output.connect(self._append)
        self._runner.sig_trace_ready.connect(self._on_trace_ready)
        self._runner.sig_failed.connect(self._on_failed)
        self._runner.sig_finished.connect(self.update_actions)

    # --- API PluginMainWidget -----------------------------------------------

    def get_title(self):
        return _("Python Tutor")

    def setup(self):
        # Action TOUJOURS visible : lancer le tracage du fichier courant.
        # Icone SVG dediee (turquoise), avec un rendu desactive gris FONCE.
        self._launch_action = self.create_action(
            PythonTutorActions.Launch,
            text=_("Lancer Python Tutor"),
            icon=_build_launch_icon(),
            tip=_("Trace le fichier actif et affiche l'execution pas a pas."),
            triggered=self.sig_launch_requested,
        )

        # Actions de navigation, DEPLOYEES seulement quand une trace est prete.
        self._first_action = self.create_action(
            PythonTutorActions.First,
            text=_("Debut"),
            icon=qta.icon("mdi.skip-backward", color=_NAV_COLOR),
            tip=_("Revenir au premier pas."),
            triggered=self._go_first,
        )
        self._prev_action = self.create_action(
            PythonTutorActions.Prev,
            text=_("Precedent"),
            icon=qta.icon("mdi.menu-left", color=_NAV_COLOR, scale_factor=1.45),
            tip=_("Pas precedent."),
            triggered=self._go_prev,
        )
        self._next_action = self.create_action(
            PythonTutorActions.Next,
            text=_("Suivant"),
            icon=qta.icon("mdi.menu-right", color=_NAV_COLOR, scale_factor=1.45),
            tip=_("Pas suivant."),
            triggered=self._go_next,
        )
        self._last_action = self.create_action(
            PythonTutorActions.Last,
            text=_("Fin"),
            icon=qta.icon("mdi.skip-forward", color=_NAV_COLOR),
            tip=_("Aller au dernier pas (la session reste active)."),
            triggered=self._go_last,
        )
        self._stop_action = self.create_action(
            PythonTutorActions.Stop,
            text=_("Arreter"),
            icon=qta.icon("mdi.stop", color=_NAV_COLOR),
            tip=_("Fermer la session : vider le schema et replier les boutons."),
            triggered=self._stop_session,
        )

        # Ordre de deploiement, apres « Lancer » qui reste seul au repos.
        self._control_actions = [
            self._first_action, self._prev_action, self._next_action,
            self._last_action, self._stop_action,
        ]

        # Les actions ne sont PAS ajoutees au dock : c'est le greffon qui les
        # place dans une barre d'outils APPLICATIVE (plugin.py, on_toolbar_available).
        # La reference a cette barre est recuperee dans on_toolbar_rendered, une
        # fois qu'elle est reellement rendue.
        self.update_actions()

    def on_toolbar_rendered(self):
        """La barre applicative Python Tutor est rendue : la memoriser + replier.

        Appele via sig_is_rendered (branche par le greffon). On garde une
        reference au QToolBar pour deployer/replier les boutons de navigation par
        addAction/removeAction — meme technique que le debogueur de Spyder
        (DebuggerWidget.on_debug_toolbar_rendered + _set_visible_control_debugger_buttons).
        Au (re)rendu, aucune session active : on replie.
        """
        self._toolbar = self.get_toolbar(
            PYTHON_TUTOR_TOOLBAR, plugin=Plugins.Toolbar)
        self._deploy_controls(self._active)

    def render_toolbars(self):
        """Masque les deux barres du panneau : elles sont vides et n'apprennent rien.

        Chapitre "Dock2" de CachyOS/Documentation/TODO - Spyder - cosmetique.txt (25/07/2026),
        meme raisonnement - et meme technique - que les panneaux Pyxel (cf. la longue note de
        spyder_pyxel/.../widgets/panes.py) :
          - la barre PRINCIPALE est vide, les boutons de ce greffon vivant dans une barre
            d'outils APPLICATIVE (cf. setup / on_toolbar_rendered) : elle ne ferait que voler
            une bande de hauteur a la visualisation ;
          - la barre du COIN ne porte que le bouton burger, dont le menu se reduit ici aux
            quatre actions de dock que PluginMainWidget ajoute d'office (Deplacer, Detacher,
            Ancrer, Fermer) - aucun reglage propre au panneau.

        ⚠ POURQUOI ICI ET PAS DANS setup() : render() ajoute le bouton d'options a la barre par
        QToolBar.addWidget(), ce qui le reparente et le REMONTRE - un masquage fait plus tot
        serait annule. On masque donc apres le rendu.

        Rien n'est supprime : rendre les barres visibles suffit a retrouver le bouton et son
        menu. "Fermer" reste accessible par Affichage > Panneaux.
        """
        super().render_toolbars()
        self.get_main_toolbar().setVisible(False)
        self._corner_toolbar.setVisible(False)

    def update_actions(self):
        if self._launch_action is None:
            return  # appele avant setup() : rien a mettre a jour
        self._launch_action.setEnabled(not self._runner.is_running())
        # Grisage contextuel des controles pendant une session.
        at_start = self._cur <= 0
        at_end = self._cur >= (len(self._trace) - 1)
        self._first_action.setEnabled(self._active and not at_start)
        self._prev_action.setEnabled(self._active and not at_start)
        self._next_action.setEnabled(self._active and not at_end)
        self._last_action.setEnabled(self._active and not at_end)
        self._stop_action.setEnabled(self._active)

    # --- API du greffon -------------------------------------------------------

    def launch(self, filename):
        """Appele par le greffon avec le chemin du fichier courant."""
        if not filename:
            self._append(_("Aucun fichier ouvert dans l'editeur."))
            return
        self._filename = filename  # cible du surlignage editeur au fil des pas
        try:  # repartir d'un journal de diagnostic web vierge
            open(_WEB_DEBUG_LOG, "w").close()
        except OSError:
            pass
        self._stack.setCurrentWidget(self._log)  # montrer la progression
        self._append("")
        self._append(_("→ {}").format(filename))
        self._runner.trace_file(filename)
        self.update_actions()

    def on_close(self):
        """Fermeture du greffon : tuer un tracage en cours."""
        self._runner.stop()

    # --- reception de la trace ------------------------------------------------

    def _on_trace_ready(self, trace_obj):
        """La trace est decodee : demarrer la session au pas 0."""
        self._trace = trace_obj.get("trace", []) or []
        if not self._trace:
            self._append(_("Trace vide : rien a visualiser."))
            return
        self._cur = 0
        self._active = True  # self._filename a ete fixe dans launch()

        self._ensure_web()
        self._deploy_controls(True)
        self._append(_("Trace prete : {} pas.").format(len(self._trace)))

        # Charger viz.html puis, une fois pret, injecter la trace complete.
        self._pending_trace = trace_obj
        if self._web_ready:
            self._render_and_show(trace_obj)
        # sinon : _on_web_loaded s'en chargera au signal loadFinished
        self.update_actions()

    def _on_failed(self, message):
        self._append(_("ERREUR : {}").format(message))
        self._stack.setCurrentWidget(self._log)

    # --- vue web (creee a la demande) ----------------------------------------

    def _ensure_web(self):
        if self._web is not None:
            return
        if not os.path.isfile(_VIZ_HTML):
            self._append(
                _("Frontend absent : {} n'existe pas.\n"
                  "Le bundle Online Python Tutor n'a pas ete vendore — voir "
                  "frontend/VENDORING.txt.").format(_VIZ_HTML))
            return
        # Import tardif : ne pas tirer QtWebEngine tant qu'aucune trace demandee.
        from qtpy.QtWebEngineWidgets import QWebEngineView
        # QWebEnginePage : QtWebEngineCore en Qt6, QtWebEngineWidgets en Qt5.
        try:
            from qtpy.QtWebEngineCore import QWebEnginePage
        except ImportError:
            from qtpy.QtWebEngineWidgets import QWebEnginePage

        # Page instrumentee LEGEREMENT : on ne journalise QUE les avertissements /
        # erreurs JS et les crashs de rendu (dans _WEB_DEBUG_LOG).
        #
        # ⚠ GARDE-FOU ESSENTIEL : javaScriptAlert est intercepte. pytutor.js signale
        # ses echecs par alert("Assertion Failure ..."), qui ouvre un dialogue MODAL
        # faisant tourner une boucle d'evenements imbriquee — et ici l'appel vient de
        # l'INTERIEUR d'un runJavaScript(). Cette re-entrance a fait planter tout
        # Spyder (SIGSEGV dans libQt6WebEngineCore, core-dump du 23/07/2026).
        # Diagnostic verifie par un test isolant : une fois alert() intercepte et le
        # frontend passe en v5 (qui n'assert plus), le chargement en file:// remarche
        # sans planter — le schema d'URL n'y etait donc pour RIEN, contrairement a ce
        # qu'une premiere hypothese (et un serveur HTTP local, depuis supprime) avait
        # laisse croire. Ne pas retirer cette interception.
        class _DebugPage(QWebEnginePage):
            def javaScriptConsoleMessage(self, level, message, line, source):
                name = getattr(level, "name", str(level))
                if "Error" in name or "Warning" in name:
                    _web_debug("JS[{}] {}:{}  {}".format(
                        name, source, line, message))

            def javaScriptAlert(self, origin, msg):
                _web_debug("ALERT: " + str(msg))  # journalise, pas de dialogue

        self._web = QWebEngineView(self)
        page = _DebugPage(self._web)
        self._web.setPage(page)
        page.renderProcessTerminated.connect(
            lambda status, code: _web_debug(
                "RENDER PROCESS TERMINATED status={} exitCode={}".format(
                    status, code)))
        self._web.loadFinished.connect(self._on_web_loaded)
        self._stack.addWidget(self._web)  # index 1
        self._web.load(QUrl.fromLocalFile(_VIZ_HTML))

    def _on_web_loaded(self, ok):
        self._web_ready = bool(ok)
        if not ok:
            self._append(_("Echec du chargement de la vue Python Tutor."))
            return
        if self._pending_trace is not None:
            self._render_and_show(self._pending_trace)

    def _run_js(self, label, script):
        """Execute du JS dans la vue, enrobe d'un try/catch ; journalise les erreurs.

        SEUL point d'entree vers la page : toute exception JS est ainsi capturee
        dans _WEB_DEBUG_LOG, et la garde « vue prete » est faite une seule fois.
        """
        if self._web is None or not self._web_ready:
            return
        wrapped = ("(function(){try{" + script +
                   "\nreturn 'OK';}catch(e){return 'ERR '+e+' | '+"
                   "(e&&e.stack||'');}})()")
        self._web.page().runJavaScript(
            wrapped,
            lambda res: None if res == "OK"
            else _web_debug("{} -> {}".format(label, res)))

    def _render_and_show(self, trace_obj):
        """Injecte la trace dans ExecutionVisualizer et affiche le pas courant."""
        self._pending_trace = None
        payload = json.dumps(trace_obj)
        # renderTrace() est defini dans viz.html : il instancie
        # ExecutionVisualizer avec hideCode:true et masque les controles OPT.
        self._run_js("renderTrace", "renderTrace(" + payload + ");")
        self._stack.setCurrentWidget(self._web)
        self._render_step()

    # --- navigation (le Python est maitre) -----------------------------------

    def _go_first(self):
        self._set_step(0)

    def _go_prev(self):
        self._set_step(self._cur - 1)

    def _go_next(self):
        self._set_step(self._cur + 1)

    def _go_last(self):
        self._set_step(len(self._trace) - 1)

    def _set_step(self, index):
        if not self._active or not self._trace:
            return
        index = max(0, min(index, len(self._trace) - 1))
        if index == self._cur:
            return
        self._cur = index
        self._render_step()
        self.update_actions()

    def _render_step(self):
        """Commande la vue web au pas courant + surligne la ligne dans l'editeur."""
        # curInstr + updateOutput() : on pilote la vue par index explicite pour
        # rester synchronise avec self._cur cote Python.
        self._run_js("step {}".format(self._cur),
                     "if (window.viz) {{ window.viz.curInstr = {}; "
                     "window.viz.updateOutput(); }}".format(self._cur))
        line = self._trace[self._cur].get("line") if self._cur < len(self._trace) \
            else None
        if self._filename and line:
            self.sig_goto_requested.emit(self._filename, int(line))

    # --- deploiement / repli des boutons (calque sur le debogueur) -----------

    def _stop_session(self):
        """Ferme la session : vide le schema, replie les boutons de navigation."""
        self._active = False
        self._trace = []
        self._cur = 0
        self._deploy_controls(False)
        self._run_js("stop", "window.viz = null;")
        self._stack.setCurrentWidget(self._log)
        self.sig_session_stopped.emit()  # retirer la bande turquoise de l'editeur
        self._append(_("Session Python Tutor arretee."))
        self.update_actions()

    def _deploy_controls(self, visible):
        """Ajoute/retire les boutons de navigation dans la barre d'outils.

        Transposition de DebuggerWidget._set_visible_control_debugger_buttons :
        afficher = reintroduire les actions APRES « Lancer » (retirees d'abord
        pour garantir l'ordre) ; masquer = les retirer (slot supprime, donc aucun
        espace gris). On agit directement sur le QToolBar par addAction/removeAction.
        """
        if self._toolbar is None:
            return  # barre pas encore rendue (on_toolbar_rendered)
        for action in self._control_actions:
            if action in self._toolbar.actions():
                self._toolbar.removeAction(action)
        if visible:
            for action in self._control_actions:
                self._toolbar.addAction(action)

    # --- journal --------------------------------------------------------------

    def _append(self, text):
        self._log.appendPlainText(text)
