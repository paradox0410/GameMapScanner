import cv2
import numpy as np
import subprocess
import os
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
import threading
import shutil
import sys


# Windows 控制台中文输出支持
sys.stdout.reconfigure(encoding="utf-8")
os.environ["PYTHONIOENCODING"] = "utf-8"


class RebelScanner:
    """通过 ADB 控制 Android 模拟器并自动扫描大型游戏地图。"""

    def __init__(self, adb_path=None):
        self.regions = {}

        # ==================== 地图网格与扫描参数 ====================
        self.game_grid_total = (200, 200)
        self.screen_grid_show = (4, 9)

        # 单个地图网格的像素尺寸
        self.grid_pixel_w = 138
        self.grid_pixel_h = 90

        # 相邻扫描区域保留一定重叠，降低漏扫概率
        self.overlap = (1, 1)

        # 屏幕可视区域的理论像素尺寸
        self.screen_total_w = (
            self.screen_grid_show[1] * self.grid_pixel_w
        )
        self.screen_total_h = (
            self.screen_grid_show[0] * self.grid_pixel_h
        )

        # 理论滑动步长
        self.slide_step_x = (
            (4 - self.overlap[1]) * self.grid_pixel_w
        )
        self.slide_step_y = (
            (self.screen_grid_show[0] - self.overlap[0])
            * self.grid_pixel_h
        )

        # 理论扫描屏数
        self.total_slide_x = (
            (self.game_grid_total[0] - self.overlap[1])
            // (self.screen_grid_show[1] - self.overlap[1])
        )
        self.total_slide_y = (
            (self.game_grid_total[1] - self.overlap[0])
            // (self.screen_grid_show[0] - self.overlap[0])
        )

        # ==================== 运行状态 ====================
        self.is_scanning = False
        self.progress_callback = None

        # 每移动 N 步获取一次截图
        self.detect_every_n_steps = 1
        self.step_counter = 0

        # ==================== 文件目录 ====================
        self.screenshot_dir = "screenshots"
        self.scan_screenshot_dir = "scan_screenshots"

        os.makedirs(self.screenshot_dir, exist_ok=True)
        os.makedirs(self.scan_screenshot_dir, exist_ok=True)

        # ==================== ADB ====================
        self.adb_path = adb_path or self.find_adb_path()

        # 当前适配的模拟器分辨率
        self.emulator_width = 563
        self.emulator_height = 1031

        # 滑动基准位置：模拟器屏幕中心
        self.base_x = self.emulator_width // 2
        self.base_y = self.emulator_height // 2

        # 根据实际运行环境调校的横向滑动距离
        self.slide_step_x_px = 662

        # 纵向理论滑动距离：(4 - 1) × 90 = 270 px
        self.slide_step_y_px = self.slide_step_y

    # ============================================================
    # ADB 与截图
    # ============================================================

    def find_adb_path(self):
        """自动寻找系统或常见 Android 模拟器中的 ADB。"""

        adb_in_path = shutil.which("adb")
        if adb_in_path:
            return os.path.normpath(adb_in_path)

        common_paths = [
            r"C:\Program Files\BlueStacks\HD-Adb.exe",
            r"C:\Program Files (x86)\BlueStacks\HD-Adb.exe",
            r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
            r"C:\Program Files (x86)\BlueStacks_nxt\HD-Adb.exe",
            r"C:\LDPlayer\LDPlayer9\adb.exe",
            r"C:\Program Files (x86)\Nox\bin\nox_adb.exe",
            os.path.expanduser(
                r"~\AppData\Local\Android\Sdk\platform-tools\adb.exe"
            ),
        ]

        for path in common_paths:
            normalized_path = os.path.normpath(path)

            if os.path.exists(normalized_path):
                return normalized_path

        print("警告：未自动找到 ADB，将尝试使用系统 PATH 中的 adb。")
        return "adb"

    def get_adb_command(self, *args):
        """构造 ADB 命令。"""

        if os.path.exists(self.adb_path):
            adb_path = os.path.normpath(self.adb_path)
        else:
            adb_path = self.adb_path

        return [adb_path] + list(args)

    def check_adb(self):
        """检查 ADB 是否可以正常运行。"""

        try:
            subprocess.run(
                self.get_adb_command("start-server"),
                capture_output=True,
                timeout=3,
            )

            result = subprocess.run(
                self.get_adb_command("version"),
                capture_output=True,
                text=True,
                timeout=5,
            )

            return result.returncode == 0

        except Exception as e:
            print(f"ADB 检查失败：{e}")
            return False

    def take_screenshot(self):
        """
        通过 ADB 获取模拟器截图。

        截图首先保存到 Android 设备临时目录，
        随后拉取到本地并转换为 OpenCV 图像。
        """

        temp_path = "/sdcard/screenshot_temp.png"
        local_path = os.path.join(
            self.screenshot_dir,
            "temp_screenshot.png",
        )

        try:
            # 在 Android 设备中生成截图
            cmd_save = self.get_adb_command(
                "shell",
                "screencap",
                "-p",
                temp_path,
            )

            subprocess.run(
                cmd_save,
                capture_output=True,
                timeout=5,
                check=True,
            )

            # 将截图拉取到本地
            cmd_pull = self.get_adb_command(
                "pull",
                temp_path,
                local_path,
            )

            subprocess.run(
                cmd_pull,
                capture_output=True,
                timeout=5,
                check=True,
            )

            # 使用 Pillow 读取文件，兼容 Windows 中文路径
            pil_image = Image.open(local_path).convert("RGB")

            image = cv2.cvtColor(
                np.array(pil_image),
                cv2.COLOR_RGB2BGR,
            )

            # 删除 Android 设备中的临时截图
            subprocess.run(
                self.get_adb_command(
                    "shell",
                    "rm",
                    temp_path,
                ),
                capture_output=True,
                timeout=2,
            )

            return image

        except Exception as e:
            print(f"截图失败：{e}")
            return None

    def save_scan_screenshot(
        self,
        image,
        physical_row,
        col,
        step_type,
    ):
        """按照扫描位置和移动方向保存截图。"""

        try:
            filename = (
                f"行{physical_row}_列{col}_{step_type}.png"
            )

            save_path = os.path.join(
                self.scan_screenshot_dir,
                filename,
            )

            # imencode + tofile 可兼容 Windows 中文路径
            cv2.imencode(
                ".png",
                image,
            )[1].tofile(save_path)

        except Exception as e:
            print(f"截图保存失败：{e}")

    # ============================================================
    # 地图滑动
    # ============================================================

    def fast_drag(self, direction="left", retry=2):
        """通过 ADB swipe 命令控制地图移动。"""

        for _ in range(retry + 1):
            try:
                start_x = self.base_x
                start_y = self.base_y

                end_x = start_x
                end_y = start_y

                if direction == "left":
                    end_x = start_x - self.slide_step_x_px

                elif direction == "right":
                    end_x = start_x + self.slide_step_x_px

                elif direction == "down":
                    end_y = (
                        start_y
                        - self.slide_step_y_px * 2
                    )

                else:
                    raise ValueError(
                        f"不支持的滑动方向：{direction}"
                    )

                cmd = self.get_adb_command(
                    "shell",
                    "input",
                    "swipe",
                    str(start_x),
                    str(start_y),
                    str(end_x),
                    str(end_y),
                    "800",
                )

                subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=5,
                )

                time.sleep(0.8)

                return True

            except Exception as e:
                print(f"滑动操作失败：{e}")
                time.sleep(0.2)

        return False

    # ============================================================
    # 地图扫描
    # ============================================================

    def scan_200x200(self, region_name, region_coords):
        """
        使用往返式扫描路径遍历地图。

        每一行扫描结束后改变横向移动方向，
        减少返回起点产生的额外移动。
        """

        if region_coords is None or not self.is_scanning:
            return

        total_rows = 22
        total_cols = 53

        physical_row = 1

        for _ in range(total_rows):
            if not self.is_scanning:
                break

            print(
                f"\n=== 正在扫描：第 {physical_row} 行 ==="
            )

            # ====================================================
            # 从右向左移动地图
            # ====================================================

            for col in range(total_cols):
                if not self.is_scanning:
                    break

                self.step_counter += 1
                current_col = col + 1

                if (
                    self.step_counter
                    % self.detect_every_n_steps
                    == 0
                ):
                    time.sleep(0.35)

                    screenshot = self.take_screenshot()

                    if screenshot is not None:
                        self.save_scan_screenshot(
                            screenshot,
                            physical_row,
                            current_col,
                            "左滑",
                        )

                if col < total_cols - 1:
                    self.fast_drag(direction="left")

            if not self.is_scanning:
                break

            # 当前行结束后向下移动
            self.fast_drag(direction="down")
            self.fast_drag(direction="down")

            time.sleep(0.15)

            screenshot = self.take_screenshot()

            if screenshot is not None:
                self.save_scan_screenshot(
                    screenshot,
                    physical_row + 1,
                    0,
                    "左滑后下滑",
                )

            # ====================================================
            # 反方向扫描
            # ====================================================

            for col in range(total_cols):
                if not self.is_scanning:
                    break

                self.step_counter += 1
                current_col = col + 1

                if (
                    self.step_counter
                    % self.detect_every_n_steps
                    == 0
                ):
                    time.sleep(0.35)

                    screenshot = self.take_screenshot()

                    if screenshot is not None:
                        self.save_scan_screenshot(
                            screenshot,
                            physical_row + 1,
                            current_col,
                            "右滑复位",
                        )

                if col < total_cols - 1:
                    self.fast_drag(direction="right")

            if not self.is_scanning:
                break

            # 第二行结束后继续向下移动
            self.fast_drag(direction="down")
            self.fast_drag(direction="down")

            time.sleep(0.15)

            screenshot = self.take_screenshot()

            if screenshot is not None:
                self.save_scan_screenshot(
                    screenshot,
                    physical_row + 2,
                    0,
                    "右滑后下滑",
                )

            physical_row += 2

    # ============================================================
    # 扫描任务控制
    # ============================================================

    def start_scanning(self):
        """启动完整地图扫描任务。"""

        if self.is_scanning:
            return

        self.is_scanning = True
        self.step_counter = 0

        self.regions["全局"] = (
            0,
            0,
            self.emulator_width,
            self.emulator_height,
        )

        print("=== 全局扫图启动 ===")

        if self.progress_callback:
            self.progress_callback(
                "开始全局 200×200 网格扫图",
                0,
            )

        region_coords = self.regions["全局"]

        print("\n=====================================")
        print("开始全局 200×200 网格扫图")
        print("=====================================")

        self.scan_200x200(
            "全局",
            region_coords,
        )

        self.is_scanning = False
        self.clean_screenshots()

        print(
            "=== 全局扫图完成，扫描结果已保存到 "
            "scan_screenshots 文件夹 ==="
        )

        messagebox.showinfo(
            "扫描完成",
            "全局扫图结束！所有截图已保存到 "
            "scan_screenshots 文件夹。",
        )

    def stop_scanning(self):
        """停止当前扫描任务。"""

        self.is_scanning = False
        self.clean_screenshots()

        print("扫图已停止，临时截图缓存已清理。")

    def clean_screenshots(self):
        """删除程序运行产生的临时截图。"""

        try:
            for filename in os.listdir(
                self.screenshot_dir
            ):
                file_path = os.path.join(
                    self.screenshot_dir,
                    filename,
                )

                if os.path.isfile(file_path):
                    os.unlink(file_path)

            print("临时截图缓存清理完成。")

        except Exception as e:
            print(f"清理截图缓存失败：{e}")


