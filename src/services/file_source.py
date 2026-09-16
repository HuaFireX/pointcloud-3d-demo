"""真实点云文件加载：.ply / .pcd / .vtk / .vtp / .xyz / .txt / .csv

.pcd 走本模块自带的原生解析器（pyvista/VTK 默认不带 PCD reader），
支持 ascii / binary / binary_compressed 三种 DATA 编码。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np


SUPPORTED_SUFFIXES = (".ply", ".pcd", ".vtk", ".vtp", ".xyz", ".txt", ".csv")

# PCD 字段类型 -> numpy dtype
_PCD_TYPE_MAP = {
    ("F", 4): "<f4",
    ("F", 8): "<f8",
    ("U", 1): "<u1",
    ("U", 2): "<u2",
    ("U", 4): "<u4",
    ("I", 1): "<i1",
    ("I", 2): "<i2",
    ("I", 4): "<i4",
}

# 离群点清洗阈值：任一坐标绝对值超过此值视为哨兵/无效点（单位米）
# 真实 AGV 激光雷达量程远小于 10km，此阈值只会剔除哨兵点（如 1.79e9 这类无效回波标记）
DEFAULT_MAX_ABS_COORD = 10_000.0


def sanitize_points(
    points: np.ndarray,
    scalars: Optional[np.ndarray] = None,
    max_abs_coord: float = DEFAULT_MAX_ABS_COORD,
) -> tuple[np.ndarray, Optional[np.ndarray]]:
    """清洗点云：丢弃 NaN / inf / 坐标绝对值超阈值的哨兵点

    激光雷达常在某些帧写入"无效回波"哨兵点（如 x=1.79e9），这些点会把
    包围盒撑爆，导致 reset_camera 后真实点云缩成一个点。加载后统一清洗。

    Args:
        points: (N, 3) 坐标
        scalars: (N,) 标量或 None，与 points 同步过滤
        max_abs_coord: 单坐标绝对值上限（米）

    Returns:
        (clean_points, clean_scalars)
    """
    pts = np.asarray(points, dtype=np.float32)
    if pts.size == 0:
        return pts, scalars

    finite = np.isfinite(pts).all(axis=1)
    in_range = (np.abs(pts) <= max_abs_coord).all(axis=1)
    keep = finite & in_range

    if keep.all():
        return pts, scalars

    clean_pts = pts[keep]
    clean_scalars: Optional[np.ndarray] = None
    if scalars is not None:
        sca = np.asarray(scalars, dtype=np.float32)
        if sca.shape[0] == pts.shape[0]:
            clean_scalars = sca[keep]
    return clean_pts, clean_scalars


def load_pointcloud(
    path: str | Path,
    sanitize: bool = True,
    max_abs_coord: float = DEFAULT_MAX_ABS_COORD,
) -> tuple[np.ndarray, Optional[np.ndarray]]:
    """加载点云文件

    Args:
        path: 文件路径
        sanitize: 是否清洗哨兵/离群点（默认 True）
        max_abs_coord: 清洗阈值（米）

    Returns:
        (points, intensities)
        points: (N, 3) float32
        intensities: (N,) float32 或 None（文件无标量时）
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {p}")

    suffix = p.suffix.lower()
    if suffix == ".pcd":
        pts, inten = _load_pcd(p)
    elif suffix in (".ply", ".vtk", ".vtp"):
        pts, inten = _load_via_pyvista(p)
    elif suffix in (".xyz", ".txt"):
        pts, inten = _load_ascii_whitespace(p)
    elif suffix == ".csv":
        pts, inten = _load_csv(p)
    else:
        raise ValueError(f"不支持的文件类型: {suffix}，仅支持 {SUPPORTED_SUFFIXES}")

    if sanitize:
        pts, inten = sanitize_points(pts, inten, max_abs_coord)
    return pts, inten


def list_pointcloud_files(
    directory: str | Path, exclude: Optional[list] = None
) -> list[Path]:
    """列出目录下所有支持的点云文件，按自然序（数字感知）排序

    自然序保证 0,1,2,...,10,...,100 的正确顺序，而非字典序 0,1,10,100,101,...
    仅扫描顶层目录，不递归子目录。

    Args:
        directory: 目录路径
        exclude: 需排除的文件路径列表（如位姿文件 alidarState.txt，
                 它是 .txt 但并非点云，混入会被误解析成"时间戳当坐标"的垃圾点）
    """
    d = Path(directory)
    if not d.is_dir():
        raise NotADirectoryError(f"不是有效目录: {d}")

    excluded = {Path(e).resolve() for e in (exclude or [])}
    files = []
    for p in d.iterdir():
        if not p.is_file() or p.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if p.resolve() in excluded:
            continue
        files.append(p)
    files.sort(key=_natural_sort_key)
    return files


