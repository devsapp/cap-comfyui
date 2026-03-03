"""
pip 服务测试 conftest
─────────────────────
pip_installer.py 内部使用无包前缀的 import（如 `from models import ...`），
这是因为运行时 services/pip/ 本身在 sys.path 中。
测试运行时 rootdir 是 src/code/agent，所以要手动把 services/pip/ 加进来。
"""
import sys
import os

_PIP_SERVICE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../services/pip")
)
if _PIP_SERVICE_DIR not in sys.path:
    sys.path.insert(0, _PIP_SERVICE_DIR)