class RegionSelector:
    """GameMapScanner 图形化操作界面。"""

    def __init__(self, scanner):
        self.scanner = scanner

        self.root = tk.Tk()
        self.root.title("GameMapScanner v2.2")
        self.root.geometry("900x700")

        # Windows 中文字体
        self.root.option_add(
            "*Font",
            "SimHei 9",
        )

        self.canvas = None
        self.current_image = None
        self.photo = None

        self.scale_factor = 1.0
        self.offset_x = 0
        self.offset_y = 0

        self.scanner.progress_callback = (
            self.update_progress
        )

        self.setup_ui()

        # GUI 初始化完成后获取第一张截图
        self.root.after(
            100,
            self.load_screenshot,
        )

    # ============================================================
    # GUI
    # ============================================================

    def setup_ui(self):
        """创建主界面控件。"""

        # -------------------- ADB 设置 --------------------

        adb_frame = ttk.LabelFrame(
            self.root,
            text="ADB 设置",
        )

        adb_frame.pack(
            pady=5,
            padx=10,
            fill=tk.X,
        )

        adb_inner = ttk.Frame(adb_frame)

        adb_inner.pack(
            fill=tk.X,
            padx=5,
            pady=5,
        )

        ttk.Label(
            adb_inner,
            text="ADB路径:",
        ).pack(
            side=tk.LEFT,
            padx=5,
        )

        self.adb_path_label = ttk.Label(
            adb_inner,
            text=self.scanner.adb_path,
            foreground="blue",
            cursor="hand2",
        )

        self.adb_path_label.pack(
            side=tk.LEFT,
            padx=5,
        )

        self.adb_path_label.bind(
            "<Button-1>",
            lambda event: self.set_adb_path(),
        )

        ttk.Button(
            adb_inner,
            text="设置ADB路径",
            command=self.set_adb_path,
        ).pack(
            side=tk.LEFT,
            padx=5,
        )

        ttk.Button(
            adb_inner,
            text="测试连接",
            command=self.test_adb_connection,
        ).pack(
            side=tk.LEFT,
            padx=5,
        )

        # -------------------- 控制区 --------------------

        control_frame = ttk.Frame(self.root)

        control_frame.pack(pady=10)

        ttk.Button(
            control_frame,
            text="刷新截图",
            command=self.load_screenshot,
        ).pack(
            side=tk.LEFT,
            padx=5,
        )

        ttk.Button(
            control_frame,
            text="开始扫图",
            command=self.start_scanning,
        ).pack(
            side=tk.LEFT,
            padx=5,
        )

        ttk.Button(
            control_frame,
            text="停止扫图",
            command=self.stop_scanning,
        ).pack(
            side=tk.LEFT,
            padx=5,
        )

        ttk.Button(
            control_frame,
            text="清理临时截图",
            command=self.clean_screenshots,
        ).pack(
            side=tk.LEFT,
            padx=5,
        )

        # -------------------- 扫描进度 --------------------

        progress_frame = ttk.LabelFrame(
            self.root,
            text="扫图进度",
        )

        progress_frame.pack(
            pady=5,
            padx=10,
            fill=tk.X,
        )

        progress_inner = ttk.Frame(
            progress_frame
        )

        progress_inner.pack(
            fill=tk.X,
            padx=5,
            pady=5,
        )

        self.progress_label = ttk.Label(
            progress_inner,
            text="准备就绪",
        )

        self.progress_label.pack(
            side=tk.LEFT,
            padx=5,
        )

        self.progress_bar = ttk.Progressbar(
            progress_inner,
            orient=tk.HORIZONTAL,
            length=300,
            mode="determinate",
        )

        self.progress_bar.pack(
            side=tk.LEFT,
            padx=5,
            fill=tk.X,
            expand=True,
        )

        # -------------------- 截图显示 --------------------

        canvas_frame = ttk.Frame(self.root)

        canvas_frame.pack(
            pady=10,
            padx=10,
            fill=tk.BOTH,
            expand=True,
        )

        self.canvas = tk.Canvas(
            canvas_frame,
            bg="white",
        )

        self.canvas.pack(
            fill=tk.BOTH,
            expand=True,
        )

    def update_progress(self, text, progress):
        """更新扫描状态和进度条。"""

        self.progress_label.config(text=text)
        self.progress_bar["value"] = progress
        self.root.update_idletasks()

    def load_screenshot(self):
        """从模拟器获取并显示当前截图。"""

        self.progress_label.config(
            text="正在获取截图..."
        )

        self.root.update_idletasks()

        screenshot = self.scanner.take_screenshot()

        if screenshot is None:
            messagebox.showwarning(
                "警告",
                "无法获取截图，请检查 ADB 连接。",
            )

            self.progress_label.config(
                text="准备就绪"
            )

            return

        self.root.update_idletasks()

        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        if canvas_width <= 1:
            canvas_width = 600

        if canvas_height <= 1:
            canvas_height = 400

        image_height, image_width = (
            screenshot.shape[:2]
        )

        scale = min(
            canvas_width / image_width,
            canvas_height / image_height,
            1.0,
        )

        new_width = int(
            image_width * scale
        )

        new_height = int(
            image_height * scale
        )

        screenshot_resized = cv2.resize(
            screenshot,
            (new_width, new_height),
        )

        screenshot_rgb = cv2.cvtColor(
            screenshot_resized,
            cv2.COLOR_BGR2RGB,
        )

        self.current_image = Image.fromarray(
            screenshot_rgb
        )

        self.photo = ImageTk.PhotoImage(
            self.current_image
        )

        self.canvas.delete("all")

        self.canvas.create_image(
            canvas_width // 2,
            canvas_height // 2,
            image=self.photo,
            anchor=tk.CENTER,
        )

        # 保留引用，防止 Tkinter 回收图片
        self.canvas.image = self.photo

        self.scale_factor = scale

        self.offset_x = (
            canvas_width - new_width
        ) // 2

        self.offset_y = (
            canvas_height - new_height
        ) // 2

        self.progress_label.config(
            text="准备就绪"
        )

    # ============================================================
    # GUI 操作
    # ============================================================

    def set_adb_path(self):
        """手动选择 ADB 可执行文件。"""

        path = filedialog.askopenfilename(
            title="选择 ADB 可执行文件",
            filetypes=[
                ("可执行文件", "*.exe"),
                ("所有文件", "*.*"),
            ],
        )

        if path:
            self.scanner.adb_path = (
                os.path.normpath(path)
            )

            self.adb_path_label.config(
                text=self.scanner.adb_path
            )

            messagebox.showinfo(
                "成功",
                f"ADB 路径已设置为："
                f"{self.scanner.adb_path}",
            )

    def test_adb_connection(self):
        """测试当前 ADB 配置。"""

        self.progress_label.config(
            text="正在测试 ADB 连接..."
        )

        self.root.update_idletasks()

        if self.scanner.check_adb():
            messagebox.showinfo(
                "成功",
                "ADB 连接测试通过！",
            )

        else:
            messagebox.showerror(
                "失败",
                "ADB 连接测试失败，请检查 "
                "ADB 路径和设备连接。",
            )

        self.progress_label.config(
            text="准备就绪"
        )

    def start_scanning(self):
        """在后台线程中启动地图扫描。"""

        if self.scanner.is_scanning:
            messagebox.showinfo(
                "提示",
                "扫描任务正在运行。",
            )
            return

        self.progress_bar["value"] = 0

        scan_thread = threading.Thread(
            target=self.scanner.start_scanning,
            daemon=True,
        )

        scan_thread.start()

    def stop_scanning(self):
        """停止地图扫描。"""

        self.scanner.stop_scanning()

        messagebox.showinfo(
            "提示",
            "扫图已停止。",
        )

    def clean_screenshots(self):
        """手动清理临时截图。"""

        self.scanner.clean_screenshots()

        messagebox.showinfo(
            "成功",
            "临时截图缓存已清理。",
        )


def main():
    """程序入口。"""

    scanner = RebelScanner()
    app = RegionSelector(scanner)
    app.root.mainloop()


if __name__ == "__main__":
    main()
