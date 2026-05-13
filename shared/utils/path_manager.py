"""
统一路径管理模块

在所有模块导入前，于入口文件调用 setup_paths()

使用方法:
    from shared.utils.path_manager import setup_paths
    setup_paths()
"""
import sys
from pathlib import Path

# 项目根目录（基于此文件位置推导）
# path_manager.py 位于：shared/utils/path_manager.py
# 所以 parents[2] 是项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 需要添加到 sys.path 的目录
PATHS_TO_ADD = [
    str(PROJECT_ROOT),                          # 项目根目录
    str(PROJECT_ROOT / "deepear" / "src"),      # DeepEar 源码
    str(PROJECT_ROOT / "deepfund" / "src"),     # DeepFund 源码
    str(PROJECT_ROOT / "shared"),               # Shared 模块
    str(PROJECT_ROOT / "backtest"),             # Backtest 模块
]

# 标记是否已经初始化
_initialized = False


def setup_paths():
    """
    Add project paths to sys.path once.
    
    在入口文件（run.py, 测试配置等）中调用此函数。
    只添加不存在的路径，避免重复。
    """
    global _initialized
    
    if _initialized:
        return  # 已经初始化过，直接返回
    
    for path in PATHS_TO_ADD:
        if path not in sys.path:
            sys.path.insert(0, path)
    
    _initialized = True


def get_project_root() -> Path:
    """获取项目根目录路径."""
    return PROJECT_ROOT


def get_deepear_src() -> Path:
    """获取 DeepEar 源码路径."""
    return PROJECT_ROOT / "deepear" / "src"


def get_deepfund_src() -> Path:
    """获取 DeepFund 源码路径."""
    return PROJECT_ROOT / "deepfund" / "src"


def get_backtest_dir() -> Path:
    """获取 Backtest 目录路径."""
    return PROJECT_ROOT / "backtest"
