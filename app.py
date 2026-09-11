"""Demo 顶层入口：把项目根加入 sys.path 后调用 bootstrap.run()"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from src.bootstrap import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
