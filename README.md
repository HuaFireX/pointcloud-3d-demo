# 上位机 3D 点云显示方案验证 Demo

## 目的

验证 **PyVista + pyvistaqt (VTK 底层)** 方案在 AGV 上位机场景下能否满足以下需求，为后续正式集成到 `map_localization` 模块提供决策依据：

- 百万~千万级点云实时渲染
- SLAM 建图过程中的流式追加
- 交互：旋转 / 缩放 / 平移 / 剖面（GPU 裁剪） / 距离测量 / 点拾取
- AGV 车模型叠加显示
- 与 PySide6 主窗口原生嵌入（QWidget）

## 目录结构

```
pointcloud_3d_demo/
├── app.py                        # 入口
├── requirements.txt              # 依赖清单
├── README.md                     # 本文档
├── setup.bat / setup.sh          # 一键创建 venv + 安装依赖
├── run.bat / run.sh              # 启动 demo
├── scripts/
│   └── check_env.py              # 环境与依赖自检
├── src/
│   ├── bootstrap.py              # QApplication 引导
│   ├── models/
│   │   └── demo_state.py         # 场景状态（点数、形状、开关）
│   ├── views/
│   │   └── main_window.py        # 主窗口 + 控制面板
│   ├── controllers/
│   │   └── demo_controller.py    # 交互逻辑
│   └── services/
│       ├── pointcloud_renderer.py# PyVista QtInteractor 封装（图层、剖面、测量）
│       ├── synthetic_source.py   # 合成点云生成器（球体、网格、SLAM 流模拟）
│       ├── file_source.py        # 真实文件加载（.ply/.pcd/.csv/.xyz）
│       ├── voxel_downsample.py   # 体素降采样
│       ├── pose_source.py        # 位姿解析（alidarState.txt）+ 配准变换
│       └── fps_monitor.py        # 帧率统计
└── data/                         # 真实点云文件放这里（可选）
```

## 环境要求

- Python **3.10 ~ 3.12**（VTK/pyvista 目前对 3.13+ 支持不完整，3.14 无 wheel）
- Windows 10/11 或 Ubuntu 22.04
- 支持 OpenGL 3.3+ 的显卡（集显也够）

## 快速开始

### Windows
```bat
setup.bat
run.bat
```

### Linux
```bash
bash setup.sh
bash run.sh
```

`setup` 会在项目根目录创建 `.venv/`，并安装 requirements.txt 中列出的依赖（约 300MB，vtk 二进制较大）。

