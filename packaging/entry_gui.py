# SPDX-License-Identifier: GPL-3.0-or-later
"""打包用的入口：`mcmt.exe`（視窗版，沒有黑色命令列視窗）。"""

import sys

from mcmt.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
