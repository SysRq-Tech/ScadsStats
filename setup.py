#!/usr/bin/env python
# coding=utf-8

"""
Installing the program. Run `python setup.py` to install.
"""

from distutils.core import setup
import sys

long_desc = """============
Requirements
============
* **Python** >= 3.3
* **Kivy** >= 1.8.0

==============
Used libraries
==============
* `vk <https://github.com/dimka665/vk>`_
* `gettext_windows <https://launchpad.net/gettext-py-windows>`_
* `requests <http://python-requests.org>`_
* Modified `KivyCalendar <https://bitbucket.org/xxblx/kivycalendar>`_

==========
Help us
==========
* `Translate <https://poeditor.com/join/project/cq07DODUUL>`_ the program to your language
* `Improve <https://github.com/SysRq-Tech/ScadsStats>`_ the code
* `Join <http://vk.com/sysrqtech>`_ VK community
"""

requirements = ["vk", "requests"]
if sys.platform.startswith("win"):
    requirements.extend(["gettext_windows", "wheel", "docutils", "pygments", "pypiwin32",
                         "kivy.deps.sdl2", "kivy.deps.glew", "kivy"])

setup(name="ScadsStats",
      version="1.0.1",
      description="Finding active users on VK walls",
      long_description=long_desc,
      author="Matvey Vyalkov",
      author_email="CyberTailor@gmail.com",
      url="https://github.com/SysRq-Tech/ScadsStats",
      license="GNU GPL v3",
      scripts=["vk-stats"],
      packages=["vk_stats", "vk_stats.KivyCalendar"],
      package_data={"": ["interface.kv"],
                    "vk_stats": ["html/*.*",
                                 "images/*.*", "images/48/*.*", "images/128/*.*",
                                 "docs/*.*", "docs/credits/*.*",
                                 "locale/ru_RU/LC_MESSAGES/*.*", "locale/uk_UA/LC_MESSAGES/*.*"]},
      requires=requirements)
