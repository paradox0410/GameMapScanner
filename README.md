Game Map Auto Scanner

基于 Python、ADB、OpenCV 和 Tkinter 实现的模拟器地图自动扫描工具。

通过 ADB 与 Android 模拟器通信，实现自动截图、地图滑动、区域遍历和扫描结果保存，并提供图形化操作界面。

主要功能
自动检测常见 Android 模拟器 ADB 环境
通过 ADB 获取模拟器实时截图
自动执行横向、纵向地图滑动
按蛇形路径遍历大规模游戏地图
自动保存并按照扫描位置命名截图
Tkinter 图形化控制界面
扫描任务使用独立线程运行，避免阻塞 GUI
技术栈

Python / OpenCV / NumPy / Pillow / Tkinter / Android ADB

使用方法
安装 Python 3。
安装项目依赖：pip install -r requirements.txt
启动 Android 模拟器并开启 ADB。
运行 python main.py。
在程序中测试 ADB 连接并开始扫描。
项目原理

程序通过 ADB 控制模拟器完成地图拖动，并按照预设的扫描路径遍历地图。每次移动后获取当前屏幕截图，并根据扫描行、列以及移动方向自动保存结果，从而实现对大型地图的自动化采集。