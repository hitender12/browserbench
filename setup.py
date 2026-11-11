"""Packaging extras for BrowserBench (see pyproject.toml).

The bundled tasks, agents, and demo live at the repo root, outside the
``browserbench`` package, so ``package_data`` cannot ship them. They are
installed as data files instead (``<venv>/share/browserbench/...``), and
``browserbench.__main__._bundled`` falls back to that location when the
checkout copy is not present — so ``browserbench run`` works after a
non-editable ``pip install``, outside a checkout.
"""

import glob
import os

from setuptools import setup

data_files = []
for src_dir in ("tasks", "agents"):
    for path in sorted(glob.glob(os.path.join(src_dir, "**", "*"),
                                 recursive=True)):
        if os.path.isfile(path):
            data_files.append(
                (os.path.join("share", "browserbench",
                              os.path.dirname(path)), [path]))
data_files.append((os.path.join("share", "browserbench"), ["demo.py"]))

setup(data_files=data_files)
