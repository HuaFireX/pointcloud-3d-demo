"""环境与依赖自检

用法：
    python scripts/check_env.py

会检查：
1. Python 版本（推荐 3.10~3.12）
2. PySide6 / numpy / vtk / pyvista / pyvistaqt 是否安装及版本
3. OpenGL 渲染窗口能否创建（VTK 层面）
4. 项目源码目录是否可导入
"""

from __future__ import annotations

import sys
from pathlib import Path


REQUIRED_PYTHON = (3, 10)
MAX_TESTED_PYTHON = (3, 12)


def _print_header(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def _check_python() -> bool:
    _print_header("[1/4] Python 版本")
    v = sys.version_info
    print(f"当前: {v.major}.{v.minor}.{v.micro}  ({sys.executable})")
    if (v.major, v.minor) < REQUIRED_PYTHON:
        print(f"错误: 需要 Python >= {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}")
        return False
    if (v.major, v.minor) > MAX_TESTED_PYTHON:
        print(
            f"警告: Python {v.major}.{v.minor} 尚未在 vtk/pyvista 官方 wheel 覆盖范围内，"
            "如遇安装失败请切换到 3.10~3.12"
        )
    else:
        print("OK")
    return True


def _check_packages() -> bool:
    _print_header("[2/4] 依赖包")
    all_ok = True

    packages = [
        ("PySide6", "PySide6"),
        ("numpy", "numpy"),
        ("vtk", "vtk"),
        ("pyvista", "pyvista"),
        ("pyvistaqt", "pyvistaqt"),
    ]

    for name, module in packages:
        try:
            mod = __import__(module)
            version = getattr(mod, "__version__", None)
            if version is None and module == "vtk":
                try:
                    from vtkmodules.vtkCommonCore import vtkVersion

                    version = vtkVersion.GetVTKVersion()
                except Exception:
                    version = "unknown"
            print(f"  {name:<12} OK  version={version}")
        except ImportError as e:
            print(f"  {name:<12} 缺失  ({e})")
            all_ok = False
        except Exception as e:
            print(f"  {name:<12} 异常  ({type(e).__name__}: {e})")
            all_ok = False

    if not all_ok:
        print()
        print("修复方式：")
        print("  pip install -r requirements.txt")
    return all_ok


def _check_opengl() -> bool:
    _print_header("[3/4] OpenGL / VTK 渲染窗口")
    try:
        import vtk

        render_window = vtk.vtkRenderWindow()
        render_window.SetOffScreenRendering(1)  # 无窗口模式测试
        render_window.SetSize(64, 64)
        renderer = vtk.vtkRenderer()
        render_window.AddRenderer(renderer)
        render_window.Render()

        # 查询 OpenGL 版本
        try:
            from vtkmodules.vtkRenderingOpenGL2 import vtkOpenGLRenderWindow

            if isinstance(render_window, vtkOpenGLRenderWindow):
                gl_version = render_window.GetOpenGLVersionString()
                print(f"  OpenGL 版本: {gl_version.strip() if gl_version else 'unknown'}")
        except Exception:
            pass

        render_window.Finalize()
        del render_window, renderer
        print("  VTK 渲染窗口创建 OK")
        return True
    except Exception as e:
        print(f"  VTK 渲染失败: {type(e).__name__}: {e}")
        print("  可能原因: 显卡驱动过旧 / 无 OpenGL 3.3+ 支持 / 远程桌面模式")
        return False


def _check_project_imports() -> bool:
    _print_header("[4/4] 项目源码可导入性")
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    modules = [
        "src.models.demo_state",
        "src.services.voxel_downsample",
        "src.services.synthetic_source",
        "src.services.file_source",
        "src.services.fps_monitor",
        "src.services.pointcloud_renderer",
        "src.views.main_window",
        "src.controllers.demo_controller",
        "src.bootstrap",
    ]

    all_ok = True
    for mod_name in modules:
        try:
            __import__(mod_name)
            print(f"  {mod_name:<45} OK")
        except Exception as e:
            print(f"  {mod_name:<45} 失败: {type(e).__name__}: {e}")
            all_ok = False
    return all_ok


def main() -> int:
    print("=" * 60)
    print("3D 点云 Demo 环境自检")
    print("=" * 60)

    checks = [
        ("Python 版本", _check_python),
        ("依赖包", _check_packages),
        ("OpenGL", _check_opengl),
        ("项目导入", _check_project_imports),
    ]

    results = []
    for name, fn in checks:
        try:
            ok = fn()
        except Exception as e:
            print(f"检查 {name} 抛异常: {type(e).__name__}: {e}")
            ok = False
        results.append((name, ok))

    _print_header("总结")
    for name, ok in results:
        print(f"  {'OK ' if ok else 'FAIL'}  {name}")

    if all(ok for _, ok in results):
        print()
        print("全部检查通过，运行 python app.py 启动 demo")
        return 0

    print()
    print("存在失败项，请先修复后再运行 demo")
    return 1


if __name__ == "__main__":
    sys.exit(main())
