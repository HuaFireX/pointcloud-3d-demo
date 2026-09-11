"""Demo 控制器：连接 view 信号与 service，管理场景/流/交互状态

主要职责：
- 场景生成：合成数据 + 可选体素降采样 + 加入渲染器
- 文件加载：真实点云 + 可选降采样 + 加入渲染器
- 实时流：QTimer 驱动雷达单帧生成 + 累积到全局地图
- 交互工具：剖面 / 测量 / 拾取的状态同步
- 图层：全局地图 / 当前帧 / 车模型的可见性
- 状态栏：FPS / 点数 / 内存 定时刷新
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QTimer

from src.models.demo_state import DemoState
from src.services import file_source, pose_source, synthetic_source, voxel_downsample
from src.services.fps_monitor import FPSMonitor
from src.services.pointcloud_renderer import PointcloudRenderer
from src.views.main_window import MainWindow


class DemoController(QObject):
    """主控器"""

    # 叠加图层调色板：白底下区分度高的颜色，循环使用
    OVERLAY_PALETTE = (
        "red", "blue", "green", "orange", "purple",
        "cyan", "magenta", "brown", "olive", "teal",
    )

    def __init__(self, window: MainWindow, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._window = window
        self._renderer: PointcloudRenderer = window.renderer
        self._state = DemoState()

        # 累积的全局地图点（模拟 SLAM 建图过程）
        self._accumulated_points: Optional[np.ndarray] = None
        self._accumulated_scalars: Optional[np.ndarray] = None

        # 文件/目录加载的原始点云缓存（切换着色方式时免重读文件）
        self._loaded_points: Optional[np.ndarray] = None
        self._loaded_scalars: Optional[np.ndarray] = None

        # 叠加图层：name -> (color, checkbox)，每个目录一个独立图层
        self._overlay_layers: dict = {}
        self._overlay_color_idx = 0

        # 真实序列回放：逐帧播放真实 pcd，验证实时建图性能
        self._seq_files: list = []
        self._seq_poses = None
        self._seq_index = 0
        self._seq_playing = False
        self._seq_accum: Optional[np.ndarray] = None
        self._seq_since_global = 0
        self._seq_timer = QTimer(self)
        self._seq_timer.timeout.connect(self._on_seq_tick)

        # 实时流：模拟雷达旋转角度
        self._stream_yaw = 0.0
        self._stream_timer = QTimer(self)
        self._stream_timer.timeout.connect(self._on_stream_tick)

        # 全局地图更新节流：每 N 帧上传一次 GPU，减少带宽
        self._global_update_counter = 0
        self._global_update_every_n_frames = 20

        # FPS 监控
        render_window = self._renderer.get_render_window()
        self._fps_monitor = FPSMonitor(render_window, sample_interval_ms=500, parent=self)
        self._fps_monitor.fps_updated.connect(self._on_fps_updated)

        # 状态栏刷新定时器
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._on_status_tick)
        self._status_timer.start(500)

        # 内存采样缓存
        self._last_memory_mb = 0.0

        self._connect_signals()

        # 初始化：生成默认场景
        QTimer.singleShot(200, self._on_generate_scene)

    # ================================================================
    # 信号连接
    # ================================================================

    def _connect_signals(self) -> None:
        w = self._window

        # 场景生成
        w.btn_generate.clicked.connect(self._on_generate_scene)
        w.cmb_point_count.currentIndexChanged.connect(self._on_scene_config_changed)
        w.cmb_shape.currentIndexChanged.connect(self._on_scene_config_changed)
        w.spn_seed.valueChanged.connect(self._on_scene_config_changed)

        # 实时流
        w.chk_stream_enabled.toggled.connect(self._on_stream_toggled)
        w.cmb_stream_fps.currentIndexChanged.connect(self._on_stream_config_changed)
        w.cmb_stream_points.currentIndexChanged.connect(self._on_stream_config_changed)
        w.chk_accumulate.toggled.connect(self._on_accumulate_toggled)
        w.btn_clear_accumulated.clicked.connect(self._on_clear_accumulated)

        # 真实序列回放
        w.btn_load_seq.clicked.connect(self._on_load_sequence)
        w.btn_play_pause.clicked.connect(self._on_play_pause)
        w.btn_seq_stop.clicked.connect(self._on_seq_stop)
        w.cmb_play_speed.currentIndexChanged.connect(self._on_play_speed_changed)

        # 文件加载
        w.btn_load_file.clicked.connect(self._on_load_file)
        w.btn_load_dir.clicked.connect(self._on_load_directory)
        w.btn_add_dir_layer.clicked.connect(self._on_add_dir_layer)
        w.btn_clear_overlay.clicked.connect(self._on_clear_overlay_layers)

        # 渲染参数
        w.sld_point_size.valueChanged.connect(self._on_point_size_changed)
        w.chk_voxel_downsample.toggled.connect(self._on_voxel_config_changed)
        w.spn_voxel_size.valueChanged.connect(self._on_voxel_config_changed)
        w.chk_edl.toggled.connect(self._on_edl_toggled)
        w.cmb_color_by.currentIndexChanged.connect(self._on_color_by_changed)

        # 图层
        w.chk_layer_global.toggled.connect(self._on_layer_global_toggled)
        w.chk_layer_current.toggled.connect(self._on_layer_current_toggled)
        w.chk_layer_car.toggled.connect(self._on_layer_car_toggled)

        # 交互工具
        w.chk_clip.toggled.connect(self._on_clip_toggled)
        for slider in (
            w.sld_clip_nx, w.sld_clip_ny, w.sld_clip_nz,
            w.sld_clip_ox, w.sld_clip_oy, w.sld_clip_oz,
        ):
            slider.valueChanged.connect(self._on_clip_param_changed)

        w.chk_measure.toggled.connect(self._on_measure_toggled)
        w.chk_pick.toggled.connect(self._on_pick_toggled)

        # 视角
        w.btn_view_iso.clicked.connect(self._renderer.view_isometric)
        w.btn_view_top.clicked.connect(self._renderer.view_top)
        w.btn_view_reset.clicked.connect(self._renderer.reset_camera)

        # 渲染器信号
        self._renderer.measurement_changed.connect(self._on_measurement_changed)
        self._renderer.point_picked.connect(self._on_point_picked)

    # ================================================================
    # 场景生成
    # ================================================================

    def _on_scene_config_changed(self) -> None:
        """仅同步状态，不自动重新生成（避免调 slider 时反复重建千万点）"""
        w = self._window
        self._state.scene.num_points = w.cmb_point_count.currentData()
        self._state.scene.shape = w.cmb_shape.currentData()
        self._state.scene.seed = w.spn_seed.value()

    def _on_generate_scene(self) -> None:
        """按当前配置生成场景"""
        w = self._window
        self._on_scene_config_changed()

        cfg = self._state.scene
        t0 = time.perf_counter()

        points = synthetic_source.generate(cfg.shape, cfg.num_points, seed=cfg.seed)

        gen_elapsed = time.perf_counter() - t0

        # 应用体素降采样
        t1 = time.perf_counter()
        display_points = self._apply_downsample(points, None)
        down_elapsed = time.perf_counter() - t1

        # 清空旧的静态图层，替换 global_map
        self._renderer.remove_pointcloud(PointcloudRenderer.LAYER_GLOBAL_MAP)
        self._renderer.remove_pointcloud(PointcloudRenderer.LAYER_CURRENT_FRAME)
        self._accumulated_points = None
        self._accumulated_scalars = None

        t2 = time.perf_counter()
        self._renderer.add_pointcloud(
            PointcloudRenderer.LAYER_GLOBAL_MAP,
            display_points[0],
            scalars=display_points[1],
            color=self._state.render.global_map_color,
            point_size=self._state.render.point_size,
        )
        upload_elapsed = time.perf_counter() - t2

        self._renderer.set_pointcloud_visible(
            PointcloudRenderer.LAYER_GLOBAL_MAP,
            self._state.layers.global_map_visible,
        )

        # 相机复位
        self._renderer.reset_camera()
        self._renderer.render()

        w.status_bar.showMessage(
            f"生成完成：{cfg.num_points:,} 点 / 形状={cfg.shape} / "
            f"生成={gen_elapsed:.2f}s / 降采样={down_elapsed:.2f}s / "
            f"上传GPU={upload_elapsed:.2f}s / 渲染={display_points[0].shape[0]:,} 点",
            8000,
        )
        self._refresh_status_labels()

    # ================================================================
    # 文件加载
    # ================================================================

    def _on_load_file(self) -> None:
        """加载一个或多个选中的点云文件并合并渲染"""
        paths = self._window.open_file_dialog()
        if not paths:
            return
        self._load_and_render_paths(paths, source_desc=f"{len(paths)} 个文件")

    def _on_load_directory(self) -> None:
        """加载整个目录下的全部点云文件并合并渲染

        若目录含位姿文件（alidarState.txt）且勾选了配准，则把位姿文件从点云
        列表排除，并按"第 i 行位姿 ↔ 第 i 帧点云"做配准后合并。
        """
        directory = self._window.open_directory_dialog()
        if not directory:
            return

        # 位姿文件是 .txt 但并非点云，必须先排除，否则会被误解析成垃圾点
        pose_path = pose_source.find_pose_file(directory)
        exclude = [pose_path] if pose_path is not None else []

        try:
            files = file_source.list_pointcloud_files(directory, exclude=exclude)
        except Exception as e:
            self._window.status_bar.showMessage(f"扫描目录失败: {e}", 8000)
            return

        if not files:
            self._window.status_bar.showMessage(
                f"目录下没有支持的点云文件: {directory}", 8000
            )
            return

        # 超大目录（>5000 帧）且步长为默认 1 时自动设步长，避免全量加载冻结
        auto_stride_note = ""
        if self._window.spn_stride.value() == 1 and len(files) > 5000:
            auto = (len(files) + 4999) // 5000
            self._window.spn_stride.setValue(auto)
            auto_stride_note = f" / 超大目录自动步长 {auto}（可在加载步长改回）"

        # 读取位姿（可选）
        poses = None
        pose_note = ""
        if pose_path is not None and self._window.chk_register.isChecked():
            try:
                _ts, positions, quaternions = pose_source.load_poses(pose_path)
                if positions.shape[0] == len(files):
                    poses = (positions, quaternions)
                    pose_note = f" / 位姿 {positions.shape[0]} 帧已配准"
                else:
                    pose_note = (
                        f" / 位姿行数 {positions.shape[0]} ≠ 点云帧数 {len(files)}，跳过配准"
                    )
            except Exception as e:
                pose_note = f" / 位姿读取失败({e})，跳过配准"

        # 步长抽帧：超长录制（如 1.7 万帧）每 N 帧取 1，位姿同步抽稀保持对齐
        stride = max(1, self._window.spn_stride.value())
        stride_note = auto_stride_note
        if stride > 1:
            files = files[::stride]
            if poses is not None:
                poses = (poses[0][::stride], poses[1][::stride])
                pose_note = f" / 位姿 {poses[0].shape[0]} 帧已配准"
            stride_note += f" / 步长 {stride}（取 {len(files)} 帧）"

        self._window.status_bar.showMessage(f"发现 {len(files)} 个文件，开始加载 ...", 0)
        self._load_and_render_paths(
            files,
            source_desc=f"目录 {os.path.basename(directory)}（{len(files)} 文件）",
            poses=poses,
            pose_note=pose_note + stride_note,
        )

    def _load_and_render_paths(
        self, paths, source_desc: str, poses=None, pose_note: str = ""
    ) -> None:
        """加载多个文件 -> (可选按位姿配准) -> 合并 -> 可选降采样 -> 渲染"""

        def _progress(done: int, count: int, current: str) -> None:
            # 每加载若干文件刷新一次状态栏，避免频繁重绘
            if done % 20 == 0 or done == count:
                self._window.status_bar.showMessage(
                    f"加载中 {done}/{count}: {os.path.basename(current)}", 0
                )

        t0 = time.perf_counter()
        try:
            if poses is not None:
                points, scalars, ok_count, fail_count = self._load_registered(
                    paths, poses, _progress
                )
            else:
                points, scalars, ok_count, fail_count = file_source.load_multiple(
                    paths, progress_callback=_progress
                )
        except Exception as e:
            self._window.status_bar.showMessage(f"加载失败: {e}", 8000)
            return
        load_elapsed = time.perf_counter() - t0

        if points.shape[0] == 0:
            self._window.status_bar.showMessage(
                f"无有效点云数据（成功 {ok_count} / 失败 {fail_count}）", 8000
            )
            return

        # 超点数预算自动降采样，避免千万级点全量渲染导致交互卡顿
        points, scalars, budget_note = self._apply_budget(points, scalars)

        # 缓存原始数据，供切换着色方式时复用（免重读文件）
        self._loaded_points = points
        self._loaded_scalars = scalars

        # 清掉实时流残留，避免与新加载的地图混叠
        self._renderer.remove_pointcloud(PointcloudRenderer.LAYER_CURRENT_FRAME)
        self._accumulated_points = None
        self._accumulated_scalars = None

        # intensity 退化（全同值，如你这批数据全 0）时自动切到 Z 高度着色，否则看不出结构
        hint = ""
        if scalars is not None and scalars.size and float(np.ptp(scalars)) < 1e-9:
            self._window.cmb_color_by.blockSignals(True)
            self._window.cmb_color_by.setCurrentIndex(1)  # Z 高度
            self._window.cmb_color_by.blockSignals(False)
            hint = " / intensity 全同值，已自动切 Z 高度着色"

        self._recolor_global_map(reset_camera=True)

        self._state.loaded_file = source_desc
        self._window.set_loaded_file_label(
            f"{source_desc} / 合并 {points.shape[0]:,} 点"
        )
        fail_note = f" / 失败 {fail_count}" if fail_count else ""
        self._window.status_bar.showMessage(
            f"加载完成 {source_desc} / 成功 {ok_count}{fail_note} / "
            f"渲染 {points.shape[0]:,} 点 / 耗时 {load_elapsed:.2f}s"
            f"{pose_note}{budget_note}{hint}",
            10000,
        )
        self._refresh_status_labels()

    def _apply_budget(self, points, scalars):
        """超点数预算时自动降采样到预算量级，防交互卡顿（表面感知两级法）

        真实扫描是稀疏表面，体素占用率 ∝ 1/voxel²（非体积法的 1/voxel³）。
        先用细 voxel(0.1m) 降采样保留细节；若仍超预算，按 sqrt(n/budget)
        放大 voxel 再降一次，逼近预算而不过杀。
        Returns:
            (points, scalars, note)
        """
        if not self._window.chk_auto_budget.isChecked():
            return points, scalars, ""
        budget = self._window.spn_budget.value() * 10_000
        n = points.shape[0]
        if n <= budget:
            return points, scalars, ""

        fine_voxel = 0.1
        if scalars is not None:
            ds_pts, ds_sca = voxel_downsample.voxel_downsample_with_scalars(
                points, scalars, fine_voxel
            )
        else:
            ds_pts = voxel_downsample.voxel_downsample(points, fine_voxel)
            ds_sca = None

        if ds_pts.shape[0] <= budget:
            note = f" / 预算降采样 voxel={fine_voxel}m -> {ds_pts.shape[0]:,} 点"
            return ds_pts, ds_sca, note

        # 仍超预算：表面占用 ∝ 1/voxel²，按 sqrt 比例放大 voxel
        coarse_voxel = fine_voxel * float(np.sqrt(ds_pts.shape[0] / budget))
        coarse_voxel = max(coarse_voxel, fine_voxel)
        if scalars is not None:
            ds2_pts, ds2_sca = voxel_downsample.voxel_downsample_with_scalars(
                points, scalars, coarse_voxel
            )
        else:
            ds2_pts = voxel_downsample.voxel_downsample(points, coarse_voxel)
            ds2_sca = None
        note = f" / 预算降采样 voxel={coarse_voxel:.2f}m -> {ds2_pts.shape[0]:,} 点"
        return ds2_pts, ds2_sca, note

    def _load_registered(self, paths, poses, progress_callback=None, max_workers: int = 8):
        """按位姿配准加载：第 i 帧点云用第 i 行位姿变换到世界系后合并（线程池并行）

        Returns:
            (points, intensities, ok_count, fail_count) 同 load_multiple
        """
        positions, quaternions = poses
        total = len(paths)
        if total == 0:
            return np.zeros((0, 3), dtype=np.float32), None, 0, 0

        def _load_and_transform(item):
            idx, raw_path = item
            try:
                pts, inten = file_source.load_pointcloud(raw_path)
            except Exception:
                return None
            if pts.shape[0] == 0:
                return (idx, np.zeros((0, 3), dtype=np.float32), None)
            # 雷达系 -> 世界系
            pts = pose_source.transform_points(pts, positions[idx], quaternions[idx])
            return (idx, pts, inten)

        workers = max(1, min(max_workers, total))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_load_and_transform, enumerate(paths)))

        chunks_pts: list[np.ndarray] = []
        chunks_int: list[np.ndarray] = []
        all_have_intensity = True
        ok_count = 0
        fail_count = 0

        for idx, result in enumerate(results):
            if result is None:
                fail_count += 1
            else:
                _i, pts, inten = result
                if pts.shape[0] > 0:
                    chunks_pts.append(pts)
                    if inten is None:
                        all_have_intensity = False
                        chunks_int.append(np.zeros(pts.shape[0], dtype=np.float32))
                    else:
                        chunks_int.append(np.asarray(inten, dtype=np.float32))
                    ok_count += 1

            if progress_callback is not None:
                progress_callback(idx + 1, total, str(paths[idx]))

        if not chunks_pts:
            return np.zeros((0, 3), dtype=np.float32), None, ok_count, fail_count

        merged_pts = np.concatenate(chunks_pts, axis=0).astype(np.float32)
        merged_int: Optional[np.ndarray] = None
        if all_have_intensity and chunks_int:
            merged_int = np.concatenate(chunks_int, axis=0).astype(np.float32)
        return merged_pts, merged_int, ok_count, fail_count

    # ================================================================
    # 多目录叠加图层
    # ================================================================

    def _on_add_dir_layer(self) -> None:
        """把一个目录作为独立叠加图层加入（不覆盖已有图层）

        每个目录用自己的 alidarState.txt 配准（若有），图层名取目录名，
        颜色从调色板循环分配，独立可见性开关。
        """
        directory = self._window.open_directory_dialog()
        if not directory:
            return

        pose_path = pose_source.find_pose_file(directory)
        exclude = [pose_path] if pose_path is not None else []

        try:
            files = file_source.list_pointcloud_files(directory, exclude=exclude)
        except Exception as e:
            self._window.status_bar.showMessage(f"扫描目录失败: {e}", 8000)
            return

        if not files:
            self._window.status_bar.showMessage(
                f"目录下没有支持的点云文件: {directory}", 8000
            )
            return

        poses = None
        pose_note = ""
        if pose_path is not None and self._window.chk_register.isChecked():
            try:
                _ts, positions, quaternions = pose_source.load_poses(pose_path)
                if positions.shape[0] == len(files):
                    poses = (positions, quaternions)
                    pose_note = "（已配准）"
            except Exception:
                poses = None

        # 步长抽帧，位姿同步抽稀
        stride = max(1, self._window.spn_stride.value())
        if stride > 1:
            files = files[::stride]
            if poses is not None:
                poses = (poses[0][::stride], poses[1][::stride])

        if poses is not None:
            points, _scalars, ok_count, fail_count = self._load_registered(files, poses)
        else:
            points, _scalars, ok_count, fail_count = file_source.load_multiple(files)

        if points.shape[0] == 0:
            self._window.status_bar.showMessage(
                f"无有效点云数据（成功 {ok_count} / 失败 {fail_count}）", 8000
            )
            return

        # 超点数预算自动降采样（叠加图层用单色，标量丢弃）
        points, _scalars, budget_note = self._apply_budget(points, None)

        base = os.path.basename(os.path.normpath(directory)) or "layer"
        name = self._unique_layer_name(base)
        color = self.OVERLAY_PALETTE[
            self._overlay_color_idx % len(self.OVERLAY_PALETTE)
        ]
        self._overlay_color_idx += 1

        self._renderer.add_pointcloud(
            name, points, color=color, point_size=self._state.render.point_size
        )
        self._renderer.reset_camera()
        self._renderer.render()

        chk = self._window.add_overlay_toggle(name, color)
        chk.toggled.connect(self._make_overlay_toggle_handler(name))
        self._overlay_layers[name] = (color, chk)

        self._window.status_bar.showMessage(
            f"叠加图层 {name}{pose_note} / {points.shape[0]:,} 点 / 颜色 {color}{budget_note}",
            8000,
        )
        self._refresh_status_labels()

    def _make_overlay_toggle_handler(self, layer_name: str):
        """生成图层可见性开关的槽函数（避免 lambda）"""

        def handler(visible: bool) -> None:
            self._renderer.set_pointcloud_visible(layer_name, visible)

        return handler

    def _unique_layer_name(self, base: str) -> str:
        """保证图层名唯一（重名目录加序号）"""
        reserved = {
            PointcloudRenderer.LAYER_GLOBAL_MAP,
            PointcloudRenderer.LAYER_CURRENT_FRAME,
            PointcloudRenderer.LAYER_CAR_MODEL,
        }
        existing = reserved | set(self._overlay_layers.keys())
        if base not in existing:
            return base
        i = 2
        while f"{base}({i})" in existing:
            i += 1
        return f"{base}({i})"

    def _on_clear_overlay_layers(self) -> None:
        """移除全部叠加图层"""
        for name, (_color, chk) in list(self._overlay_layers.items()):
            self._renderer.remove_pointcloud(name)
            self._window.remove_overlay_toggle(chk)
        self._overlay_layers.clear()
        self._overlay_color_idx = 0
        self._renderer.render()
        self._window.status_bar.showMessage("叠加图层已清空", 3000)
        self._refresh_status_labels()

    def _prepare_display(self, points, scalars, color_by):
        """按着色方式计算要渲染的 (坐标, 标量)，并应用体素降采样"""
        if color_by == "z":
            sca = np.asarray(points, dtype=np.float32)[:, 2].copy()
        elif color_by == "intensity":
            sca = scalars
        else:
            sca = None

        if sca is not None:
            return self._apply_downsample(points, sca)
        dp, _ = self._apply_downsample(points, None)
        return dp, None

    def _recolor_global_map(self, reset_camera: bool = False) -> None:
        """按当前着色方式重建全局地图图层"""
        if self._loaded_points is None:
            return
        color_by = self._window.cmb_color_by.currentData()
        dp, ds = self._prepare_display(self._loaded_points, self._loaded_scalars, color_by)

        self._renderer.remove_pointcloud(PointcloudRenderer.LAYER_GLOBAL_MAP)
        self._renderer.add_pointcloud(
            PointcloudRenderer.LAYER_GLOBAL_MAP,
            dp,
            scalars=ds,
            color=self._state.render.global_map_color,
            point_size=self._state.render.point_size,
        )
        self._renderer.set_pointcloud_visible(
            PointcloudRenderer.LAYER_GLOBAL_MAP,
            self._state.layers.global_map_visible,
        )
        if reset_camera:
            self._renderer.reset_camera()
        self._renderer.render()

    def _on_color_by_changed(self) -> None:
        self._recolor_global_map(reset_camera=False)

    # ================================================================
    # 实时流
    # ================================================================

    def _on_stream_toggled(self, enabled: bool) -> None:
        self._state.stream.enabled = enabled
        if enabled:
            fps = self._window.cmb_stream_fps.currentData()
            self._stream_timer.start(max(int(1000 / fps), 1))
            self._window.status_bar.showMessage(f"实时流已启动，{fps} Hz", 3000)
        else:
            self._stream_timer.stop()
            self._window.status_bar.showMessage("实时流已停止", 3000)

    def _on_stream_config_changed(self) -> None:
        self._state.stream.fps = self._window.cmb_stream_fps.currentData()
        self._state.stream.points_per_frame = self._window.cmb_stream_points.currentData()
        if self._state.stream.enabled:
            self._stream_timer.start(max(int(1000 / self._state.stream.fps), 1))

    def _on_accumulate_toggled(self, enabled: bool) -> None:
        self._state.stream.accumulate = enabled

    def _on_clear_accumulated(self) -> None:
        """清空累积的全局地图（保留场景生成的初始图层不受影响）"""
        self._accumulated_points = None
        self._accumulated_scalars = None
        self._renderer.remove_pointcloud(PointcloudRenderer.LAYER_GLOBAL_MAP)
        # 如果之前是场景生成的图层，需要提示用户
        self._window.status_bar.showMessage("累积点云已清空", 3000)
        self._refresh_status_labels()

    # ================================================================
    # 真实序列回放（逐帧播放真实 pcd，验证实时建图性能）
    # ================================================================

    def _on_load_sequence(self) -> None:
        """加载一个目录作为回放序列（只记文件列表+位姿，不一次性渲染）"""
        directory = self._window.open_directory_dialog()
        if not directory:
            return

        pose_path = pose_source.find_pose_file(directory)
        exclude = [pose_path] if pose_path is not None else []
        try:
            files = file_source.list_pointcloud_files(directory, exclude=exclude)
        except Exception as e:
            self._window.status_bar.showMessage(f"扫描目录失败: {e}", 8000)
            return
        if not files:
            self._window.status_bar.showMessage(
                f"目录下没有支持的点云文件: {directory}", 8000
            )
            return

        poses = None
        pose_note = ""
        if pose_path is not None and self._window.chk_register.isChecked():
            try:
                _ts, positions, quaternions = pose_source.load_poses(pose_path)
                if positions.shape[0] == len(files):
                    poses = (positions, quaternions)
                    pose_note = "（已配准）"
            except Exception:
                poses = None

        stride = max(1, self._window.spn_stride.value())
        if stride > 1:
            files = files[::stride]
            if poses is not None:
                poses = (poses[0][::stride], poses[1][::stride])

        # 停掉正在进行的回放，重置状态
        self._seq_timer.stop()
        self._seq_playing = False
        self._seq_files = files
        self._seq_poses = poses
        self._seq_index = 0
        self._seq_accum = None
        self._seq_since_global = 0

        self._renderer.remove_pointcloud(PointcloudRenderer.LAYER_GLOBAL_MAP)
        self._renderer.remove_pointcloud(PointcloudRenderer.LAYER_CURRENT_FRAME)
        self._renderer.render()

        self._window.btn_play_pause.setEnabled(True)
        self._window.btn_play_pause.setText("播放")
        self._window.btn_seq_stop.setEnabled(True)
        self._window.lbl_seq_progress.setText(f"帧: 0/{len(files)}")
        self._window.status_bar.showMessage(
            f"回放序列已加载: {len(files)} 帧{pose_note}"
            f"{'（步长 ' + str(stride) + '）' if stride > 1 else ''}，点播放开始",
            8000,
        )

    def _on_play_pause(self) -> None:
        if not self._seq_files:
            return
        if self._seq_playing:
            self._seq_timer.stop()
            self._seq_playing = False
            self._window.btn_play_pause.setText("播放")
        else:
            if self._seq_index >= len(self._seq_files):
                # 播完了再点播放 = 从头开始
                self._seq_index = 0
                self._seq_accum = None
                self._seq_since_global = 0
                self._renderer.remove_pointcloud(PointcloudRenderer.LAYER_GLOBAL_MAP)
            self._seq_playing = True
            self._window.btn_play_pause.setText("暂停")
            if self._seq_index == 0:
                self._renderer.reset_camera()
            self._restart_seq_timer()

    def _on_play_speed_changed(self) -> None:
        if self._seq_playing:
            self._restart_seq_timer()

    def _restart_seq_timer(self) -> None:
        """按 录制帧率(10Hz) x 倍率 重启回放定时器"""
        base_hz = 10.0
        speed = float(self._window.cmb_play_speed.currentData() or 1.0)
        interval = max(int(1000.0 / (base_hz * speed)), 10)
        self._seq_timer.start(interval)

    def _on_seq_stop(self) -> None:
        self._seq_timer.stop()
        self._seq_playing = False
        self._seq_index = 0
        self._seq_accum = None
        self._seq_since_global = 0
        self._renderer.remove_pointcloud(PointcloudRenderer.LAYER_CURRENT_FRAME)
        self._renderer.remove_pointcloud(PointcloudRenderer.LAYER_GLOBAL_MAP)
        self._renderer.render()
        self._window.btn_play_pause.setText("播放")
        self._window.lbl_seq_progress.setText(f"帧: 0/{len(self._seq_files)}")

    def _on_seq_tick(self) -> None:
        """回放单帧：读盘 -> 配准 -> 当前帧图层 + 累积全局地图（节流）"""
        total = len(self._seq_files)
        if self._seq_index >= total:
            self._seq_timer.stop()
            self._seq_playing = False
            self._window.btn_play_pause.setText("播放")
            self._window.status_bar.showMessage(f"回放完成: {total} 帧", 5000)
            return

        idx = self._seq_index
        try:
            pts, _inten = file_source.load_pointcloud(self._seq_files[idx])
        except Exception:
            pts = None

        if pts is not None and pts.shape[0] > 0:
            if self._seq_poses is not None:
                pts = pose_source.transform_points(
                    pts, self._seq_poses[0][idx], self._seq_poses[1][idx]
                )

            # 当前帧图层：点数少（~2k），每帧 remove+add 开销可忽略
            self._renderer.remove_pointcloud(PointcloudRenderer.LAYER_CURRENT_FRAME)
            self._renderer.add_pointcloud(
                PointcloudRenderer.LAYER_CURRENT_FRAME,
                pts,
                color=self._state.render.current_frame_color,
                point_size=max(self._state.render.point_size, 3.0),
            )
            self._renderer.set_pointcloud_visible(
                PointcloudRenderer.LAYER_CURRENT_FRAME,
                self._state.layers.current_frame_visible,
            )

            # 累积到全局地图，每 20 帧节流重建一次
            if self._window.chk_accumulate.isChecked():
                if self._seq_accum is None:
                    self._seq_accum = pts.copy()
                else:
                    self._seq_accum = np.concatenate([self._seq_accum, pts], axis=0)
                self._seq_since_global += 1
                if self._seq_since_global >= 20:
                    self._seq_since_global = 0
                    self._renderer.remove_pointcloud(PointcloudRenderer.LAYER_GLOBAL_MAP)
                    self._renderer.add_pointcloud(
                        PointcloudRenderer.LAYER_GLOBAL_MAP,
                        self._seq_accum,
                        color=self._state.render.global_map_color,
                        point_size=self._state.render.point_size,
                    )
                    self._renderer.set_pointcloud_visible(
                        PointcloudRenderer.LAYER_GLOBAL_MAP,
                        self._state.layers.global_map_visible,
                    )

        self._renderer.render()
        self._seq_index += 1
        self._window.lbl_seq_progress.setText(f"帧: {self._seq_index}/{total}")

    def _on_stream_tick(self) -> None:
        """实时流单帧回调"""
        cfg = self._state.stream
        render_cfg = self._state.render

        # 生成一帧雷达扫描
        frame_points = synthetic_source.generate_lidar_frame(
            center=np.asarray(cfg.center, dtype=np.float32),
            n_points=cfg.points_per_frame,
            yaw=self._stream_yaw,
        )
        self._stream_yaw += 0.05  # 每帧转 ~3°

        # 更新当前帧图层
        display_frame, _ = self._apply_downsample(frame_points, None)
        if self._renderer.get_point_count(PointcloudRenderer.LAYER_CURRENT_FRAME) == 0:
            self._renderer.add_pointcloud(
                PointcloudRenderer.LAYER_CURRENT_FRAME,
                display_frame,
                color=render_cfg.current_frame_color,
                point_size=max(render_cfg.point_size, 3.0),
            )
        else:
            self._renderer.update_pointcloud(
                PointcloudRenderer.LAYER_CURRENT_FRAME, display_frame
            )
        self._renderer.set_pointcloud_visible(
            PointcloudRenderer.LAYER_CURRENT_FRAME,
            self._state.layers.current_frame_visible,
        )

        # 累积到全局地图
        if cfg.accumulate:
            if self._accumulated_points is None:
                self._accumulated_points = frame_points.copy()
            else:
                self._accumulated_points = np.concatenate(
                    [self._accumulated_points, frame_points], axis=0
                )

            # 上限保护：超过 max_accumulated 时丢弃最早的点
            if self._accumulated_points.shape[0] > cfg.max_accumulated:
                self._accumulated_points = self._accumulated_points[-cfg.max_accumulated:]

            # 节流：每 N 帧才上传全局地图到 GPU
            self._global_update_counter += 1
            if self._global_update_counter >= self._global_update_every_n_frames:
                self._global_update_counter = 0
                display_global, _ = self._apply_downsample(self._accumulated_points, None)

                # 累积点数逐帧增长，pv.PolyData.points 赋值不会重建顶点单元
                # 因此这里用 remove + add 重建图层（每 N 帧一次，节流后可接受）
                # 若需要更高性能，可预分配 max_accumulated buffer + in-place 写入
                self._renderer.remove_pointcloud(PointcloudRenderer.LAYER_GLOBAL_MAP)
                self._renderer.add_pointcloud(
                    PointcloudRenderer.LAYER_GLOBAL_MAP,
                    display_global,
                    color=render_cfg.global_map_color,
                    point_size=render_cfg.point_size,
                )
                self._renderer.set_pointcloud_visible(
                    PointcloudRenderer.LAYER_GLOBAL_MAP,
                    self._state.layers.global_map_visible,
                )

        self._renderer.render()
        self._state.accumulated_points = (
            0 if self._accumulated_points is None else int(self._accumulated_points.shape[0])
        )

    # ================================================================
    # 渲染参数
    # ================================================================

    def _on_point_size_changed(self, value: int) -> None:
        self._window.lbl_point_size.setText(str(value))
        self._state.render.point_size = float(value)
        layer_names = [
            PointcloudRenderer.LAYER_GLOBAL_MAP,
            PointcloudRenderer.LAYER_CURRENT_FRAME,
        ]
        layer_names.extend(self._overlay_layers.keys())
        for layer_name in layer_names:
            self._renderer.set_point_size(layer_name, float(value))

    def _on_voxel_config_changed(self) -> None:
        self._state.render.voxel_downsample = self._window.chk_voxel_downsample.isChecked()
        self._state.render.voxel_size = float(self._window.spn_voxel_size.value())

    def _on_edl_toggled(self, enabled: bool) -> None:
        self._state.render.edl_enabled = enabled
        self._renderer.set_edl_enabled(enabled)

    def _apply_downsample(
        self, points: np.ndarray, scalars: Optional[np.ndarray]
    ) -> tuple[np.ndarray, Optional[np.ndarray]]:
        """按当前配置应用体素降采样"""
        cfg = self._state.render
        if not cfg.voxel_downsample or cfg.voxel_size <= 0:
            return points, scalars

        if scalars is None:
            return voxel_downsample.voxel_downsample(points, cfg.voxel_size), None
        return voxel_downsample.voxel_downsample_with_scalars(points, scalars, cfg.voxel_size)

    # ================================================================
    # 图层可见性
    # ================================================================

    def _on_layer_global_toggled(self, visible: bool) -> None:
        self._state.layers.global_map_visible = visible
        self._renderer.set_pointcloud_visible(PointcloudRenderer.LAYER_GLOBAL_MAP, visible)

    def _on_layer_current_toggled(self, visible: bool) -> None:
        self._state.layers.current_frame_visible = visible
        self._renderer.set_pointcloud_visible(PointcloudRenderer.LAYER_CURRENT_FRAME, visible)

    def _on_layer_car_toggled(self, visible: bool) -> None:
        self._state.layers.car_model_visible = visible
        if visible:
            # 用简单立方体占位表示 AGV，实际集成时替换为真实 .obj/.stl
            import pyvista as pv

            car_mesh = pv.Box(bounds=(-0.6, 0.6, -0.4, 0.4, 0.0, 0.4))
            self._renderer.add_mesh_model(
                PointcloudRenderer.LAYER_CAR_MODEL,
                car_mesh,
                color=self._state.render.car_model_color,
            )
        else:
            self._renderer.remove_mesh_model(PointcloudRenderer.LAYER_CAR_MODEL)
        self._renderer.render()

    # ================================================================
    # 剖面
    # ================================================================

    def _on_clip_toggled(self, enabled: bool) -> None:
        self._state.interaction.clip_enabled = enabled
        self._renderer.set_clip_enabled(enabled)
        self._on_clip_param_changed()

    def _on_clip_param_changed(self) -> None:
        normal = self._window.get_clip_normal()
        origin = self._window.get_clip_origin()
        self._state.interaction.clip_normal = normal
        self._state.interaction.clip_origin = origin
        self._renderer.set_clip_plane(np.asarray(normal), np.asarray(origin))

    # ================================================================
    # 测量 & 拾取
    # ================================================================

    def _on_measure_toggled(self, enabled: bool) -> None:
        self._state.interaction.measure_enabled = enabled
        self._renderer.set_measure_enabled(enabled)
        if not enabled:
            self._window.set_measurement_label(None)

    def _on_measurement_changed(self, distance: float) -> None:
        self._state.interaction.last_measurement = distance
        self._window.set_measurement_label(distance)

    def _on_pick_toggled(self, enabled: bool) -> None:
        self._state.interaction.pick_enabled = enabled
        self._renderer.set_pick_enabled(enabled)
        if not enabled:
            self._window.set_picked_label(None)

    def _on_point_picked(self, point) -> None:
        pt = tuple(float(v) for v in np.asarray(point).ravel()[:3])
        self._state.interaction.last_picked_point = pt
        self._window.set_picked_label(pt)

    # ================================================================
    # 状态栏刷新
    # ================================================================

    def _on_fps_updated(self, fps: float) -> None:
        self._window.set_fps_label(fps)

    def _on_status_tick(self) -> None:
        self._refresh_status_labels()

    def _refresh_status_labels(self) -> None:
        total = self._renderer.get_total_point_count()
        self._state.displayed_points = total
        self._window.set_points_label(total)
        self._window.set_memory_label(self._get_process_memory_mb())

    @staticmethod
    def _get_process_memory_mb() -> float:
        """获取当前进程 RSS 内存（MB），跨平台"""
        try:
            import psutil  # type: ignore

            return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
        except Exception:
            pass

        # fallback：Windows 走 tasklist，Linux 走 /proc/self/status
        try:
            if os.name == "nt":
                # 简化处理：读 /proc 不可用时返回 0
                return 0.0
            with open("/proc/self/status", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        kb = float(line.split()[1])
                        return kb / 1024.0
        except Exception:
            pass
        return 0.0

    # ================================================================
    # 清理
    # ================================================================

    def shutdown(self) -> None:
        """关闭窗口前释放资源"""
        self._stream_timer.stop()
        self._status_timer.stop()
        if self._fps_monitor is not None:
            self._fps_monitor.stop()
