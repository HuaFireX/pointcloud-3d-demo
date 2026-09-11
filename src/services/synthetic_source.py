"""合成点云生成器：随机立方体 / 球体 / 网格地面 / 室内扫描 / 雷达单帧"""

from __future__ import annotations

from typing import Optional

import numpy as np


SHAPES = ("cube", "sphere", "grid", "room")


def generate(shape: str, n: int, seed: Optional[int] = None) -> np.ndarray:
    """按形状生成 (n, 3) float32 点云"""
    if shape == "cube":
        return generate_random_cube(n, seed=seed)
    if shape == "sphere":
        return generate_random_sphere(n, seed=seed)
    if shape == "grid":
        return generate_grid_ground(n, seed=seed)
    if shape == "room":
        return generate_room_scan(n, seed=seed)
    raise ValueError(f"未知形状: {shape}，可选 {SHAPES}")


def generate_random_cube(n: int, extent: float = 40.0, seed: Optional[int] = None) -> np.ndarray:
    """立方体内均匀随机点云，边长 extent 米"""
    rng = np.random.default_rng(seed)
    return ((rng.random((n, 3), dtype=np.float32) - 0.5) * extent).astype(np.float32)


def generate_random_sphere(n: int, radius: float = 15.0, seed: Optional[int] = None) -> np.ndarray:
    """球体内均匀随机点云（体积均匀，用 cbrt 变换半径）"""
    rng = np.random.default_rng(seed)
    r = np.cbrt(rng.random(n, dtype=np.float32)) * radius
    theta = rng.random(n, dtype=np.float32) * (2.0 * np.pi)
    phi = np.arccos(2.0 * rng.random(n, dtype=np.float32) - 1.0)

    x = r * np.sin(phi) * np.cos(theta)
    y = r * np.sin(phi) * np.sin(theta)
    z = r * np.cos(phi)
    return np.stack([x, y, z], axis=1).astype(np.float32)


def generate_grid_ground(n: int, extent: float = 80.0, seed: Optional[int] = None) -> np.ndarray:
    """带正弦高度起伏的地面网格点云"""
    rng = np.random.default_rng(seed)
    side = max(int(np.sqrt(n)), 2)
    axis = np.linspace(-extent / 2.0, extent / 2.0, side, dtype=np.float32)
    xx, yy = np.meshgrid(axis, axis)
    zz = np.sin(xx * 0.15) * np.cos(yy * 0.15) * 2.0
    zz = zz + rng.normal(0.0, 0.05, xx.shape).astype(np.float32)

    pts = np.stack([xx.ravel(), yy.ravel(), zz.ravel()], axis=1)
    if pts.shape[0] > n:
        pts = pts[:n]
    return pts.astype(np.float32)


def generate_room_scan(
    n: int,
    room_size: tuple[float, float, float] = (20.0, 16.0, 4.0),
    seed: Optional[int] = None,
) -> np.ndarray:
    """模拟室内 SLAM 扫描：地面 + 天花板 + 四面墙"""
    rng = np.random.default_rng(seed)
    width, depth, height = room_size

    per_surface = max(n // 6, 1)
    parts: list[np.ndarray] = []

    # 地面 z ≈ 0
    parts.append(np.stack([
        rng.uniform(-width / 2, width / 2, per_surface),
        rng.uniform(-depth / 2, depth / 2, per_surface),
        rng.normal(0.0, 0.02, per_surface),
    ], axis=1))

    # 天花板 z ≈ height
    parts.append(np.stack([
        rng.uniform(-width / 2, width / 2, per_surface),
        rng.uniform(-depth / 2, depth / 2, per_surface),
        rng.normal(height, 0.02, per_surface),
    ], axis=1))

    # 四面墙
    wall_specs = [
        ("x-", -width / 2),
        ("x+", width / 2),
        ("y-", -depth / 2),
        ("y+", depth / 2),
    ]
    for axis, coord in wall_specs:
        if axis.startswith("x"):
            parts.append(np.stack([
                rng.normal(coord, 0.02, per_surface),
                rng.uniform(-depth / 2, depth / 2, per_surface),
                rng.uniform(0.0, height, per_surface),
            ], axis=1))
        else:
            parts.append(np.stack([
                rng.uniform(-width / 2, width / 2, per_surface),
                rng.normal(coord, 0.02, per_surface),
                rng.uniform(0.0, height, per_surface),
            ], axis=1))

    return np.concatenate(parts, axis=0).astype(np.float32)


def generate_lidar_frame(
    center: np.ndarray,
    n_points: int,
    yaw: float,
    max_range: float = 20.0,
    vertical_fov_deg: float = 30.0,
    seed: Optional[int] = None,
) -> np.ndarray:
    """生成一帧模拟 3D 雷达扫描：水平 360°，垂直 ±vertical_fov_deg/2

    Args:
        center: 雷达中心 (3,)
        n_points: 每帧点数
        yaw: 当前偏航角（弧度），用于模拟雷达随车旋转
    """
    rng = np.random.default_rng(seed)

    theta = rng.uniform(0.0, 2.0 * np.pi, n_points).astype(np.float32)
    phi_max = np.deg2rad(vertical_fov_deg / 2.0)
    phi = rng.uniform(-phi_max, phi_max, n_points).astype(np.float32)
    # 距离分布：多数近，少数远
    r = (rng.random(n_points, dtype=np.float32) ** 0.5) * max_range + 0.3

    x = r * np.cos(phi) * np.cos(theta)
    y = r * np.cos(phi) * np.sin(theta)
    z = r * np.sin(phi)

    # 应用 yaw 旋转
    cos_yaw = np.cos(yaw, dtype=np.float32)
    sin_yaw = np.sin(yaw, dtype=np.float32)
    x_rot = x * cos_yaw - y * sin_yaw
    y_rot = x * sin_yaw + y * cos_yaw

    frame = np.stack([x_rot, y_rot, z], axis=1) + np.asarray(center, dtype=np.float32)
    return frame.astype(np.float32)
