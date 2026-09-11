"""FPS 监控：hook VTK RenderEvent 统计每秒实际渲染帧数"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal


class FPSMonitor(QObject):
    """统计 VTK 渲染窗口的实际 FPS

    实现：
    - AddObserver('RenderEvent') 累加帧计数
    - QTimer 每 sample_interval_ms 采样一次，计算 fps = 帧数 / 时间

    注意：VTK 只在真正调用 Render() 时触发 RenderEvent，交互拖动、
    流式更新都会走这条路径，因此这里统计的是"用户看到的帧率"。
    """

    fps_updated = Signal(float)

    def __init__(self, render_window, sample_interval_ms: int = 500, parent: QObject | None = None):
        super().__init__(parent)
        self._render_window = render_window
        self._frame_count = 0
        self._last_sample_time = time.perf_counter()
        self._interval_sec = sample_interval_ms / 1000.0
        self._observer_id: int | None = None

        if render_window is not None:
            self._observer_id = render_window.AddObserver("RenderEvent", self._on_render_event)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_sample_timer)
        self._timer.start(sample_interval_ms)

    def _on_render_event(self, _caller, _event) -> None:
        """VTK 观察者回调，签名固定为 (caller, event)"""
        self._frame_count += 1

    def _on_sample_timer(self) -> None:
        now = time.perf_counter()
        elapsed = now - self._last_sample_time
        fps = 0.0
        if elapsed > 1e-6:
            fps = self._frame_count / elapsed
        self.fps_updated.emit(fps)
        self._frame_count = 0
        self._last_sample_time = now

    def stop(self) -> None:
        """停止监控并清理观察者"""
        self._timer.stop()
        if self._observer_id is not None and self._render_window is not None:
            try:
                self._render_window.RemoveObserver(self._observer_id)
            except Exception:
                pass
            self._observer_id = None
