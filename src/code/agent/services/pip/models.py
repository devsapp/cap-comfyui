from dataclasses import dataclass, field, asdict
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
class DependencyInfo:
    """依赖包信息"""
    package_name: str      # 基础包名（不含版本），已按 PEP 503 规范化
    version_spec: str      # 版本规范（如 ==1.0.0, >=1.5.0）
    original_line: str     # 原始行内容
    source_nodes: List[str]  # 来源插件列表


@dataclass
class DependencyInstallRecord:
    """用于记录两轮批次安装的整体结果"""
    requirements_txt: str = "" # 过滤后实际参与安装的依赖内容
    duration: float = 0
    success: bool = True
    error_msg: str = ""
    problematic_deps: List[DependencyInfo] = field(default_factory=list)  # 黑名单 / git+ / 安装失败的包

    def to_dict(self):
        return asdict(self)
