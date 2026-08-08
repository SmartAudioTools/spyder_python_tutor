#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Driver de trace : execute un fichier sous pg_logger et ecrit la trace JSON.

    python run_trace.py <fichier_source.py> <sortie.json>

Lance dans un process separe par tracer.py (avec le python du venv Spyder). Ajoute
ce dossier (backend/) a sys.path pour importer pg_logger + pg_encoder, VENDORES
ici depuis Online Python Tutor (voir VENDORING.txt). Ecrit dans <sortie.json> un
objet {"code": "<source>", "trace": [ ...pas... ]}, exactement ce qu'attend
ExecutionVisualizer cote frontend.

NOTE : pg_logger execute le code de l'eleve DANS CE PROCESS, sous bdb, en bac a
sable (I/O limitees, imports restreints, plafond de pas). C'est voulu : Python
Tutor vise de petits extraits pedagogiques deterministes. L'isolation vis-a-vis
de Spyder vient du fait que ce driver tourne dans un QProcess distinct.
"""

import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Compat Python 3.12 : pg_logger (v5-unity) fait « import imp », module retire de
# la stdlib en 3.12. Il ne s'en sert que pour imp.new_module(). On injecte un shim
# minimal AVANT d'importer pg_logger, plutot que de modifier le fichier vendore.
if "imp" not in sys.modules:
    try:
        import imp  # noqa: F401
    except ImportError:
        _imp = types.ModuleType("imp")
        _imp.new_module = lambda name: types.ModuleType(name)
        sys.modules["imp"] = _imp


def main(argv):
    if len(argv) != 3:
        sys.stderr.write("usage: run_trace.py <source.py> <sortie.json>\n")
        return 2
    source_path, out_path = argv[1], argv[2]

    try:
        with open(source_path, "r", encoding="utf-8") as f:
            script_str = f.read()
    except OSError as exc:
        sys.stderr.write("Lecture impossible : {}\n".format(exc))
        return 1

    try:
        import pg_logger  # vendore, voir VENDORING.txt
    except ImportError as exc:
        import traceback
        sys.stderr.write(
            "Import de pg_logger impossible ({}). Backend absent ou incompatible "
            "— voir VENDORING.txt.\n".format(exc))
        traceback.print_exc()
        return 1

    result_holder = {}

    def finalizer(input_code, output_trace):
        # Signature du finalizer OPT : (code source, liste des pas).
        result_holder["obj"] = {"code": input_code, "trace": output_trace}
        return result_holder["obj"]

    # L'API a legerement varie selon les versions d'OPT ; on tente la forme
    # v5-unity (exec_script_str_local) puis une forme plus ancienne.
    #   cumulative_mode=False : chaque pas est un instantane (mode « pas a pas »,
    #     defaut de pythontutor.com), pas un cumul.
    #   heap_primitives=False : les scalaires restent en ligne, pas boxes.
    try:
        pg_logger.exec_script_str_local(
            script_str, None, False, False, finalizer)
    except AttributeError:
        # Forme historique : exec_script_str(script, raw_input_json, options, finalizer)
        pg_logger.exec_script_str(script_str, None, False, finalizer)

    obj = result_holder.get("obj")
    if obj is None:
        sys.stderr.write("pg_logger n'a produit aucune trace.\n")
        return 1

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