def _natural_sort_key(path: Path):
    """自然序排序键：把文件名中的数字段按整数比较"""
    import re

    parts = re.split(r"(\d+)", path.stem)
    key: list = []
    for part in parts:
        if part.isdigit():
            key.append((1, int(part), ""))
        else:
            key.append((0, 0, part.lower()))
    return key


def load_multiple(
    paths: list[str | Path],
    progress_callback=None,
    max_workers: int = 8,
) -> tuple[np.ndarray, Optional[np.ndarray], int, int]:
    """加载多个点云文件并合并为一个点云（线程池并行解析，IO 密集提速明显）

    Args:
        paths: 文件路径列表
        progress_callback: 可选回调 fn(loaded_index, total, current_path)，用于进度提示
        max_workers: 并行线程数

    Returns:
        (points, intensities, ok_count, fail_count)
        points: (N, 3) float32 合并后的坐标
        intensities: (N,) float32 或 None（仅当所有文件都含强度时保留）
        ok_count: 成功加载的文件数
        fail_count: 失败的文件数
    """
    total = len(paths)
    if total == 0:
        return np.zeros((0, 3), dtype=np.float32), None, 0, 0

    def _load_one(raw_path):
        try:
            return load_pointcloud(raw_path)
        except Exception:
            return None

    workers = max(1, min(max_workers, total))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_load_one, paths))

    all_pts: list[np.ndarray] = []
    all_int: list[np.ndarray] = []
    all_have_intensity = True
    ok_count = 0
    fail_count = 0

    for idx, (raw_path, result) in enumerate(zip(paths, results)):
        if result is None:
            fail_count += 1
        else:
            pts, inten = result
            if pts.shape[0] == 0:
                pass
            else:
                all_pts.append(pts)
                if inten is None:
                    all_have_intensity = False
                    all_int.append(np.zeros(pts.shape[0], dtype=np.float32))
                else:
                    all_int.append(np.asarray(inten, dtype=np.float32))
                ok_count += 1

        if progress_callback is not None:
            progress_callback(idx + 1, total, str(raw_path))

    if not all_pts:
        return np.zeros((0, 3), dtype=np.float32), None, ok_count, fail_count

    merged_pts = np.concatenate(all_pts, axis=0).astype(np.float32)
    merged_int: Optional[np.ndarray] = None
    if all_have_intensity and all_int:
        merged_int = np.concatenate(all_int, axis=0).astype(np.float32)

    return merged_pts, merged_int, ok_count, fail_count


# ================================================================
# PCD 写出
# ================================================================


def save_pcd(
    path: str | Path,
    points: np.ndarray,
    scalars: Optional[np.ndarray] = None,
    binary: bool = True,
) -> int:
    """把点云写成单个 PCD 文件（与解析器格式对齐，可被本模块/VTK/PCL 读回）

    Args:
        path: 输出路径（.pcd）
        points: (N, 3) 坐标
        scalars: (N,) 强度标量或 None；有则写 FIELDS x y z intensity
        binary: True 写 binary（紧凑快速），False 写 ascii

    Returns:
        写出的点数 N
    """
    pts = np.asarray(points, dtype=np.float32)
    n = int(pts.shape[0])
    has_int = scalars is not None and np.asarray(scalars).shape[0] == n

    fields = ["x", "y", "z", "intensity"] if has_int else ["x", "y", "z"]
    nf = len(fields)
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\n"
        "VERSION 0.7\n"
        f"FIELDS {' '.join(fields)}\n"
        f"SIZE {' '.join(['4'] * nf)}\n"
        f"TYPE {' '.join(['F'] * nf)}\n"
        f"COUNT {' '.join(['1'] * nf)}\n"
        f"WIDTH {n}\n"
        "HEIGHT 1\n"
        "VIEWPOINT 0 0 0 1 0 0 0\n"
        f"POINTS {n}\n"
        f"DATA {'binary' if binary else 'ascii'}\n"
    )

    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        if binary:
            dtype = np.dtype([(name, "<f4") for name in fields])
            arr = np.zeros(n, dtype=dtype)
            arr["x"], arr["y"], arr["z"] = pts[:, 0], pts[:, 1], pts[:, 2]
            if has_int:
                arr["intensity"] = np.asarray(scalars, dtype=np.float32)
            f.write(arr.tobytes())
        else:
            data = np.column_stack([pts, np.asarray(scalars, dtype=np.float32)]) if has_int else pts
            np.savetxt(f, data, fmt="%.6f")

    return n


