"""
pip 服务测试 conftest

生产代码（pip_installer.py）已改为包限定导入
（services.pip.*），通过 `from services.pip.pip_installer import ...` 可正常导入。

测试文件中直接 import version_resolver / models
等内部模块（裸名），需要把 services/pip/ 加入 sys.path 才能找到。
conftest 在测试收集阶段最早执行，是放置此操作的标准位置。
"""
import sys
import os

_PIP_SERVICE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../services/pip")
)
if _PIP_SERVICE_DIR not in sys.path:
    sys.path.insert(0, _PIP_SERVICE_DIR)
