"""
统一路径管理模块

在所有模块导入前，于入口文件调用 setup_paths()

使用方法:
    from shared.utils.path_manager import setup_paths
    setup_paths()

包名解析规则（重要）:
    多个受管根目录定义了同名顶层包，setup_paths() 以固定顺序消解歧义
    （最终 sys.path 顺序: backtest, deepfund/src, deepear/src, shared,
    PROJECT_ROOT）——即使调用前这些路径已经以其他顺序存在:
    - `agents`（deepfund/src vs deepear/src）: 裸导入恒定解析到
      deepfund/src/agents（分析师注册表）；deepear 侧代码必须使用完整
      路径 `deepear.src.agents.*`。
    - `utils`（deepear/src vs shared/）: 裸导入恒定解析到
      deepear/src/utils（report_agent、search_tools、deepear_client
      依赖此行为）；shared 侧一律使用全限定 `shared.utils.*`。
    - `config`（deepfund/src vs shared/）: 无代码裸导入；一律使用
      全限定路径。
"""
import sys
from pathlib import Path

# 项目根目录（基于此文件位置推导）
# path_manager.py 位于：shared/utils/path_manager.py
# 所以 parents[2] 是项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 需要添加到 sys.path 的目录。列表按 insert(0) 逆序排列——列表中越靠后的
# 条目最终优先级越高。最终 sys.path 顺序（见模块 docstring 的解析规则）:
#   backtest > deepfund/src > deepear/src > shared > PROJECT_ROOT
PATHS_TO_ADD = [
    str(PROJECT_ROOT),                          # 项目根目录
    str(PROJECT_ROOT / "shared"),               # Shared 模块
    str(PROJECT_ROOT / "deepear" / "src"),      # DeepEar 源码（裸 `utils` 归它）
    str(PROJECT_ROOT / "deepfund" / "src"),     # DeepFund 源码（裸 `agents` 归它）
    str(PROJECT_ROOT / "backtest"),             # Backtest 模块
]

# 标记是否已经初始化
_initialized = False


def setup_paths(force: bool = False):
    """
    Put managed project paths on sys.path in canonical order.

    在入口文件（run.py, 测试配置等）中调用此函数。与旧版"跳过已存在路径"
    不同，本函数会将受管路径重排为固定顺序（reorder-if-present），使
    deepfund/src 恒定位于 deepear/src 之前——见模块 docstring 的包名解析
    规则。非受管路径保持原有相对顺序不变。

    Args:
        force: 为 True 时忽略已初始化标记，强制重排（供测试会话钉住
            解析顺序使用）。
    """
    global _initialized

    if _initialized and not force:
        return  # 已经初始化过，直接返回

    # 先移除所有受管路径（无论出现在何处、出现几次），再按固定顺序重新
    # 插入。最终顺序与全新进程首次调用完全一致：
    # backtest, shared, deepfund/src, deepear/src, PROJECT_ROOT, <其余原有项>
    for path in PATHS_TO_ADD:
        while path in sys.path:
            sys.path.remove(path)
    for path in PATHS_TO_ADD:
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
