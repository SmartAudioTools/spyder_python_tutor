# -*- coding: utf-8 -*-
"""Greffon « Python Tutor » : visualise l'execution du fichier courant.

Le greffon est la seule couche qui connait le plugin Editor : il fournit au widget
le chemin du fichier a tracer (sig_launch_requested) et pilote le saut/surlignage
de ligne dans l'editeur au fil des pas (sig_goto_requested). Toute la logique de
trace et d'affichage vit dans le widget (widgets/main_widget.py) et le runner
(tracer.py).
"""

import os

import qtawesome as qta

from spyder.api.plugin_registration.decorators import (
    on_plugin_available, on_plugin_teardown)
from spyder.api.plugins import Plugins, SpyderDockablePlugin
from spyder.utils.icon_manager import ima

from spyder_python_tutor.spyder.panels import install_tutor_arrow, set_step_arrow
from spyder_python_tutor.spyder.translations import _
from spyder_python_tutor.spyder.widgets.main_widget import (
    PythonTutorActions, PythonTutorWidget, PYTHON_TUTOR_TOOLBAR)

# Actions placees dans la barre d'outils APPLICATIVE, dans l'ordre : « Lancer »
# (toujours visible) puis les controles de navigation (deployes en session).
_TOOLBAR_ACTIONS = [
    PythonTutorActions.Launch,
    PythonTutorActions.First,
    PythonTutorActions.Prev,
    PythonTutorActions.Next,
    PythonTutorActions.Last,
    PythonTutorActions.Stop,
]


class PythonTutorPlugin(SpyderDockablePlugin):
    """Panneau Python Tutor (visualisation pas a pas de l'execution)."""

    NAME = "python_tutor"  # doit etre identique au nom du point d'entree
    REQUIRES = [Plugins.Editor]
    OPTIONAL = [Plugins.Toolbar]
    TABIFY = [Plugins.Help]
    WIDGET_CLASS = PythonTutorWidget
    CONF_SECTION = "python_tutor"
    CONF_FILE = False

    @staticmethod
    def get_name():
        return _("Python Tutor")

    @staticmethod
    def get_description():
        return _("Trace le fichier courant et visualise l'execution pas a pas "
                 "(pile, tas, references) a destination des eleves.")

    @classmethod
    def get_icon(cls):
        return qta.icon("mdi.school-outline", color=ima.MAIN_FG_COLOR)

    # --- API SpyderDockablePlugin -------------------------------------------

    def on_initialize(self):
        widget = self.get_widget()
        widget.sig_launch_requested.connect(self._launch_current_file)
        widget.sig_goto_requested.connect(self._goto_in_editor)
        widget.sig_session_stopped.connect(self._clear_step_highlight)
        # Etendre le DebuggerPanel de Spyder avec la fleche turquoise (idempotent).
        install_tutor_arrow()
        self._arrow_panel = None  # DebuggerPanel portant la fleche turquoise

    @on_plugin_available(plugin=Plugins.Editor)
    def on_editor_available(self):
        self.get_widget().update_actions()

    @on_plugin_available(plugin=Plugins.Toolbar)
    def on_toolbar_available(self):
        """Cree la barre d'outils APPLICATIVE et y place les actions.

        Meme mecanique que le debogueur (debugger/plugin.py.on_toolbar_available) :
        creer la barre, y ajouter les actions, puis brancher sig_is_rendered pour
        que le widget memorise la barre et replie les controles au repos.
        """
        toolbar = self.get_plugin(Plugins.Toolbar)
        toolbar.create_application_toolbar(
            PYTHON_TUTOR_TOOLBAR, _("Python Tutor"))
        for action_id in _TOOLBAR_ACTIONS:
            toolbar.add_item_to_application_toolbar(
                self.get_action(action_id),
                toolbar_id=PYTHON_TUTOR_TOOLBAR,
            )
        tb = toolbar.get_application_toolbar(PYTHON_TUTOR_TOOLBAR)
        tb.sig_is_rendered.connect(self.get_widget().on_toolbar_rendered)

    @on_plugin_teardown(plugin=Plugins.Toolbar)
    def on_toolbar_teardown(self):
        toolbar = self.get_plugin(Plugins.Toolbar)
        for action_id in _TOOLBAR_ACTIONS:
            toolbar.remove_item_from_application_toolbar(
                action_id, toolbar_id=PYTHON_TUTOR_TOOLBAR)
        toolbar.remove_application_toolbar(PYTHON_TUTOR_TOOLBAR)

    # --- interne -------------------------------------------------------------

    def _launch_current_file(self):
        """Recupere le fichier actif de l'editeur et lance le tracage."""
        filename = None
        editor = self.get_plugin(Plugins.Editor, error=False)
        if editor is not None:
            filename = editor.get_current_filename()
        # Amener l'onglet « Python Tutor » au premier plan de son dock : sinon la
        # visualisation se construit dans un panneau cache derriere ses voisins
        # (Aide, VizTracer, Explorateur de variables...). force_focus reste a False
        # (defaut) : on rend l'onglet visible sans voler le clavier a l'editeur.
        self.switch_to_plugin()
        self.get_widget().launch(filename)

    def _goto_in_editor(self, filename, line):
        """Ouvre le fichier, va a la ligne du pas, et pose la bande turquoise.

        editor.load(goto=line) ouvre/active l'onglet et fait defiler jusqu'a la
        ligne ; on ajoute ensuite une decoration turquoise pleine largeur sur cette
        ligne (cle _STEP_KEY), qui suit donc chaque pas — comme la ligne courante
        du debogueur, a la couleur de l'icone.
        """
        editor = self.get_plugin(Plugins.Editor, error=False)
        if editor is None or not filename or not os.path.isfile(filename):
            return
        if line is None:
            return
        editor.load(filenames=filename, goto=line)
        # Fleche turquoise dans la marge du DebuggerPanel, a la ligne du pas.
        self._arrow_panel = set_step_arrow(editor.get_current_editor(), int(line))

    def _clear_step_highlight(self):
        """Efface la fleche turquoise (fin de session)."""
        panel = self._arrow_panel
        self._arrow_panel = None
        if panel is not None:
            try:
                panel.set_tutor_line_arrow(None)
            except RuntimeError:
                pass  # l'editeur a pu etre ferme entre-temps
