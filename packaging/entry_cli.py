# SPDX-License-Identifier: GPL-3.0-or-later
"""打包用的入口：`mcmt-cli.exe`（命令列版，給習慣終端機的人）。"""

import sys

from mcmt.cli.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
