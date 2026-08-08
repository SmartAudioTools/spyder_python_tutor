# -*- coding: utf-8 -*-
"""Fonction de traduction du greffon.

`spyder.api.translations.get_translation("spyder_python_tutor")` marcherait aussi,
mais tant qu'aucun catalogue .mo n'est fourni elle affiche a chaque import
« Could not load translations for fr ... » - du bruit dans la console a chaque
demarrage de Spyder (meme travers que spyder_line_profiler / spyder_viztracer).

Les libelles sont ecrits directement en francais. On garde l'habillage `_(...)`
pour pouvoir ajouter un catalogue plus tard sans toucher au reste du code.
"""


def _(message):
    return message
