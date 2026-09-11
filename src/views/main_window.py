"""主窗口：左侧控制面板 + 右侧 3D 视图 + 底部状态栏

所有控件的信号连接由 controller 完成，view 只负责暴露控件引用。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from src.services.pointcloud_renderer import PointcloudRenderer


# 点数选项：标签 -> 值
POINT_COUNT_OPTIONS = [
    ("1 万", 10_000),
    ("10 万", 100_000),
    ("100 万", 1_000_000),
    ("500 万", 5_000_000),
    ("1000 万", 10_000_000),
    ("5000 万", 50_000_000),
]

SHAPE_OPTIONS = [
    ("随机立方体", "cube"),
    ("球体", "sphere"),
    ("网格地面", "grid"),
    ("室内扫描", "room"),
]

STREAM_FPS_OPTIONS = [("5 Hz", 5), ("10 Hz", 10), ("20 Hz", 20), ("30 Hz", 30)]
STREAM_FRAME_POINTS_OPTIONS = [
    ("1 千", 1_000),
    ("1 万", 10_000),
    ("10 万", 100_000),
]

# 着色方式：标签 -> 值
COLOR_BY_OPTIONS = [
    ("强度 intensity", "intensity"),
    ("Z 高度", "z"),
    ("单色", "solid"),
]

# 回放速度倍率：标签 -> 值（基于录制帧率 10Hz）
PLAY_SPEED_OPTIONS = [
    ("0.5x", 0.5),
    ("1x", 1.0),
    ("2x", 2.0),
    ("4x", 4.0),
]


class MainWindow(QMainWindow):
    """Demo 主窗口"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("3D 点云显示方案验证 Demo (PyVista + pyvistaqt)")
        self.resize(1600, 900)

        # 中央 splitter：左控制面板 + 右渲染器
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.setCentralWidget(splitter)

        # ---------- 右侧：3D 渲染器 ----------
        self.renderer = PointcloudRenderer(splitter)
        splitter.addWidget(self.renderer)

        # ---------- 左侧：控制面板 ----------
        scroll = QScrollArea(splitter)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(360)
        scroll.setMaximumWidth(420)

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        panel_layout.setSpacing(8)

        # ========== 1. 场景生成 ==========
        self.grp_scene = QGroupBox("1. 场景生成")
        scene_layout = QVBoxLayout(self.grp_scene)

        row = QHBoxLayout()
        row.addWidget(QLabel("点数："))
        self.cmb_point_count = QComboBox()
        for label, value in POINT_COUNT_OPTIONS:
            self.cmb_point_count.addItem(label, value)
        self.cmb_point_count.setCurrentIndex(2)  # 默认 100 万
        row.addWidget(self.cmb_point_count, 1)
        scene_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("形状："))
        self.cmb_shape = QComboBox()
        for label, value in SHAPE_OPTIONS:
            self.cmb_shape.addItem(label, value)
        row.addWidget(self.cmb_shape, 1)
        scene_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("随机种子："))
        self.spn_seed = QSpinBox()
        self.spn_seed.setRange(0, 999999)
        self.spn_seed.setValue(42)
        row.addWidget(self.spn_seed, 1)
        scene_layout.addLayout(row)

        self.btn_generate = QPushButton("生成场景")
        scene_layout.addWidget(self.btn_generate)

        panel_layout.addWidget(self.grp_scene)

        # ========== 2. 实时流模拟 ==========
        self.grp_stream = QGroupBox("2. 实时流模拟（SLAM 建图）")
        stream_layout = QVBoxLayout(self.grp_stream)

        self.chk_stream_enabled = QCheckBox("启用实时流")
        stream_layout.addWidget(self.chk_stream_enabled)

        row = QHBoxLayout()
        row.addWidget(QLabel("帧率："))
        self.cmb_stream_fps = QComboBox()
        for label, value in STREAM_FPS_OPTIONS:
            self.cmb_stream_fps.addItem(label, value)
        self.cmb_stream_fps.setCurrentIndex(1)  # 10 Hz
        row.addWidget(self.cmb_stream_fps, 1)
        stream_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("每帧点数："))
        self.cmb_stream_points = QComboBox()
        for label, value in STREAM_FRAME_POINTS_OPTIONS:
            self.cmb_stream_points.addItem(label, value)
        self.cmb_stream_points.setCurrentIndex(1)  # 1 万
        row.addWidget(self.cmb_stream_points, 1)
        stream_layout.addLayout(row)

        self.chk_accumulate = QCheckBox("累积到全局地图")
        self.chk_accumulate.setChecked(True)
        stream_layout.addWidget(self.chk_accumulate)

        self.btn_clear_accumulated = QPushButton("清空累积")
        stream_layout.addWidget(self.btn_clear_accumulated)

        # ---- 真实序列回放（用真实 pcd 逐帧播放，验证实时建图性能） ----
        self.btn_load_seq = QPushButton("加载真实序列（用于回放）")
        stream_layout.addWidget(self.btn_load_seq)

        row = QHBoxLayout()
        self.btn_play_pause = QPushButton("播放")
        self.btn_play_pause.setEnabled(False)
        self.btn_seq_stop = QPushButton("停止/重置")
        self.btn_seq_stop.setEnabled(False)
        row.addWidget(self.btn_play_pause)
        row.addWidget(self.btn_seq_stop)
        stream_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("回放速度："))
        self.cmb_play_speed = QComboBox()
        for label, value in PLAY_SPEED_OPTIONS:
            self.cmb_play_speed.addItem(label, value)
        self.cmb_play_speed.setCurrentIndex(1)  # 1x
        row.addWidget(self.cmb_play_speed, 1)
        stream_layout.addLayout(row)

        self.lbl_seq_progress = QLabel("帧: -/-")
        self.lbl_seq_progress.setStyleSheet("font-weight: bold;")
        stream_layout.addWidget(self.lbl_seq_progress)

        self.chk_follow = QCheckBox("跟随小车视角（回放时相机跟车）")
        self.chk_follow.setChecked(True)
        stream_layout.addWidget(self.chk_follow)

        panel_layout.addWidget(self.grp_stream)

        # ========== 3. 文件加载 ==========
        self.grp_file = QGroupBox("3. 真实文件加载")
        file_layout = QVBoxLayout(self.grp_file)

        self.btn_load_file = QPushButton("加载文件（可多选 .ply/.pcd/.csv/.xyz/.txt）")
        file_layout.addWidget(self.btn_load_file)

        self.btn_load_dir = QPushButton("加载整个目录（合并全部点云）")
        file_layout.addWidget(self.btn_load_dir)

        self.chk_register = QCheckBox("按位姿配准拼接（需目录含 alidarState.txt）")
        self.chk_register.setChecked(True)
        file_layout.addWidget(self.chk_register)

        row = QHBoxLayout()
        row.addWidget(QLabel("加载步长："))
        self.spn_stride = QSpinBox()
        self.spn_stride.setRange(1, 500)
        self.spn_stride.setValue(1)
        self.spn_stride.setSuffix("  (每N帧取1)")
        row.addWidget(self.spn_stride, 1)
        file_layout.addLayout(row)

        self.btn_add_dir_layer = QPushButton("叠加新目录（独立图层/独立颜色）")
        file_layout.addWidget(self.btn_add_dir_layer)

        self.grp_overlay = QGroupBox("叠加图层")
        self.overlay_layout = QVBoxLayout(self.grp_overlay)
        self.lbl_overlay_empty = QLabel("暂无叠加图层")
        self.lbl_overlay_empty.setStyleSheet("color: gray; font-size: 11px;")
        self.overlay_layout.addWidget(self.lbl_overlay_empty)
        self.btn_clear_overlay = QPushButton("清空叠加图层")
        self.overlay_layout.addWidget(self.btn_clear_overlay)
        file_layout.addWidget(self.grp_overlay)

        self.lbl_loaded_file = QLabel("未加载")
        self.lbl_loaded_file.setWordWrap(True)
        self.lbl_loaded_file.setStyleSheet("color: gray; font-size: 11px;")
        file_layout.addWidget(self.lbl_loaded_file)

        panel_layout.addWidget(self.grp_file)

        # ========== 4. 渲染参数 ==========
        self.grp_render = QGroupBox("4. 渲染参数")
        render_layout = QVBoxLayout(self.grp_render)

        row = QHBoxLayout()
        row.addWidget(QLabel("点大小："))
        self.sld_point_size = QSlider(Qt.Orientation.Horizontal)
        self.sld_point_size.setRange(1, 10)
        self.sld_point_size.setValue(2)
        row.addWidget(self.sld_point_size, 1)
        self.lbl_point_size = QLabel("2")
        self.lbl_point_size.setMinimumWidth(24)
        row.addWidget(self.lbl_point_size)
        render_layout.addLayout(row)

        self.chk_voxel_downsample = QCheckBox("体素降采样")
        render_layout.addWidget(self.chk_voxel_downsample)

        row = QHBoxLayout()
        row.addWidget(QLabel("voxel size (m)："))
        self.spn_voxel_size = QDoubleSpinBox()
        self.spn_voxel_size.setDecimals(3)
        self.spn_voxel_size.setRange(0.001, 5.0)
        self.spn_voxel_size.setSingleStep(0.01)
        self.spn_voxel_size.setValue(0.10)
        row.addWidget(self.spn_voxel_size, 1)
        render_layout.addLayout(row)

        self.chk_auto_budget = QCheckBox("超点数预算自动降采样（防交互卡顿）")
        self.chk_auto_budget.setChecked(True)
        render_layout.addWidget(self.chk_auto_budget)

        row = QHBoxLayout()
        row.addWidget(QLabel("点数预算(万)："))
        self.spn_budget = QSpinBox()
        self.spn_budget.setRange(10, 5000)
        self.spn_budget.setSingleStep(50)
        self.spn_budget.setValue(300)  # 300 万 = 3,000,000
        row.addWidget(self.spn_budget, 1)
        render_layout.addLayout(row)

        self.chk_edl = QCheckBox("EDL 光照增强（性能开销大）")
        render_layout.addWidget(self.chk_edl)

        row = QHBoxLayout()
        row.addWidget(QLabel("着色："))
        self.cmb_color_by = QComboBox()
        for label, value in COLOR_BY_OPTIONS:
            self.cmb_color_by.addItem(label, value)
        row.addWidget(self.cmb_color_by, 1)
        render_layout.addLayout(row)

        panel_layout.addWidget(self.grp_render)

        # ========== 5. 图层可见性 ==========
        self.grp_layers = QGroupBox("5. 图层可见性")
        layers_layout = QVBoxLayout(self.grp_layers)

        self.chk_layer_global = QCheckBox("显示全局地图")
        self.chk_layer_global.setChecked(True)
        layers_layout.addWidget(self.chk_layer_global)

        self.chk_layer_current = QCheckBox("显示当前帧")
        self.chk_layer_current.setChecked(True)
        layers_layout.addWidget(self.chk_layer_current)

        self.chk_layer_car = QCheckBox("显示 AGV 车模型")
        layers_layout.addWidget(self.chk_layer_car)

        panel_layout.addWidget(self.grp_layers)

        # ========== 6. 交互工具 ==========
        self.grp_interaction = QGroupBox("6. 交互工具")
        interaction_layout = QVBoxLayout(self.grp_interaction)

        self.chk_clip = QCheckBox("启用 GPU 剖面")
        interaction_layout.addWidget(self.chk_clip)

        # 剖面法向
        clip_normal_box = QGroupBox("剖面法向 (nx, ny, nz)")
        cn_layout = QHBoxLayout(clip_normal_box)
        self.sld_clip_nx = self._make_axis_slider(1.0)
        self.sld_clip_ny = self._make_axis_slider(0.0)
        self.sld_clip_nz = self._make_axis_slider(0.0)
        cn_layout.addWidget(QLabel("X"))
        cn_layout.addWidget(self.sld_clip_nx)
        cn_layout.addWidget(QLabel("Y"))
        cn_layout.addWidget(self.sld_clip_ny)
        cn_layout.addWidget(QLabel("Z"))
        cn_layout.addWidget(self.sld_clip_nz)
        interaction_layout.addWidget(clip_normal_box)

        # 剖面原点
        clip_origin_box = QGroupBox("剖面原点 (ox, oy, oz) 米")
        co_layout = QHBoxLayout(clip_origin_box)
        self.sld_clip_ox = self._make_position_slider(0.0)
        self.sld_clip_oy = self._make_position_slider(0.0)
        self.sld_clip_oz = self._make_position_slider(0.0)
        co_layout.addWidget(QLabel("X"))
        co_layout.addWidget(self.sld_clip_ox)
        co_layout.addWidget(QLabel("Y"))
        co_layout.addWidget(self.sld_clip_oy)
        co_layout.addWidget(QLabel("Z"))
        co_layout.addWidget(self.sld_clip_oz)
        interaction_layout.addWidget(clip_origin_box)

        self.chk_measure = QCheckBox("启用距离测量（Line Widget）")
        interaction_layout.addWidget(self.chk_measure)

        self.lbl_measurement = QLabel("测量距离：--")
        self.lbl_measurement.setStyleSheet("font-weight: bold;")
        interaction_layout.addWidget(self.lbl_measurement)

        self.chk_pick = QCheckBox("启用点拾取（Ctrl + 左键）")
        interaction_layout.addWidget(self.chk_pick)

        self.lbl_picked = QLabel("拾取坐标：--")
        interaction_layout.addWidget(self.lbl_picked)

        panel_layout.addWidget(self.grp_interaction)

        # ========== 7. 视角 ==========
        self.grp_camera = QGroupBox("7. 视角")
        camera_layout = QHBoxLayout(self.grp_camera)
        self.btn_view_iso = QPushButton("等轴")
        self.btn_view_top = QPushButton("俯视")
        self.btn_view_reset = QPushButton("重置")
        camera_layout.addWidget(self.btn_view_iso)
        camera_layout.addWidget(self.btn_view_top)
        camera_layout.addWidget(self.btn_view_reset)
        panel_layout.addWidget(self.grp_camera)

        # 弹性空隙
        panel_layout.addStretch(1)

        scroll.setWidget(panel)
        splitter.addWidget(scroll)

        # splitter 初始比例：控制面板 380，渲染器占剩余
        splitter.setSizes([380, 1200])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # ---------- 状态栏 ----------
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.lbl_fps = QLabel("FPS: --")
        self.lbl_points = QLabel("点数: 0")
        self.lbl_memory = QLabel("内存: --")
        self.status_bar.addPermanentWidget(self.lbl_fps)
        self.status_bar.addPermanentWidget(self.lbl_points)
        self.status_bar.addPermanentWidget(self.lbl_memory)

    # ================================================================
    # 辅助：创建滑块
    # ================================================================

    @staticmethod
    def _make_axis_slider(initial: float) -> QSlider:
        """法向滑块：范围 [-1.0, 1.0]，用 int 值 * 100 表示"""
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(-100, 100)
        slider.setValue(int(round(initial * 100)))
        slider.setFixedWidth(60)
        return slider

    @staticmethod
    def _make_position_slider(initial: float) -> QSlider:
        """位置滑块：范围 [-30.0, 30.0] 米，用 int 值 * 10 表示"""
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(-300, 300)
        slider.setValue(int(round(initial * 10)))
        slider.setFixedWidth(60)
        return slider

    # ================================================================
    # 便捷读取
    # ================================================================

    def get_clip_normal(self) -> tuple[float, float, float]:
        return (
            self.sld_clip_nx.value() / 100.0,
            self.sld_clip_ny.value() / 100.0,
            self.sld_clip_nz.value() / 100.0,
        )

    def get_clip_origin(self) -> tuple[float, float, float]:
        return (
            self.sld_clip_ox.value() / 10.0,
            self.sld_clip_oy.value() / 10.0,
            self.sld_clip_oz.value() / 10.0,
        )

    def open_file_dialog(self) -> list[str]:
        """弹出文件选择对话框（支持多选），返回路径列表（可能为空）"""
        from src.services.file_source import SUPPORTED_SUFFIXES

        filter_str = "点云文件 (" + " ".join(f"*{s}" for s in SUPPORTED_SUFFIXES) + ");;所有文件 (*)"
        paths, _ = QFileDialog.getOpenFileNames(self, "选择点云文件（可多选）", "", filter_str)
        return list(paths) if paths else []

    def open_directory_dialog(self) -> Optional[str]:
        """弹出目录选择对话框，返回目录路径或 None"""
        path = QFileDialog.getExistingDirectory(self, "选择包含点云文件的目录", "")
        return path if path else None

    def add_overlay_toggle(self, name: str, color_text: str) -> QCheckBox:
        """为叠加图层添加一个可见性复选框，返回该复选框"""
        chk = QCheckBox(f"{name} [{color_text}]")
        chk.setChecked(True)
        # 插到"清空"按钮之前
        self.overlay_layout.insertWidget(self.overlay_layout.count() - 1, chk)
        self.lbl_overlay_empty.setVisible(False)
        return chk

    def remove_overlay_toggle(self, chk: QCheckBox) -> None:
        """移除一个叠加图层复选框"""
        self.overlay_layout.removeWidget(chk)
        chk.deleteLater()
        # 只剩"暂无"标签和"清空"按钮时恢复提示
        if self.overlay_layout.count() <= 2:
            self.lbl_overlay_empty.setVisible(True)

    def set_fps_label(self, fps: float) -> None:
        self.lbl_fps.setText(f"FPS: {fps:5.1f}")

    def set_points_label(self, count: int) -> None:
        self.lbl_points.setText(f"点数: {count:,}")

    def set_memory_label(self, mem_mb: float) -> None:
        self.lbl_memory.setText(f"内存: {mem_mb:.0f} MB")

    def set_measurement_label(self, distance: Optional[float]) -> None:
        if distance is None:
            self.lbl_measurement.setText("测量距离：--")
        else:
            self.lbl_measurement.setText(f"测量距离：{distance:.3f} m")

    def set_picked_label(self, point: Optional[tuple[float, float, float]]) -> None:
        if point is None:
            self.lbl_picked.setText("拾取坐标：--")
        else:
            x, y, z = point
            self.lbl_picked.setText(f"拾取坐标：({x:.2f}, {y:.2f}, {z:.2f})")

    def set_loaded_file_label(self, path: Optional[str]) -> None:
        self.lbl_loaded_file.setText(path if path else "未加载")
