"""体素降采样：纯 numpy 实现，避免引入 open3d 额外依赖

内存优化要点：
- 全程 float32 计算，不做隐式 float64 提升
- 及时 del 中间数组，降低峰值内存
- 超大点云（> chunk_threshold）自动分块处理，避免一次性分配 GB 级中间数组
"""

from __future__ import annotations

from typing import Optional

import numpy as np


# 单次处理点数阈值：超过则分块
_CHUNK_THRESHOLD = 8_000_000
# 每块大小
_CHUNK_SIZE = 4_000_000


def voxel_downsample(
    points: np.ndarray,
    voxel_size: float,
    chunk_threshold: int = _CHUNK_THRESHOLD,
) -> np.ndarray:
    """按立方体网格降采样，每个体素保留第一个落入的点

    Args:
        points: (N, 3) float32/float64 数组
        voxel_size: 体素边长（单位与 points 一致，通常为米）
        chunk_threshold: 超过此点数自动分块处理（内存保护）

    Returns:
        (M, 3) float32 数组，M <= N。voxel_size <= 0 或 points 为空时原样返回。
    """
    if points.size == 0 or voxel_size <= 0:
        return points

    n = int(points.shape[0])
    if n <= chunk_threshold:
        return _voxel_downsample_single(points, voxel_size)

    # 分块处理：每块独立降采样，再对合并结果做一次全局降采样
    # 注意：分块降采样会有轻微边界效应（相邻块的同一位素可能被重复保留一次）
    # 最后再全局降采样一次消除重复
    chunks: list[np.ndarray] = []
    for start in range(0, n, _CHUNK_SIZE):
        end = min(start + _CHUNK_SIZE, n)
        chunk = points[start:end]
        chunks.append(_voxel_downsample_single(chunk, voxel_size))

    merged = np.concatenate(chunks, axis=0)
    del chunks
    return _voxel_downsample_single(merged, voxel_size)


def _voxel_downsample_single(points: np.ndarray, voxel_size: float) -> np.ndarray:
    """单块降采样核心实现"""
    pts = np.asarray(points, dtype=np.float32)

    # 用乘法代替除法，保持 float32（避免隐式 float64 提升）
    inv = np.float32(1.0) / np.float32(voxel_size)
    scaled = pts * inv
    indices = np.floor(scaled).astype(np.int64)
    del scaled

    # 平移到非负
    indices -= indices.min(axis=0)
    max_dim = int(indices.max()) + 1

    # 单维度小于 2^21 时用一维编码，unique 更快
    if max_dim < (1 << 21):
        flat = (indices[:, 0] * max_dim + indices[:, 1]) * max_dim + indices[:, 2]
        del indices
        _, unique_idx = np.unique(flat, return_index=True)
        del flat
    else:
        _, unique_idx = np.unique(indices, axis=0, return_index=True)
        del indices

    result = pts[unique_idx]
    del unique_idx
    return result.astype(np.float32, copy=False)


def voxel_downsample_with_scalars(
    points: np.ndarray,
    scalars: np.ndarray,
    voxel_size: float,
    chunk_threshold: int = _CHUNK_THRESHOLD,
) -> tuple[np.ndarray, np.ndarray]:
    """同步降采样坐标和标量（如反射强度）"""
    if points.size == 0 or voxel_size <= 0:
        return points, scalars

    n = int(points.shape[0])
    if n <= chunk_threshold:
        return _voxel_downsample_with_scalars_single(points, scalars, voxel_size)

    pts_chunks: list[np.ndarray] = []
    sca_chunks: list[np.ndarray] = []
    for start in range(0, n, _CHUNK_SIZE):
        end = min(start + _CHUNK_SIZE, n)
        p, s = _voxel_downsample_with_scalars_single(
            points[start:end], scalars[start:end], voxel_size
        )
        pts_chunks.append(p)
        sca_chunks.append(s)

    merged_pts = np.concatenate(pts_chunks, axis=0)
    merged_sca = np.concatenate(sca_chunks, axis=0)
    del pts_chunks, sca_chunks
    return _voxel_downsample_with_scalars_single(merged_pts, merged_sca, voxel_size)


def _voxel_downsample_with_scalars_single(
    points: np.ndarray, scalars: np.ndarray, voxel_size: float
) -> tuple[np.ndarray, np.ndarray]:
    pts = np.asarray(points, dtype=np.float32)
    sca = np.asarray(scalars, dtype=np.float32)

    inv = np.float32(1.0) / np.float32(voxel_size)
    scaled = pts * inv
    indices = np.floor(scaled).astype(np.int64)
    del scaled

    indices -= indices.min(axis=0)
    max_dim = int(indices.max()) + 1

    if max_dim < (1 << 21):
        flat = (indices[:, 0] * max_dim + indices[:, 1]) * max_dim + indices[:, 2]
        del indices
        _, unique_idx = np.unique(flat, return_index=True)
        del flat
    else:
        _, unique_idx = np.unique(indices, axis=0, return_index=True)
        del indices

    result_pts = pts[unique_idx]
    result_sca = sca[unique_idx]
    del unique_idx
    return result_pts.astype(np.float32, copy=False), result_sca.astype(np.float32, copy=False)
