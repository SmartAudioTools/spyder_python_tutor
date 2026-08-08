# -*- coding: utf-8 -*-
"""Backend de trace : lance pg_logger sur un fichier dans un process separe.

pg_logger (Online Python Tutor, vendore dans backend/) execute le code de l'eleve
sous le controle du debogueur `bdb` et produit une TRACE : la liste de tous les
pas d'execution (pile d'appels, objets du tas, references) au format JSON
    {"code": "<source>", "trace": [ {..pas..}, {..pas..}, ... ]}

On lance le driver backend/run_trace.py avec le python du venv Spyder (sys.executable,
le meme que celui du greffon) dans un QProcess :
  - non bloquant pour l'UI ;
  - isole une boucle infinie / un plantage du code trace du process de Spyder ;
  - espace de noms neuf.

Le widget recoit la trace decodee (dict) par sig_trace_ready et en tire lui-meme
len(trace) et la ligne de chaque pas : c'est le Python qui pilote l'avancement.
"""

import json
import os
import sys
import tempfile

from qtpy.QtCore import QObject, QProcess, Signal

_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "backend")
_RUN_TRACE = os.path.join(_BACKEND_DIR, "run_trace.py")


class TutorRunner(QObject):
    """Lance pg_logger sur un fichier et renvoie la trace decodee.

    Les signaux permettent au widget d'afficher l'etat sans que ce module ne
    connaisse quoi que ce soit de l'UI.
    """

    sig_started = Signal(str)       # chemin du fichier trace
    sig_output = Signal(str)        # ligne de sortie (stdout/stderr fusionnes)
    sig_trace_ready = Signal(dict)  # trace decodee {"code":..., "trace":[...]}
    sig_failed = Signal(str)        # message d'erreur
    sig_finished = Signal()         # fin du cycle (succes OU echec)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = None
        self._out_path = None
        self._filename = None

    def is_running(self):
        return (self._proc is not None
                and self._proc.state() != QProcess.NotRunning)

    def trace_file(self, filename):
        """Trace `filename` avec pg_logger, dans un process separe."""
        if self.is_running():
            self.sig_failed.emit("Un tracage est deja en cours.")
            return
        if not filename or not os.path.isfile(filename):
            self.sig_failed.emit("Fichier introuvable : {!r}".format(filename))
            return
        if not os.path.isfile(_RUN_TRACE):
            self.sig_failed.emit(
                "Backend absent : {} n'existe pas encore.\n"
                "pg_logger n'a pas ete vendore — voir backend/VENDORING.txt."
                .format(_RUN_TRACE))
            return

        self._filename = filename
        self._out_path = os.path.join(
            tempfile.gettempdir(),
            "pytutor_{}.json".format(
                os.path.splitext(os.path.basename(filename))[0]))

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.setWorkingDirectory(os.path.dirname(filename) or os.getcwd())
        proc.readyReadStandardOutput.connect(self._drain_output)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(
            lambda err: self.sig_failed.emit(
                "Echec du lancement du backend : {}".format(err)))
        self._proc = proc

        args = [_RUN_TRACE, filename, self._out_path]
        self.sig_started.emit(filename)
        self.sig_output.emit("$ " + " ".join([sys.executable] + args))
        proc.start(sys.executable, args)

    def _drain_output(self):
        proc = self.sender()
        if proc is None:
            return
        data = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in data.splitlines():
            self.sig_output.emit(line)

    def _on_finished(self, code, status):
        self._proc = None
        if code != 0 or not os.path.isfile(self._out_path):
            self.sig_failed.emit(
                "pg_logger a echoue (code {}). Voir le journal.".format(code))
            self.sig_finished.emit()
            return
        try:
            with open(self._out_path, "r", encoding="utf-8") as f:
                trace_obj = json.load(f)
        except (OSError, ValueError) as exc:
            self.sig_failed.emit("Trace illisible : {}".format(exc))
            self.sig_finished.emit()
            return
        self.sig_trace_ready.emit(trace_obj)
        self.sig_finished.emit()

    def stop(self):
        """Tue le process de trace en cours (fermeture du greffon)."""
        if self._proc is not None:
            proc = self._proc
            self._proc = None
            proc.kill()
            proc.waitForFinished(2000)
            proc.deleteLater()

