# coding=utf-8

import os
import sys
import locale
import gettext

locale.setlocale(locale.LC_ALL, "")

SCRIPTDIR = os.path.abspath(os.path.dirname(__file__))  # directory with this script
HOME = os.path.expanduser("~")  # user's home
LOCALE_DIR = SCRIPTDIR + "/locale/"
APP = "vk_stats"
mustdie = sys.platform.startswith("win")

if mustdie:
    import gettext_windows
if mustdie:
    lang = gettext_windows.get_language()
    translation = gettext.translation(APP, localedir=LOCALE_DIR, languages=lang, fallback=True)
else:
    translation = gettext.translation(APP, localedir=LOCALE_DIR, fallback=True)
_ = translation.gettext
