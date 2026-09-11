"""位姿源：解析 alidarState.txt 用于多帧点云配准

alidarState.txt 每行 26 列，布局：
    0      时间戳（epoch 秒）
    1-3    位置 (x, y, z) 米
    4-7    四元数 (x, y, z, w)
    8-10   线速度
    11-13  角速度
    14-16  陀螺零偏
    17-19  重力向量
    20-25  其他状态量

行数与同目录 pcd 帧数一一对应（按自然序第 i 行 ↔ 第 i 帧）。
配准公式：p_world = R(quat) @ p_lidar + pos
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np


def find_pose_file(directory: str | Path) -> Optional[Path]:
    """在目录中查找位姿状态文件（alidarState.txt 或名字含 state 的 .txt）"""
    d = Path(directory)
    if not d.is_dir():
        return None

    candidates = [
        p
        for p in sorted(d.iterdir())
        if p.is_file() and p.suffix.lower() == ".txt" and "state" in p.name.lower()
    ]
    if not candidates:
        return None

    # 优先精确匹配 alidarState.txt
    for p in candidates:
        if p.name.lower() == "alidarstate.txt":
            return p
    return candidates[0]


def load_poses(path: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """解析位姿文件

    Returns:
        (timestamps, positions, quaternions)
        timestamps: (N,) float64 epoch 秒
        positions: (N, 3) float64 米
        quaternions: (N, 4) float64，已归一化，顺序 (x, y, z, w)
    """
    raw = np.loadtxt(str(path), dtype=np.float64, ndmin=2)
    if raw.shape[1] < 8:
        raise ValueError(f"位姿文件列数不足（需 >= 8 列）: {raw.shape}")

    timestamps = raw[:, 0]
    positions = raw[:, 1:4].astype(np.float64)
    quaternions = raw[:, 4:8].astype(np.float64)

    norms = np.linalg.norm(quaternions, axis=1, keepdims=True)
    norms[norms < 1e-12] = 1.0
    quaternions = quaternions / norms

    return timestamps, positions, quaternions


def quat_to_matrix(q: np.ndarray) -> np.ndarray:
    """四元数 (x, y, z, w) -> 3x3 旋转矩阵"""
    x, y, z, w = (float(v) for v in q)
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z

    return np.array(
        [
            [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)],
            [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)],
            [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)],
        ],
        dtype=np.float64,
    )


def transform_points(
    points: np.ndarray, position: np.ndarray, quaternion: np.ndarray
) -> np.ndarray:
    """把雷达坐标系下的点变换到世界坐标系：p_world = R @ p + t"""
    rot = quat_to_matrix(quaternion)
    pts = np.asarray(points, dtype=np.float64)
    return (pts @ rot.T + np.asarray(position, dtype=np.float64)).astype(np.float32)