## 手动安装

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux
source .venv/bin/activate
pip install -r requirements.txt
python scripts/check_env.py    # 自检
python app.py                  # 启动
```

## 试验清单

启动 demo 后按下列顺序验证，勾选完成后即可判断方案是否达标：

- [ ] **T1 静态渲染性能**：形状选"随机立方体"，点数依次切 10 万 → 100 万 → 500 万 → 1000 万 → 5000 万，观察右下角 FPS。目标：100 万 ≥ 30fps，1000 万 ≥ 15fps（不开降采样）
- [ ] **T2 体素降采样效果**：点数 1000 万，勾选"体素降采样"，voxel_size 从 0.5 调到 0.05，观察 FPS 与视觉损失
- [ ] **T3 SLAM 建图流模拟**：勾选"实时流式追加"，观察长时间运行（≥5 分钟）内存是否稳定、FPS 是否下降；点击"清空累积"重置
- [ ] **T3b 真实序列回放（验证实时建图）**：静态合并渲染只能验证"能否画出"，验证不了持续渲染 FPS / 每帧延迟 / 内存增长。点"加载真实序列（用于回放）"选目录（只记文件列表+位姿，不一次性渲染），再点"播放"按录制帧率 10Hz 逐帧播放：当前帧红色 + 累积地图实时生长，状态栏 FPS + "帧: i/N" 进度实时可见；可调 0.5x~4x 倍速、暂停/停止。实测 company_wai 单帧端到端（读盘+配准+上传+渲染）mean 13.9ms / p95 20.2ms，10Hz 预算 100ms 内余量约 7 倍
- [ ] **T3c 回放视角切换面板**："回放视角"下拉四选一，均用 alidarState.txt 位姿驱动、平滑插值消抖：①**车后跟随**（车后 12m 上 7m 注视车前）；②**旁观者**（斜向侧俯视跟随，右侧 18m+上 12m+稍后 6m，默认离车 23m；**该模式下滚轮调节离车距离**，上滚拉近/下滚拉远，范围 5~80m，状态栏实时显示距离；滚轮被拦截不触发 VTK 缩放）；③**俯视跟随**（车正上方 45m 往下看、跟随位置、北向上）；④**上帝视角**（固定全局俯瞰不跟车，切换时立即 fit 全场景）。实测 company_wai12：third 相机-车 15.8m / observer 默认 23m、滚轮 5 次上滚→15.2m、8 次下滚→28.1m、钳制 5/80m / top 正上方 45m / god 全程位移 0
- [ ] **T4 GPU 剖面**：勾选"启用剖面"，拖动三个滑块调整法向和原点，确认点云被裁剪且 FPS 不掉（GPU 侧裁剪）
- [ ] **T5 距离测量**：勾选"测量工具"，在点云上点两点，观察顶部标题栏显示距离
- [ ] **T6 点拾取**：勾选"点拾取"，点击点云任意点，状态栏显示坐标
- [ ] **T7 车模型叠加**：勾选"显示 AGV 车模型"，确认蓝色立方体渲染正常，随视角一起变换；**回放时车模型按 alidarState.txt 位姿（位置+四元数朝向）逐帧变换到车当前位姿**，跟着回放跑（实测车模型中心与位姿位置恒定差 0.2m = 模型自身中心高度偏移，即精确贴合）
- [ ] **T8 真实文件加载**：把 `.ply`/`.pcd`/`.csv` 放到 `data/`，点"加载文件"（**可框选多个**）或"加载整个目录"（合并目录下全部点云，按数字自然序），确认渲染正常。`.pcd` 走本模块**原生解析器**（pyvista/VTK 默认不带 PCD reader），支持 ascii / binary / binary_compressed 三种编码
- [ ] **T8b 位姿配准拼接**：目录含 `alidarState.txt`（每行：时间戳+位置+四元数+…，与 pcd 帧一一对应）时，勾选"按位姿配准拼接"，多帧会按 `p_world = R(quat)·p_lidar + pos` 变换到世界系再合并，消除移动平台的拖影。实测 company_wai 548 帧配准后 0.2m 体素占用从 115,970 降到 40,916（-65%）。位姿文件是 `.txt` 但**不是点云**，目录加载时会自动排除，避免被误解析成"时间戳当坐标"的垃圾点
- [ ] **T8c 多目录叠加**：点"叠加新目录"可把多个目录各自作为**独立图层**加入（独立颜色、独立可见性复选框、重名目录自动加序号），每个目录用自己的 alidarState.txt 配准；"清空叠加图层"一键移除。适合多趟扫描/多批次数据对比
- [ ] **T8d 超大目录性能**：对上万帧的长录制（如 company_wai12 = 16,925 帧 / 580MB / ~2850 万点），三项优化防"加载慢+交互卡"：①**加载步长**（每 N 帧取 1，>5000 帧且步长=1 时自动设步长并提示）；②**线程池并行解析**（load_multiple / 配准加载均 8 线程）；③**点数预算自动降采样**（默认 300 万，超预算先用 0.1m 细 voxel、仍超再按 sqrt(n/budget) 放大 voxel，表面感知不过杀）。实测 company_wai12 自动步长 4 → 4232 帧 → 215 万点，端到端 6.05s，交互流畅
- [ ] **T9 图层管理**：勾选/取消"显示全局地图"/"显示当前帧"，确认图层独立可见
- [ ] **T10 内存占用**：任务管理器/htop 观察 5000 万点时进程内存，判断是否可接受

## 关键性能设计（代码已实现）

1. **GPU 侧剖面**：用 `vtkMapper.SetClippingPlanes(vtkPlaneCollection)`，零 CPU 开销。避免 `add_mesh_clip_plane`（每次重建 mesh）
2. **点渲染用 `GL_POINTS`**：`render_points_as_spheres=False`，比球体快 10 倍以上
3. **分层 actor**：全局地图、当前帧、车模型各自独立 actor，只更新变化的层
4. **体素降采样在渲染前**：CPU 侧一次哈希，O(N) 时间，>800 万点自动分块避免内存峰值
5. **流式追加**：全局地图层每 20 帧才更新一次，当前帧层每帧更新
6. **numpy 直接映射**：`pv.PolyData(xyz)` 零拷贝构造

## 实测性能（headless / Windows 11 / Python 3.12.9 / VTK 9.7 / pyvista 0.49）

`scripts/perf_test.py` 压测结果，作为集成前的性能基线：

| 点数 | 生成 (s) | 上传 GPU (s) | 单帧渲染 (s) | 内存增量 (MB) | 体素降采样 0.1m (s) | 降采样后点数 |
|---:|---:|---:|---:|---:|---:|---:|
| 100k | 0.003 | 0.004 | <0.001 | 1.9 | 0.019 | 99,927 |
| 1M | 0.020 | 0.023 | <0.001 | 14.7 | 0.246 | 992,099 |
| 5M (room) | 0.251 | 0.110 | <0.001 | 76.5 | 1.122 | 184,010 |
| 10M | 0.202 | 0.205 | <0.001 | 187.2 | 4.422 | 9,257,547 |
| 30M | 2.795 | 0.727 | <0.001 | 395.6 | 14.150 | 12,484,562 |

结论：
- **上传 GPU 是线性的**：百万级 ~20ms，千万级 ~200ms，3000 万 ~730ms。**百万级实时流式（10Hz）完全可行**，千万级需要降采样或分块
- **headless 单帧渲染 <1ms**：有显示器时会更高，但百万级 30fps、千万级 15fps 是合理预期
- **体素降采样是 CPU 瓶颈**：`np.unique` 对千万级要秒级，**不能每帧降采样**，只能对全局地图周期性降采样
- **内存**：30M 点云进程 RSS 约 480MB，可接受；再往上需要八叉树 LOD 或流式加载

## 后续集成到 `map_localization` 的路径

demo 稳定后按以下映射迁入主项目（AGENTS.md 的分层约定）：

| Demo 文件 | 迁入路径 |
|---|---|
| `services/pointcloud_renderer.py` | `src/modules/map_localization/services/pointcloud_3d_service.py` |
| `services/synthetic_source.py`（部分）| 保留在 demo，不进主项目 |
| `services/file_source.py` | `src/modules/map_localization/services/pointcloud_file_loader.py` |
| `services/voxel_downsample.py` | `src/platform/common/voxel_downsample.py`（跨模块可复用） |
| `views/main_window.py` 的中央视图部分 | `src/modules/map_localization/views/pointcloud_3d_view.py` |
| `controllers/demo_controller.py` | `src/modules/map_localization/controllers/pointcloud_3d_controller.py` |
| `models/demo_state.py` | `src/modules/map_localization/models/pointcloud_3d_state.py` |

## 已知局限

- Demo 只覆盖渲染性能与交互验证，不涉及坐标系变换、多雷达融合、时间同步等业务逻辑
- 车模型是占位立方体，实际集成需替换为真实 `.obj`/`.stl`
- 未做多线程数据加载（大文件读取会阻塞 UI 一次）

## 故障排查

- **启动黑屏/闪退**：先跑 `python scripts/check_env.py`，确认 OpenGL 版本 ≥ 3.3
- **vtk 装不上**：Python 3.13/3.14 目前没有 wheel，用 3.10~3.12
- **点数超过 5000 万卡死**：正常，VTK 单 actor 极限约 1 亿点，超过需要八叉树 LOD（demo 未实现，生产可加 `vtkLODActor` 或分块）
- **剖面无效果**：确认法向不全为 0，且原点坐标在点云包围盒内
