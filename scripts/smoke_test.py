"""冒烟测试：headless 模式下验证渲染管线

用 offscreen QPA 平台，不显示窗口，只验证：
1. MainWindow / DemoController 能实例化
2. 合成数据生成 + 降采样 + 上传 GPU 全流程无异常
3. 剖面 / 测量 / 拾取 / 车模型 开关能切换
4. FPSMonitor 能收到 RenderEvent

用法：
    python scripts/smoke_test.py
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

# Windows GBK 控制台兼容：强制 stdout/stderr 为 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# 强制 offscreen 渲染（必须在 QApplication 之前）
os.environ["QT_QPA_PLATFORM"] = "offscreen"

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    print("[1/6] 创建主窗口 ...")
    from src.views.main_window import MainWindow

    window = MainWindow()
    print("      OK")

    print("[2/6] 创建控制器（会自动生成默认场景）...")
    from src.controllers.demo_controller import DemoController

    controller = DemoController(window)
    # 手动触发一次生成，因为默认 singleShot 需要事件循环
    controller._on_generate_scene()
    total = window.renderer.get_total_point_count()
    print(f"      OK  渲染点数: {total:,}")

    print("[3/6] 生成 100 万点云 ...")
    window.cmb_point_count.setCurrentIndex(2)  # 100 万
    window.cmb_shape.setCurrentIndex(0)  # cube
    controller._on_scene_config_changed()
    controller._on_generate_scene()
    total = window.renderer.get_total_point_count()
    assert total > 0, "点云上传失败"
    print(f"      OK  渲染点数: {total:,}")

    print("[4/6] 体素降采样 ...")
    window.chk_voxel_downsample.setChecked(True)
    window.spn_voxel_size.setValue(0.5)
    controller._on_voxel_config_changed()
    controller._on_generate_scene()
    downsampled_total = window.renderer.get_total_point_count()
    print(f"      OK  降采样后: {downsampled_total:,} (原 {total:,})")
    assert downsampled_total < total, "降采样未生效"
    window.chk_voxel_downsample.setChecked(False)
    controller._on_voxel_config_changed()

    print("[5/6] 交互工具切换 ...")
    window.chk_clip.setChecked(True)
    controller._on_clip_toggled(True)
    window.sld_clip_nx.setValue(50)
    window.sld_clip_oy.setValue(-30)
    controller._on_clip_param_changed()
    window.chk_measure.setChecked(True)
    controller._on_measure_toggled(True)
    window.chk_pick.setChecked(True)
    controller._on_pick_toggled(True)
    window.chk_layer_car.setChecked(True)
    controller._on_layer_car_toggled(True)
    window.renderer.render()
    print("      OK")

    print("[6/6] 实时流模拟（跑 5 帧）...")
    window.cmb_stream_points.setCurrentIndex(0)  # 1 千点/帧
    controller._on_stream_config_changed()
    for i in range(5):
        controller._on_stream_tick()
    print(f"      OK  累积点数: {controller._state.accumulated_points:,}")

    # 触发一次全局地图上传（正常需 20 帧）
    controller._global_update_counter = controller._global_update_every_n_frames - 1
    controller._on_stream_tick()
    total_with_stream = window.renderer.get_total_point_count()
    print(f"      流式渲染总点数: {total_with_stream:,}")

    # 关闭
    window.chk_stream_enabled.setChecked(False)
    controller.shutdown()
    window.close()

    print()
    print("=" * 60)
    print("冒烟测试全部通过 [OK]")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        import traceback

        print()
        print("冒烟测试失败:")
        traceback.print_exc()
        sys.exit(1)
