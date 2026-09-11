"""大规模点云性能压测：验证不同点数下的生成 + 上传 + 渲染耗时

headless 模式（offscreen QPA），只测 CPU + GPU 上传耗时，不测交互 FPS。

用法：
    python scripts/perf_test.py
"""

from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["QT_QPA_PLATFORM"] = "offscreen"

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import numpy as np


def get_process_memory_mb() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def bench(renderer, name: str, n_points: int, shape: str, seed: int = 42) -> None:
    from src.services import synthetic_source, voxel_downsample

    mem_before = get_process_memory_mb()

    # 1) 生成
    t0 = time.perf_counter()
    try:
        pts = synthetic_source.generate(shape, n_points, seed=seed)
    except MemoryError as e:
        print(f"\n=== {name}: {n_points:,} 点 / shape={shape} ===")
        print(f"  生成失败（内存不足）: {e}")
        return
    t_gen = time.perf_counter() - t0

    # 2) 上传 GPU（不降采样）
    t0 = time.perf_counter()
    try:
        renderer.remove_pointcloud("bench")
        renderer.add_pointcloud("bench", pts, color="black", point_size=2.0)
        t_upload = time.perf_counter() - t0

        # 3) 强制渲染一帧
        t0 = time.perf_counter()
        renderer.render()
        t_render = time.perf_counter() - t0
    except MemoryError as e:
        print(f"\n=== {name}: {n_points:,} 点 / shape={shape} ===")
        print(f"  生成: {t_gen:.3f} s")
        print(f"  上传 GPU 失败（内存不足）: {e}")
        return

    mem_after = get_process_memory_mb()
    mem_delta = mem_after - mem_before

    # 4) 降采样对比（voxel_size=0.1）
    t0 = time.perf_counter()
    try:
        ds_pts = voxel_downsample.voxel_downsample(pts, 0.1)
        t_down = time.perf_counter() - t0
        down_ok = True
    except MemoryError as e:
        t_down = time.perf_counter() - t0
        ds_pts = None
        down_ok = False
        down_err = str(e)

    if down_ok:
        t0 = time.perf_counter()
        renderer.remove_pointcloud("bench")
        renderer.add_pointcloud("bench", ds_pts, color="black", point_size=2.0)
        renderer.render()
        t_ds_upload_render = time.perf_counter() - t0

    print(f"\n=== {name}: {n_points:,} 点 / shape={shape} ===")
    print(f"  生成:            {t_gen:>7.3f} s")
    print(f"  上传 GPU:        {t_upload:>7.3f} s")
    print(f"  渲染一帧:        {t_render:>7.3f} s")
    print(f"  内存增量:        {mem_delta:>7.1f} MB")
    if down_ok:
        print(f"  体素降采样 0.1m: {t_down:>7.3f} s  ({n_points:,} -> {ds_pts.shape[0]:,})")
        print(f"  降采样后上传+渲染: {t_ds_upload_render:>7.3f} s")
    else:
        print(f"  体素降采样 0.1m: 失败（{down_err}）")

    renderer.remove_pointcloud("bench")


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from src.services.pointcloud_renderer import PointcloudRenderer

    app = QApplication(sys.argv)
    renderer = PointcloudRenderer()
    renderer.resize(800, 600)
    renderer.show()

    # 预热
    renderer.add_pointcloud("warmup", np.random.rand(1000, 3).astype(np.float32))
    renderer.render()
    renderer.remove_pointcloud("warmup")

    print("=" * 60)
    print("大规模点云性能压测（headless）")
    print("=" * 60)
    print(f"初始内存: {get_process_memory_mb():.1f} MB")

    bench(renderer, "T1", 100_000, "cube")
    bench(renderer, "T2", 1_000_000, "cube")
    bench(renderer, "T3", 5_000_000, "room")
    bench(renderer, "T4", 10_000_000, "cube")
    bench(renderer, "T5", 30_000_000, "sphere")

    print(f"\n最终内存: {get_process_memory_mb():.1f} MB")
    print()
    print("=" * 60)
    print("压测完成 [OK]")
    print("=" * 60)

    renderer.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback

        print()
        print("压测失败:")
        traceback.print_exc()
        sys.exit(1)
