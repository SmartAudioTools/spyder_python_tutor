# -*- coding: utf-8 -*-
"""Ajoute une fleche turquoise AU DebuggerPanel de Spyder (pas de panneau separe).

Demande utilisateur : reutiliser la marge EXISTANTE du debogueur (celle ou l'on
pose les points d'arret, `spyder/plugins/debugger/panels/debuggerpanel.py`) plutot
que d'ajouter un second panneau. On etend donc DebuggerPanel, au chargement du
greffon, pour qu'il sache dessiner une SECONDE fleche — turquoise (#40b3c0, la
couleur de l'icone Python_tutor_start.svg) — a la ligne du pas courant.

Monkeypatch de CLASSE (pas d'edition de site-packages : survit aux mises a jour de
Spyder, et le comportement de debogage d'origine est intact tant qu'aucune ligne
n'est fixee). DebuggerPanel gagne :
  - set_tutor_line_arrow(n) : fixe (ou efface avec None) la ligne de la fleche ;
  - un paintEvent enveloppe qui, APRES le rendu d'origine, peint la fleche
    turquoise a cette ligne (independamment de l'etat pdb : Python Tutor n'est pas
    le debogueur).
"""

import qtawesome as qta

from qtpy.QtCore import QRect
from qtpy.QtGui import QPainter

from spyder.plugins.debugger.panels.debuggerpanel import DebuggerPanel

# Couleur de l'icone Python_tutor_start.svg.
TUTOR_COLOR = "#40b3c0"
_PATCH_FLAG = "_python_tutor_arrow_installed"


def install_tutor_arrow():
    """Etend DebuggerPanel avec la fleche turquoise (idempotent)."""
    if getattr(DebuggerPanel, _PATCH_FLAG, False):
        return
    # EXACTEMENT la fleche du debogueur, recoloree en turquoise : Spyder definit
    # 'arrow_debugger' comme ('mdi.arrow-right-bold', color=ICON_2, scale_factor=1.5)
    # (utils/icon_manager.py). On reprend le meme glyphe et la meme echelle, seule
    # la couleur change -> forme identique a celle du debogueur.
    tutor_icon = qta.icon("mdi.arrow-right-bold", color=TUTOR_COLOR,
                          scale_factor=1.5)
    orig_paint = DebuggerPanel.paintEvent

    def set_tutor_line_arrow(self, n):
        """Ligne (1-based) ou dessiner la fleche turquoise, ou None pour l'effacer."""
        self._tutor_line_arrow = n
        self.update()

    def paintEvent(self, event):
        # D'abord le rendu d'origine (breakpoints + fleche pdb). Son QPainter est
        # local et detruit au retour ; on peut donc en ouvrir un nouveau ensuite.
        orig_paint(self, event)
        line = getattr(self, "_tutor_line_arrow", None)
        if line is None:
            return
        painter = QPainter(self)
        width = self.sizeHint().width()
        height = self.sizeHint().height()
        for top, line_number, _block in self.editor.visible_blocks:
            if line == line_number:
                tutor_icon.paint(painter, QRect(0, top, width, height))

    DebuggerPanel.set_tutor_line_arrow = set_tutor_line_arrow
    DebuggerPanel.paintEvent = paintEvent
    setattr(DebuggerPanel, _PATCH_FLAG, True)


def set_step_arrow(code_editor, line):
    """Pose (ou efface avec line=None) la fleche turquoise sur `code_editor`.

    Passe par le DebuggerPanel de l'editeur (code_editor.breakpoints_manager.
    debugger_panel), pose la par le plugin Debugger sur chaque editeur de code.
    Retourne le DebuggerPanel utilise (pour pouvoir l'effacer ensuite), ou None si
    l'editeur n'a pas (encore) de gestionnaire de points d'arret.
    """
    if code_editor is None:
        return None
    manager = getattr(code_editor, "breakpoints_manager", None)
    if manager is None:
        return None
    panel = getattr(manager, "debugger_panel", None)
    if panel is None:
        return None
    panel.set_tutor_line_arrow(line)
    return panel
