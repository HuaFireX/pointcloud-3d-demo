"""主窗口：左侧 3D 视图（带相机工具条）+ 右侧任务分组 tab 面板 + 底部状态栏

编排参考 lh_host_computer 前端惯例：
- 任务分组 tab（数据 / 回放 / 显示 / 工具），降低单屏控件密度
- 顶部"快速上手"引导条（workflow header 思路）
- 3D 视图上方常驻相机工具条（常用操作始终可见）
- 稳定对象名：所有控件属性名保持不变，controller 无需改动

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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.services.pointcloud_renderer import PointcloudRenderer


# 点数选项：标签 -> 值
POINT_COUNT_OPTIONS = [
    ("1 万", 10_000),
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
    ("Z 高度（推荐）", "z"),
    ("强度 intensity", "intensity"),
    ("单色", "solid"),
]

# 回放速度倍率：标签 -> 值（基于录制帧率 10Hz）
PLAY_SPEED_OPTIONS = [
    ("0.5x", 0.5),
    ("1x", 1.0),
    ("2x", 2.0),
    ("4x", 4.0),
]

# 回放视角模式：标签 -> 值
VIEW_MODE_OPTIONS = [
    ("车后跟随", "third"),
    ("旁观者（斜侧俯视·滚轮调距）", "observer"),
    ("俯视跟随（正上往下）", "top"),
    ("上帝视角（固定全局）", "god"),
]

QUICK_START_TEXT = (
    "快速上手：① [数据] 加载整个目录 → ② [回放] 播放 → ③ 换视角/滚轮调距观察；"
    "着色与点大小在 [显示]，剖面/测量在 [工具]"
)


class MainWindow(QMainWindow):
    """Demo 主窗口"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("3D 点云显示方案验证 Demo (PyVista + pyvistaqt)")
        self.resize(1600, 900)

        # 中央 splitter：左 3D 视图（含相机工具条）+ 右 tab 面板
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.setCentralWidget(splitter)

        # ---------- 左侧：3D 视图容器（顶部相机工具条 + 渲染器） ----------
        view_container = QWidget(splitter)
        view_layout = QVBoxLayout(view_container)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(4)

        camera_bar = QHBoxLayout()
        camera_bar.setSpacing(6)
        self.btn_view_iso = QPushButton("等轴")
        self.btn_view_top = QPushButton("俯视")
        self.btn_view_reset = QPushButton("重置视角")
        for btn in (self.btn_view_iso, self.btn_view_top, self.btn_view_reset):
            btn.setFixedWidth(80)
            camera_bar.addWidget(btn)
        camera_bar.addStretch(1)
        self.lbl_view_hint = QLabel("左键旋转 / 右键平移 / 滚轮缩放；旁观者视角滚轮=调离车距离")
        self.lbl_view_hint.setStyleSheet("color: gray; font-size: 11px;")
        camera_bar.addWidget(self.lbl_view_hint)
        view_layout.addLayout(camera_bar)

        self.renderer = PointcloudRenderer(view_container)
        view_layout.addWidget(self.renderer, 1)
        splitter.addWidget(view_container)

        # ---------- 右侧：快速上手引导 + 任务 tab 面板 ----------
        side = QWidget(splitter)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(8, 8, 8, 8)
        side_layout.setSpacing(6)

        self.lbl_quick_start = QLabel(QUICK_START_TEXT)
        self.lbl_quick_start.setWordWrap(True)
        self.lbl_quick_start.setStyleSheet(
            "background: #eef4fb; border: 1px solid #c9dcf0; border-radius: 4px; "
            "padding: 6px; font-size: 12px;"
        )
        side_layout.addWidget(self.lbl_quick_start)

        self.tabs = QTabWidget()
        side_layout.addWidget(self.tabs, 1)
        splitter.addWidget(side)

        self._build_data_tab()
        self._build_play_tab()
        self._build_display_tab()
        self._build_tool_tab()

        # splitter 初始比例：3D 视图占大头，面板固定窄
        splitter.setSizes([1200, 400])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        side.setMinimumWidth(360)
        side.setMaximumWidth(440)

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
    # Tab 1：数据
    # ================================================================

    def _build_data_tab(self) -> None:
        scroll = self._make_tab_scroll()

        grp_load = QGroupBox("加载点云")
        load_layout = QVBoxLayout(grp_load)

        self.btn_load_dir = QPushButton("① 加载整个目录（合并全部点云）")
        self.btn_load_dir.setToolTip(
            "扫描目录内所有点云帧并按位姿（alidarState.txt）配准合并为一张地图；"
            "大目录会自动设加载步长"
        )
        load_layout.addWidget(self.btn_load_dir)

        self.btn_load_file = QPushButton("加载文件（可多选）")
        self.btn_load_file.setToolTip("选择一个或多个 .ply/.pcd/.csv/.xyz/.txt 文件合并加载")
        load_layout.addWidget(self.btn_load_file)

        self.chk_register = QCheckBox("按位姿配准拼接")
        self.chk_register.setChecked(True)
        self.chk_register.setToolTip(
            "目录含 alidarState.txt 时，用每帧位姿把点云变换到世界系再合并，消除移动拖影"
        )
        load_layout.addWidget(self.chk_register)

        row = QHBoxLayout()
        row.addWidget(QLabel("加载步长："))
        self.spn_stride = QSpinBox()
        self.spn_stride.setRange(1, 500)
        self.spn_stride.setValue(1)
        self.spn_stride.setSuffix("  (每N帧取1)")
        self.spn_stride.setToolTip("超长录制抽帧加载：N 越大加载越快、点越稀；>5000 帧自动设")
        row.addWidget(self.spn_stride, 1)
        load_layout.addLayout(row)

        self.btn_export_pcd = QPushButton("导出合并点云为 PCD")
        self.btn_export_pcd.setToolTip("把当前合并（配准后）点云写成单个完整 .pcd 文件")
        load_layout.addWidget(self.btn_export_pcd)

        self.lbl_loaded_file = QLabel("未加载")
        self.lbl_loaded_file.setWordWrap(True)
        self.lbl_loaded_file.setStyleSheet("color: gray; font-size: 11px;")
        load_layout.addWidget(self.lbl_loaded_file)

        scroll.widget().layout().addWidget(grp_load)

        grp_overlay = QGroupBox("多目录叠加")
        overlay_layout = QVBoxLayout(grp_overlay)
        self.btn_add_dir_layer = QPushButton("叠加新目录（独立图层/颜色）")
        self.btn_add_dir_layer.setToolTip("把另一个目录作为独立颜色图层叠加，用于多趟对比")
        overlay_layout.addWidget(self.btn_add_dir_layer)
        self.overlay_layout = QVBoxLayout()
        self.lbl_overlay_empty = QLabel("暂无叠加图层")
        self.lbl_overlay_empty.setStyleSheet("color: gray; font-size: 11px;")
        self.overlay_layout.addWidget(self.lbl_overlay_empty)
        self.btn_clear_overlay = QPushButton("清空叠加图层")
        self.overlay_layout.addWidget(self.btn_clear_overlay)
        overlay_layout.addLayout(self.overlay_layout)
        scroll.widget().layout().addWidget(grp_overlay)

        grp_scene = QGroupBox("合成测试场景（可选）")
        scene_layout = QVBoxLayout(grp_scene)
        row = QHBoxLayout()
        row.addWidget(QLabel("点数："))
        self.cmb_point_count = QComboBox()
        for label, value in POINT_COUNT_OPTIONS:
            self.cmb_point_count.addItem(label, value)
        self.cmb_point_count.setCurrentIndex(1)  # 默认 100 万
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
        scroll.widget().layout().addWidget(grp_scene)

        scroll.widget().layout().addStretch(1)
        self.tabs.addTab(scroll, "数据")

    # ================================================================
    # Tab 2：回放
    # ================================================================

    def _build_play_tab(self) -> None:
        scroll = self._make_tab_scroll()

        grp_seq = QGroupBox("真实序列回放（推荐）")
        seq_layout = QVBoxLayout(grp_seq)

        self.btn_load_seq = QPushButton("① 加载真实序列")
        self.btn_load_seq.setToolTip("选目录后只记文件列表+位姿（不一次性渲染），供逐帧播放")
        seq_layout.addWidget(self.btn_load_seq)

        row = QHBoxLayout()
        self.btn_play_pause = QPushButton("② 播放")
        self.btn_play_pause.setEnabled(False)
        self.btn_seq_stop = QPushButton("停止/重置")
        self.btn_seq_stop.setEnabled(False)
        row.addWidget(self.btn_play_pause)
        row.addWidget(self.btn_seq_stop)
        seq_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("速度："))
        self.cmb_play_speed = QComboBox()
        for label, value in PLAY_SPEED_OPTIONS:
            self.cmb_play_speed.addItem(label, value)
        self.cmb_play_speed.setCurrentIndex(1)  # 1x
        row.addWidget(self.cmb_play_speed, 1)
        seq_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("视角："))
        self.cmb_view_mode = QComboBox()
        for label, value in VIEW_MODE_OPTIONS:
            self.cmb_view_mode.addItem(label, value)
        self.cmb_view_mode.setCurrentIndex(0)  # 车后跟随
        self.cmb_view_mode.setToolTip(
            "车后跟随=经典跟随；旁观者=斜侧俯视、滚轮调离车距离；"
            "俯视跟随=正上往下；上帝视角=固定全局"
        )
        row.addWidget(self.cmb_view_mode, 1)
        seq_layout.addLayout(row)

        self.lbl_seq_progress = QLabel("帧: -/-")
        self.lbl_seq_progress.setStyleSheet("font-weight: bold;")
        seq_layout.addWidget(self.lbl_seq_progress)

        scroll.widget().layout().addWidget(grp_seq)

        grp_stream = QGroupBox("合成实时流（无真实数据时演示）")
        stream_layout = QVBoxLayout(grp_stream)
        self.chk_stream_enabled = QCheckBox("启用合成实时流")
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
        scroll.widget().layout().addWidget(grp_stream)

        scroll.widget().layout().addStretch(1)
        self.tabs.addTab(scroll, "回放")

    # ================================================================
    # Tab 3：显示与图层
    # ================================================================

    def _build_display_tab(self) -> None:
        scroll = self._make_tab_scroll()

        grp_render = QGroupBox("渲染")
        render_layout = QVBoxLayout(grp_render)

        row = QHBoxLayout()
        row.addWidget(QLabel("着色："))
        self.cmb_color_by = QComboBox()
        for label, value in COLOR_BY_OPTIONS:
            self.cmb_color_by.addItem(label, value)
        self.cmb_color_by.setToolTip("Z 高度按高程着色看结构；强度用反射强度；单色统一颜色")
        row.addWidget(self.cmb_color_by, 1)
        render_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("点大小："))
        self.sld_point_size = QSlider(Qt.Orientation.Horizontal)
        self.sld_point_size.setRange(1, 10)
        self.sld_point_size.setValue(2)
        self.sld_point_size.setToolTip("点越大越易看但越耗性能")
        row.addWidget(self.sld_point_size, 1)
        self.lbl_point_size = QLabel("2")
        self.lbl_point_size.setMinimumWidth(24)
        row.addWidget(self.lbl_point_size)
        render_layout.addLayout(row)

        self.chk_voxel_downsample = QCheckBox("体素降采样（手动）")
        self.chk_voxel_downsample.setToolTip("按 voxel size 抽稀点云，降低渲染量")
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

        self.chk_auto_budget = QCheckBox("超点数预算自动降采样")
        self.chk_auto_budget.setChecked(True)
        self.chk_auto_budget.setToolTip("合并点数超预算时自动抽稀，防交互卡顿（推荐开启）")
        render_layout.addWidget(self.chk_auto_budget)
        row = QHBoxLayout()
        row.addWidget(QLabel("点数预算(万)："))
        self.spn_budget = QSpinBox()
        self.spn_budget.setRange(10, 5000)
        self.spn_budget.setSingleStep(50)
        self.spn_budget.setValue(300)  # 300 万
        self.spn_budget.setToolTip("渲染点数上限；越大越细但越卡")
        row.addWidget(self.spn_budget, 1)
        render_layout.addLayout(row)

        self.chk_edl = QCheckBox("EDL 光照增强")
        self.chk_edl.setToolTip("Eye-Dome Lighting 提升深度感知，性能开销大")
        render_layout.addWidget(self.chk_edl)

        scroll.widget().layout().addWidget(grp_render)

        grp_layers = QGroupBox("图层可见性")
        layers_layout = QVBoxLayout(grp_layers)
        self.chk_layer_global = QCheckBox("全局地图（累积/合并）")
        self.chk_layer_global.setChecked(True)
        layers_layout.addWidget(self.chk_layer_global)
        self.chk_layer_current = QCheckBox("当前帧（红色活扫描）")
        self.chk_layer_current.setChecked(True)
        layers_layout.addWidget(self.chk_layer_current)
        self.chk_layer_car = QCheckBox("AGV 车模型")
        self.chk_layer_car.setToolTip("回放时车模型贴到当前位姿")
        layers_layout.addWidget(self.chk_layer_car)
        scroll.widget().layout().addWidget(grp_layers)

        scroll.widget().layout().addStretch(1)
        self.tabs.addTab(scroll, "显示")

    # ================================================================
    # Tab 4：测量工具
    # ================================================================

    def _build_tool_tab(self) -> None:
        scroll = self._make_tab_scroll()

        grp_clip = QGroupBox("GPU 剖面")
        clip_layout = QVBoxLayout(grp_clip)
        self.chk_clip = QCheckBox("启用剖面（GPU 裁剪）")
        self.chk_clip.setToolTip("按法向+原点裁切点云，看内部结构；GPU 侧零 CPU 开销")
        clip_layout.addWidget(self.chk_clip)

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
        clip_layout.addWidget(clip_normal_box)

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
        clip_layout.addWidget(clip_origin_box)

        scroll.widget().layout().addWidget(grp_clip)

        grp_measure = QGroupBox("测量与拾取")
        measure_layout = QVBoxLayout(grp_measure)
        self.chk_measure = QCheckBox("距离测量（拖线）")
        self.chk_measure.setToolTip("启用后拖出线段，状态显示两端点距离")
        measure_layout.addWidget(self.chk_measure)
        self.lbl_measurement = QLabel("测量距离：--")
        self.lbl_measurement.setStyleSheet("font-weight: bold;")
        measure_layout.addWidget(self.lbl_measurement)
        self.chk_pick = QCheckBox("点拾取（Ctrl + 左键）")
        self.chk_pick.setToolTip("点击点云拾取最近点，状态显示坐标")
        measure_layout.addWidget(self.chk_pick)
        self.lbl_picked = QLabel("拾取坐标：--")
        measure_layout.addWidget(self.lbl_picked)
        scroll.widget().layout().addWidget(grp_measure)

        scroll.widget().layout().addStretch(1)
        self.tabs.addTab(scroll, "工具")

    # ================================================================
    # 辅助
    # ================================================================

    @staticmethod
    def _make_tab_scroll() -> QScrollArea:
        """每个 tab 内一个可滚动容器，返回 QScrollArea（内容用 .widget().layout() 追加）"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        scroll.setWidget(host)
        return scroll

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

    def open_save_pcd_dialog(self, default_name: str) -> Optional[str]:
        """弹出 PCD 保存对话框，返回路径或 None"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出合并点云为 PCD", default_name, "PCD 点云 (*.pcd)"
        )
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