# ================================================================
# PCD 原生解析
# ================================================================


def _load_pcd(path: Path) -> tuple[np.ndarray, Optional[np.ndarray]]:
    """解析 PCD 文件（Point Cloud Library 标准格式）

    支持 DATA = ascii / binary / binary_compressed
    """
    with open(path, "rb") as f:
        raw = f.read()

    header, data_mode, body_offset = _parse_pcd_header(raw)

    fields = header.get("FIELDS")
    sizes = header.get("SIZE")
    types = header.get("TYPE")
    counts = header.get("COUNT")
    n_points = header.get("POINTS")

    if fields is None or sizes is None or types is None:
        raise ValueError("PCD 头缺少 FIELDS/SIZE/TYPE，无法解析")

    n_fields = len(fields)
    if counts is None:
        counts = [1] * n_fields

    if n_points is None:
        width = header.get("WIDTH") or 0
        height = header.get("HEIGHT") or 1
        n_points = width * height
    n_points = int(n_points)

    if n_points == 0:
        return np.zeros((0, 3), dtype=np.float32), None

    body = raw[body_offset:]

    if data_mode == "ascii":
        arrays = _pcd_read_ascii(body, fields, sizes, types, counts, n_points)
    elif data_mode == "binary":
        arrays = _pcd_read_binary(body, fields, sizes, types, counts, n_points)
    elif data_mode == "binary_compressed":
        arrays = _pcd_read_binary_compressed(body, fields, sizes, types, counts, n_points)
    else:
        raise ValueError(f"不支持的 PCD DATA 模式: {data_mode!r}")

    points = _extract_xyz(arrays, fields)
    intensity = _extract_intensity(arrays, fields)
    return points, intensity


def _parse_pcd_header(raw: bytes) -> tuple[dict, str, int]:
    """逐行解析 PCD 头，返回 (header_dict, data_mode, body_offset)

    body_offset 是 DATA 行换行符之后的字节位置
    """
    header: dict = {}
    data_mode = "ascii"
    body_offset = len(raw)

    pos = 0
    while pos < len(raw):
        nl = raw.find(b"\n", pos)
        if nl == -1:
            line_bytes = raw[pos:]
            next_pos = len(raw)
        else:
            line_bytes = raw[pos:nl]
            next_pos = nl + 1

        line = line_bytes.rstrip(b"\r").decode("ascii", errors="ignore").strip()
        pos = next_pos

        if not line or line.startswith("#"):
            continue

        parts = line.split()
        key = parts[0].upper()
        vals = parts[1:]

        if key == "DATA":
            data_mode = vals[0].lower() if vals else "ascii"
            body_offset = pos
            break

        if key == "FIELDS":
            header["FIELDS"] = vals
        elif key == "SIZE":
            header["SIZE"] = [int(v) for v in vals]
        elif key == "TYPE":
            header["TYPE"] = [v.upper() for v in vals]
        elif key == "COUNT":
            header["COUNT"] = [int(v) for v in vals]
        elif key == "POINTS":
            header["POINTS"] = int(vals[0])
        elif key == "WIDTH":
            header["WIDTH"] = int(vals[0])
        elif key == "HEIGHT":
            header["HEIGHT"] = int(vals[0])

    return header, data_mode, body_offset


def _build_structured_dtype(
    fields: list[str], sizes: list[int], types: list[str], counts: list[int]
) -> np.dtype:
    """根据 PCD 头构造 numpy structured dtype（用于 binary AoS 布局）"""
    names: list[str] = []
    formats: list = []
    for i, fname in enumerate(fields):
        key = (types[i], sizes[i])
        if key not in _PCD_TYPE_MAP:
            raise ValueError(f"不支持的 PCD 字段类型: TYPE={types[i]} SIZE={sizes[i]}")
        base = _PCD_TYPE_MAP[key]
        # 字段名可能重复（少见），加序号去重
        unique_name = fname if fname not in names else f"{fname}_{i}"
        names.append(unique_name)
        if counts[i] > 1:
            formats.append((base, (counts[i],)))
        else:
            formats.append(base)
    return np.dtype({"names": names, "formats": formats})


