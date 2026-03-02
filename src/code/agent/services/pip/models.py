from dataclasses import dataclass, asdict
from typing import List


@dataclass
class InstallRecord:
    """用于记录 install.py 脚本的执行结果"""
    node_name: str
    script_name: str = "install.py"
    duration: float = 0
    success: bool = True
    error_msg: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class DependencyInstallRecord:
    """用于记录 pip install -r 批量安装的结果"""
    requirements_txt: str  # 实际安装的 requirements.txt 内容
    duration: float = 0
    success: bool = True
    error_msg: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class DependencyInfo:
    """依赖包信息"""
    package_name: str      # 基础包名（不含版本）
    version_spec: str      # 版本规范（如 ==1.0.0, >=1.5.0）
    original_line: str     # 原始行内容
    source_nodes: List[str]  # 来源插件列表
