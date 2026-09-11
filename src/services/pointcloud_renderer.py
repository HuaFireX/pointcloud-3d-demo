"""PyVista QtInteractor 封装：图层管理、GPU 剖面、测量、点拾取

关键性能设计：
- 点云渲染走 GL_POINTS（render_points_as_spheres=False），比球体快 10 倍以上
- 剖面用 vtkMapper.SetClippingPlanes（GPU 侧），零 CPU 开销
- 每个图层独立 actor，更新时只影响自己
- add_mesh / update_points 分离，避免样式重设
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pyvista as pv
import vtk
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from pyvistaqt import QtInteractor


class PointcloudRenderer(QWidget):
    """3D 点云渲染器 Widget

    信号：
    - measurement_changed(float): 距离测量值变化（米）
    - point_picked(object): 点拾取，参数为 (3,) numpy 数组
    """

    measurement_changed = Signal(float)
    point_picked = Signal(object)

    # 图层名常量
    LAYER_GLOBAL_MAP = "global_map"
    LAYER_CURRENT_FRAME = "current_frame"
    LAYER_CAR_MODEL = "car_model"

    def __init__(self, parent: Optional[QWidget] = None, background: str = "white"):
        super().__init__(parent)

        self._plotter = QtInteractor(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._plotter.interactor)
        self.setLayout(layout)

        self._plotter.set_background(background)
        self._plotter.add_axes()

        # 图层管理：name -> (mesh, actor, mapper)
        self._pointcloud_layers: Dict[str, tuple[pv.PolyData, object, object]] = {}
        self._mesh_layers: Dict[str, tuple[pv.DataSet, object, object]] = {}

        # 剖面：全局单例
        self._clip_plane = vtk.vtkPlane()
        self._clip_plane.SetNormal(1.0, 0.0, 0.0)
        self._clip_plane.SetOrigin(0.0, 0.0, 0.0)
        self._clip_collection = vtk.vtkPlaneCollection()
        self._clip_collection.AddItem(self._clip_plane)
        self._clip_enabled = False

        # 测量工具
        self._measure_widget = None
        self._measure_enabled = False

        # 点拾取
        self._pick_enabled = False

        # EDL 光照（可选）
        self._edl_enabled = False

    # ================================================================
    # 点云图层
    # ================================================================

    def add_pointcloud(
        self,
        name: str,
        points: np.ndarray,
        scalars: Optional[np.ndarray] = None,
        color: str = "black",
        point_size: float = 2.0,
        cmap: str = "viridis",
        opacity: float = 1.0,
    ) -> None:
        """添加或替换点云图层（同名先移除）"""
        self.remove_pointcloud(name)

        pts = np.asarray(points, dtype=np.float32)
        if pts.size == 0:
            return

        mesh = pv.PolyData(pts)

        add_kwargs = dict(
            name=name,
            point_size=point_size,
            render_points_as_spheres=False,
            opacity=opacity,
        )
        if scalars is not None:
            mesh["scalars"] = np.asarray(scalars, dtype=np.float32)
            add_kwargs["scalars"] = "scalars"
            add_kwargs["cmap"] = cmap
        else:
            add_kwargs["color"] = color

        actor = self._plotter.add_mesh(mesh, **add_kwargs)
        mapper = self._get_mapper(actor)

        if self._clip_enabled and mapper is not None:
            mapper.SetClippingPlanes(self._clip_collection)

        self._pointcloud_layers[name] = (mesh, actor, mapper)

    def update_pointcloud(
        self, name: str, points: np.ndarray, scalars: Optional[np.ndarray] = None
    ) -> None:
        """更新已有点云图层的坐标，保持样式

        pyvista 的 mesh.points = new_array 会自动触发 VTK Modified
        """
        layer = self._pointcloud_layers.get(name)
        if layer is None:
            return

        mesh, _actor, _mapper = layer
        pts = np.asarray(points, dtype=np.float32)
        mesh.points = pts

        if scalars is not None:
            mesh["scalars"] = np.asarray(scalars, dtype=np.float32)

        self._plotter.render()

    def remove_pointcloud(self, name: str) -> None:
        """移除点云图层"""
        if name not in self._pointcloud_layers:
            return
        _mesh, actor, _mapper = self._pointcloud_layers.pop(name)
        try:
            self._plotter.remove_actor(actor, render=False)
        except Exception:
            # 兼容不同 pyvista 版本的 remove_actor 签名
            try:
                self._plotter.remove_actor(name, render=False)
            except Exception:
                pass

    def set_pointcloud_visible(self, name: str, visible: bool) -> None:
        """设置点云图层可见性"""
        layer = self._pointcloud_layers.get(name)
        if layer is None:
            return
        _mesh, actor, _mapper = layer
        try:
            actor.SetVisibility(bool(visible))
        except AttributeError:
            actor.visibility = bool(visible)
        self._plotter.render()

    def set_point_size(self, name: str, point_size: float) -> None:
        """调整点大小"""
        layer = self._pointcloud_layers.get(name)
        if layer is None:
            return
        _mesh, actor, _mapper = layer
        try:
            prop = actor.GetProperty() if hasattr(actor, "GetProperty") else actor.prop
            prop.SetPointSize(float(point_size))
        except Exception:
            pass
        self._plotter.render()

    # ================================================================
    # 网格模型图层（如 AGV 车模型）
    # ================================================================

    def add_mesh_model(
        self,
        name: str,
        mesh: pv.DataSet,
        color: str = "steelblue",
        opacity: float = 1.0,
    ) -> None:
        """添加三角网格模型图层"""
        self.remove_mesh_model(name)
        actor = self._plotter.add_mesh(mesh, name=name, color=color, opacity=opacity)
        mapper = self._get_mapper(actor)
        if self._clip_enabled and mapper is not None:
            mapper.SetClippingPlanes(self._clip_collection)
        self._mesh_layers[name] = (mesh, actor, mapper)

    def remove_mesh_model(self, name: str) -> None:
        if name not in self._mesh_layers:
            return
        _mesh, actor, _mapper = self._mesh_layers.pop(name)
        try:
            self._plotter.remove_actor(actor, render=False)
        except Exception:
            try:
                self._plotter.remove_actor(name, render=False)
            except Exception:
                pass

    def set_mesh_visible(self, name: str, visible: bool) -> None:
        layer = self._mesh_layers.get(name)
        if layer is None:
            return
        _mesh, actor, _mapper = layer
        try:
            actor.SetVisibility(bool(visible))
        except AttributeError:
            actor.visibility = bool(visible)
        self._plotter.render()

    # ================================================================
    # 全局操作
    # ================================================================

    def clear_all(self) -> None:
        """清空所有图层，重置坐标轴"""
        self._pointcloud_layers.clear()
        self._mesh_layers.clear()
        self._plotter.clear()
        self._plotter.add_axes()

    def get_point_count(self, name: str) -> int:
        layer = self._pointcloud_layers.get(name)
        if layer is None:
            return 0
        mesh, _actor, _mapper = layer
        return int(mesh.n_points)

    def get_total_point_count(self) -> int:
        return sum(self.get_point_count(name) for name in self._pointcloud_layers)

    # ================================================================
    # 相机
    # ================================================================

    def reset_camera(self) -> None:
        self._plotter.reset_camera()

    def view_isometric(self) -> None:
        self._plotter.view_isometric()

    def view_top(self) -> None:
        self._plotter.view_xy()

    def view_front(self) -> None:
        self._plotter.view_xz()

    # ================================================================
    # GPU 剖面
    # ================================================================

    def set_clip_enabled(self, enabled: bool) -> None:
        """启用/禁用剖面（对所有图层生效）"""
        self._clip_enabled = bool(enabled)
        all_mappers = [layer[2] for layer in self._pointcloud_layers.values()]
        all_mappers += [layer[2] for layer in self._mesh_layers.values()]

        for mapper in all_mappers:
            if mapper is None:
                continue
            if self._clip_enabled:
                mapper.SetClippingPlanes(self._clip_collection)
            else:
                mapper.SetClippingPlanes(None)

        self._plotter.render()

    def set_clip_plane(self, normal: np.ndarray, origin: np.ndarray) -> None:
        """更新剖面法向和原点（GPU 侧，零 CPU 开销）"""
        n = np.asarray(normal, dtype=np.float64).ravel()
        o = np.asarray(origin, dtype=np.float64).ravel()

        # 法向归零时退化，跳过
        norm_len = float(np.linalg.norm(n))
        if norm_len < 1e-6:
            return

        self._clip_plane.SetNormal(float(n[0]), float(n[1]), float(n[2]))
        self._clip_plane.SetOrigin(float(o[0]), float(o[1]), float(o[2]))

        if self._clip_enabled:
            self._plotter.render()

    # ================================================================
    # 测量工具（Line Widget）
    # ================================================================

    def set_measure_enabled(self, enabled: bool) -> None:
        """启用/禁用距离测量工具"""
        enabled = bool(enabled)
        if enabled and not self._measure_enabled:
            # use_vertices=True: 回调接收两个参数 (pointa, pointb)，直接是端点坐标
            # use_vertices=False (默认): 回调只接收一个 PolyData 线对象，需自己解析端点
            self._measure_widget = self._plotter.add_line_widget(
                callback=self._on_line_widget_change,
                use_vertices=True,
            )
            self._measure_enabled = True
        elif not enabled and self._measure_enabled:
            if self._measure_widget is not None:
                try:
                    self._measure_widget.close()
                except Exception:
                    pass
                self._measure_widget = None
            self._measure_enabled = False
        self._plotter.render()

    def _on_line_widget_change(self, pointa, pointb) -> None:
        """Line widget 回调：计算距离并发射信号

        use_vertices=True 时 pyvista 传入两个 (3,) 数组，分别是线段两端点。
        """
        a = np.asarray(pointa, dtype=np.float64).ravel()
        b = np.asarray(pointb, dtype=np.float64).ravel()
        if a.size < 3 or b.size < 3:
            return
        distance = float(np.linalg.norm(a - b))
        self.measurement_changed.emit(distance)

    # ================================================================
    # 点拾取
    # ================================================================

    def set_pick_enabled(self, enabled: bool) -> None:
        """启用/禁用点拾取（鼠标点击拾取最近点）"""
        enabled = bool(enabled)
        if enabled and not self._pick_enabled:
            try:
                self._plotter.enable_point_picking(
                    callback=self._on_point_picked,
                    show_message=False,
                    use_picker=True,
                    show_point=True,
                    color="red",
                    point_size=8,
                )
                self._pick_enabled = True
            except Exception:
                self._pick_enabled = False
        elif not enabled and self._pick_enabled:
            try:
                self._plotter.disable_picking()
            except Exception:
                pass
            self._pick_enabled = False

    def _on_point_picked(self, picked_point) -> None:
        pt = np.asarray(picked_point, dtype=np.float64).ravel()
        if pt.size >= 3:
            self.point_picked.emit(pt[:3])

    # ================================================================
    # EDL 光照增强
    # ================================================================

    def set_edl_enabled(self, enabled: bool) -> None:
        """Eye-Dome Lighting，提升点云深度感知，但性能开销较大"""
        enabled = bool(enabled)
        if enabled == self._edl_enabled:
            return
        try:
            if enabled:
                self._plotter.enable_eye_dome_lighting()
            else:
                self._plotter.disable_eye_dome_lighting()
            self._edl_enabled = enabled
        except Exception:
            self._edl_enabled = False

    # ================================================================
    # 渲染 & 底层访问
    # ================================================================

    def render(self) -> None:
        self._plotter.render()

    def get_plotter(self) -> QtInteractor:
        """暴露底层 plotter，供 FPS 监控等外部使用"""
        return self._plotter

    def get_render_window(self):
        """获取 VTK render window，供 FPSMonitor 注册观察者"""
        try:
            return self._plotter.render_window
        except AttributeError:
            return None

    @staticmethod
    def _get_mapper(actor):
        """从 pyvista Actor 或 vtkActor 中提取 mapper，跨版本兼容"""
        mapper = getattr(actor, "mapper", None)
        if mapper is not None:
            return mapper
        getter = getattr(actor, "GetMapper", None)
        if callable(getter):
            return getter()
        return None

    def closeEvent(self, event) -> None:
        """窗口关闭时释放 VTK 资源"""
        try:
            self._plotter.close()
        except Exception:
            pass
        super().closeEvent(event)