def _pcd_read_ascii(
    body: bytes,
    fields: list[str],
    sizes: list[int],
    types: list[str],
    counts: list[int],
    n_points: int,
) -> dict[str, np.ndarray]:
    """解析 ascii DATA：每行一个点，字段按 COUNT 展开"""
    text = body.decode("ascii", errors="ignore")
    total_cols = sum(counts)
    rows: list[list[float]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        tokens = line.split()
        if len(tokens) < total_cols:
            continue
        try:
            rows.append([float(t) for t in tokens[:total_cols]])
        except ValueError:
            continue
        if len(rows) >= n_points:
            break

    if not rows:
        return {f: np.zeros((0,), dtype=np.float32) for f in fields}

    data = np.asarray(rows, dtype=np.float64)
    arrays: dict[str, np.ndarray] = {}
    col = 0
    for i, fname in enumerate(fields):
        key = (types[i], sizes[i])
        dt = np.dtype(_PCD_TYPE_MAP.get(key, "<f4"))
        c = counts[i]
        block = data[:, col : col + c].astype(dt)
        arrays[fname] = block[:, 0] if c == 1 else block
        col += c
    return arrays


def _pcd_read_binary(
    body: bytes,
    fields: list[str],
    sizes: list[int],
    types: list[str],
    counts: list[int],
    n_points: int,
) -> dict[str, np.ndarray]:
    """解析 binary DATA：AoS 布局，每个点的字段连续存放"""
    dtype = _build_structured_dtype(fields, sizes, types, counts)
    itemsize = dtype.itemsize

    expected = itemsize * n_points
    if len(body) < expected:
        # 数据不足时按实际能容纳的点数解析
        actual = len(body) // itemsize
        if actual == 0:
            raise ValueError("PCD binary 数据体为空或长度不足")
        n_points = actual

    data = np.frombuffer(body[: itemsize * n_points], dtype=dtype, count=n_points)
    arrays: dict[str, np.ndarray] = {}
    for i, fname in enumerate(fields):
        col_name = fname if fname in data.dtype.names else f"{fname}_{i}"
        arrays[fname] = np.asarray(data[col_name])
    return arrays


def _pcd_read_binary_compressed(
    body: bytes,
    fields: list[str],
    sizes: list[int],
    types: list[str],
    counts: list[int],
    n_points: int,
) -> dict[str, np.ndarray]:
    """解析 binary_compressed DATA：LZF 压缩 + SoA 布局

    PCL 的 binary_compressed 格式：
    - uint32 compressed_size
    - uint32 uncompressed_size
    - LZF 压缩数据
    解压后是按字段（SoA）排列，而非按点（AoS）
    """
    if len(body) < 8:
        raise ValueError("PCD binary_compressed 数据体过短")

    compressed_size = int(np.frombuffer(body[0:4], dtype="<u4")[0])
    uncompressed_size = int(np.frombuffer(body[4:8], dtype="<u4")[0])
    compressed = body[8 : 8 + compressed_size]

    decompressed = _lzf_decompress(compressed, uncompressed_size)

    arrays: dict[str, np.ndarray] = {}
    offset = 0
    for i, fname in enumerate(fields):
        key = (types[i], sizes[i])
        if key not in _PCD_TYPE_MAP:
            raise ValueError(f"不支持的 PCD 字段类型: TYPE={types[i]} SIZE={sizes[i]}")
        dt = np.dtype(_PCD_TYPE_MAP[key])
        c = counts[i]
        nbytes = dt.itemsize * c * n_points
        block = np.frombuffer(decompressed[offset : offset + nbytes], dtype=dt)
        if c == 1:
            arrays[fname] = block.reshape(n_points)
        else:
            arrays[fname] = block.reshape(n_points, c)
        offset += nbytes
    return arrays


def _lzf_decompress(compressed: bytes, expected_len: int) -> bytes:
    """LZF 解压（liblzf 算法），PCL binary_compressed 使用"""
    out = bytearray(expected_len)
    i = 0
    o = 0
    n = len(compressed)

    while i < n:
        ctrl = compressed[i]
        i += 1
        if ctrl < 32:
            # 字面量运行：ctrl+1 个字节
            length = ctrl + 1
            out[o : o + length] = compressed[i : i + length]
            i += length
            o += length
        else:
            # 回引
            length = ctrl >> 5
            if length == 7:
                length += compressed[i]
                i += 1
            ref = o - ((ctrl & 0x1F) << 8) - compressed[i] - 1
            i += 1
            length += 2
            if ref < 0:
                raise ValueError("LZF 解压失败：回引偏移非法")
            for _ in range(length):
                out[o] = out[ref]
                o += 1
                ref += 1

    return bytes(out[:o])


def _extract_xyz(arrays: dict[str, np.ndarray], fields: list[str]) -> np.ndarray:
    """从字段字典里提取 x/y/z 组成 (N,3) float32"""
    lower_map = {f.lower(): f for f in fields}
    for axis in ("x", "y", "z"):
        if axis not in lower_map:
            raise ValueError(f"PCD 缺少坐标字段 '{axis}'，实际字段: {fields}")

    n = arrays[lower_map["x"]].shape[0]
    out = np.zeros((n, 3), dtype=np.float32)
    for col, axis in enumerate(("x", "y", "z")):
        out[:, col] = np.asarray(arrays[lower_map[axis]], dtype=np.float32).ravel()[:n]
    return out


def _extract_intensity(
    arrays: dict[str, np.ndarray], fields: list[str]
) -> Optional[np.ndarray]:
    """尝试提取强度字段，找不到返回 None"""
    lower_map = {f.lower(): f for f in fields}
    for key in ("intensity", "reflectivity", "scalar", "gray", "ring"):
        if key in lower_map:
            arr = np.asarray(arrays[lower_map[key]], dtype=np.float32).ravel()
            return arr
    return None


# ================================================================
# 其他格式
# ================================================================


def _load_via_pyvista(path: Path) -> tuple[np.ndarray, Optional[np.ndarray]]:
    """通过 pyvista 加载 .ply/.vtk/.vtp"""
    import pyvista as pv

    mesh = pv.read(str(path))
    pts = np.asarray(mesh.points, dtype=np.float32)

    intensity: Optional[np.ndarray] = None
    if mesh.point_data:
        for key in ("intensity", "Intensity", "reflectivity", "scalar", "scalars", "gray"):
            if key in mesh.point_data:
                intensity = np.asarray(mesh.point_data[key], dtype=np.float32)
                break
    return pts, intensity


def _load_ascii_whitespace(path: Path) -> tuple[np.ndarray, Optional[np.ndarray]]:
    """.xyz / .txt：空格分隔，可选首行注释（# 开头）"""
    rows: list[list[float]] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tokens = line.replace(",", " ").split()
            if len(tokens) < 3:
                continue
            try:
                row = [float(tok) for tok in tokens]
            except ValueError:
                continue
            rows.append(row)

    if not rows:
        return np.zeros((0, 3), dtype=np.float32), None

    max_cols = max(len(r) for r in rows)
    data = np.zeros((len(rows), max_cols), dtype=np.float32)
    for i, row in enumerate(rows):
        data[i, : len(row)] = row

    pts = data[:, :3]
    intensity = data[:, 3] if data.shape[1] >= 4 else None
    return pts, intensity


def _load_csv(path: Path) -> tuple[np.ndarray, Optional[np.ndarray]]:
    """CSV：自动检测表头"""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        first_line = f.readline().strip()

    has_header = not _is_numeric_row(first_line, delimiter=",")

    data = np.loadtxt(
        str(path),
        dtype=np.float32,
        delimiter=",",
        skiprows=1 if has_header else 0,
        ndmin=2,
    )
    if data.size == 0:
        return np.zeros((0, 3), dtype=np.float32), None

    pts = data[:, :3]
    intensity = data[:, 3] if data.shape[1] >= 4 else None
    return pts.astype(np.float32), intensity


def _is_numeric_row(line: str, delimiter: str = ",") -> bool:
    """判断一行是否为纯数字（用于表头检测）"""
    if not line:
        return False
    tokens = line.split(delimiter)
    numeric_count = 0
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        try:
            float(tok)
            numeric_count += 1
        except ValueError:
            return False
    return numeric_count >= 3
