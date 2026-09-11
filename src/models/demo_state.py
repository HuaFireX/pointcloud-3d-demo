"""Demo 场景状态：所有可调参数集中在此，便于 controller 与 view 同步"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SceneConfig:
    """静态场景生成参数"""

    num_points: int = 1_000_000
    shape: str = "cube"  # cube | sphere | grid | room
    seed: Optional[int] = 42


@dataclass
class StreamConfig:
    """实时流模拟参数（模拟 SLAM 建图过程）"""

    enabled: bool = False
    fps: int = 10
    points_per_frame: int = 10_000
    center: tuple[float, float, float] = (0.0, 0.0, 1.0)
    accumulate: bool = True
    max_accumulated: int = 5_000_000


@dataclass
class RenderConfig:
    """渲染参数"""

    point_size: float = 2.0
    voxel_downsample: bool = False
    voxel_size: float = 0.10
    edl_enabled: bool = False
    global_map_color: str = "black"
    current_frame_color: str = "red"
    car_model_color: str = "steelblue"


@dataclass
class LayerConfig:
    """图层可见性"""

    global_map_visible: bool = True
    current_frame_visible: bool = True
    car_model_visible: bool = False


@dataclass
class InteractionConfig:
    """交互工具状态"""

    clip_enabled: bool = False
    clip_normal: tuple[float, float, float] = (1.0, 0.0, 0.0)
    clip_origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    measure_enabled: bool = False
    pick_enabled: bool = False
    last_measurement: float = 0.0
    last_picked_point: Optional[tuple[float, float, float]] = None


@dataclass
class DemoState:
    """总状态"""

    scene: SceneConfig = field(default_factory=SceneConfig)
    stream: StreamConfig = field(default_factory=StreamConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    layers: LayerConfig = field(default_factory=LayerConfig)
    interaction: InteractionConfig = field(default_factory=InteractionConfig)

    loaded_file: Optional[str] = None
    displayed_points: int = 0
    accumulated_points: int = 0
