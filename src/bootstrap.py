"""QApplication 引导：创建主窗口、控制器，进入事件循环"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from src.controllers.demo_controller import DemoController
from src.views.main_window import MainWindow


def run() -> int:
    """应用入口"""
    app = QApplication(sys.argv)
    app.setApplicationName("Pointcloud3DDemo")
    app.setOrganizationName("RCS5.0")

    window = MainWindow()
    controller = DemoController(window)

    # QApplication 退出前释放控制器资源（停止 QTimer、注销 VTK observer）
    app.aboutToQuit.connect(controller.shutdown)

    window.show()

    exit_code = app.exec()
    return exit_code
