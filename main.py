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

# 修复中文路径乱码
sys.stdout.reconfigure(encoding='utf-8')
os.environ['PYTHONIOENCODING'] = 'utf-8'


class RebelScanner:
    def __init__(self, adb_path=None):
        self.regions = {}  # 清空区域配置
        # 核心配置（固定，无需修改）
        self.game_grid_total = (200, 200)  # 单区域200列×200行游戏格
        self.screen_grid_show = (4, 9)  # 屏幕可视4行×9列游戏格
        self.grid_pixel_w = 138  # 单个游戏格宽（你的实测值）
        self.grid_pixel_h = 90  # 单个游戏格高（你的实测值）
        self.overlap = (1, 1)  # 滑动重叠1行1列，避免漏扫
        # 计算屏幕可视区总像素/滑动步长（自动计算）
        self.screen_total_w = self.screen_grid_show[1] * self.grid_pixel_w
        self.screen_total_h = self.screen_grid_show[0] * self.grid_pixel_h
        self.slide_step_x = (4 - self.overlap[1]) * self.grid_pixel_w  # 4列替代原9列计算
        self.slide_step_y = (self.screen_grid_show[0] - self.overlap[0]) * self.grid_pixel_h
        # 计算总滑动屏数（自动计算）
        self.total_slide_x = (self.game_grid_total[0] - self.overlap[1]) // (self.screen_grid_show[1] - self.overlap[1])
        self.total_slide_y = (self.game_grid_total[1] - self.overlap[0]) // (self.screen_grid_show[0] - self.overlap[0])

        self.is_scanning = False
        self.screenshot_dir = "screenshots"
        os.makedirs(self.screenshot_dir, exist_ok=True)
        self.adb_path = adb_path or self.find_adb_path()
        # 关键：你的模拟器实际分辨率（563×1031）
        self.emulator_width = 563
        self.emulator_height = 1031
        # 滑屏基准坐标（模拟器屏幕中心，适配563×1031）
        self.base_x = self.emulator_width // 2  # 281
        self.base_y = self.emulator_height // 2  # 515
        # 固定滑动步长（删除了可配置功能，使用固定值）
        self.slide_step_x_px = 662  # 原828对应5格，662对应4格
        self.slide_step_y_px = self.slide_step_y  # Y轴像素步长（固定180）
        # 扫描进度回调
        self.progress_callback = None
        # 步数控制（仅用于截图频率）
        self.detect_every_n_steps = 1  # 每走1步截图一次
        self.step_counter = 0  # 步数计数器
        self.scan_screenshot_dir = "scan_screenshots"  # 扫图专用保存目录
        os.makedirs(self.scan_screenshot_dir, exist_ok=True)

    # ===================== ADB/截图基础功能 =====================
    def find_adb_path(self):
        adb_in_path = shutil.which('adb')
        if adb_in_path:
            return os.path.normpath(adb_in_path)
        common_paths = [
            r"C:\Program Files\BlueStacks\HD-Adb.exe", r"C:\Program Files (x86)\BlueStacks\HD-Adb.exe",
            r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe", r"C:\Program Files (x86)\BlueStacks_nxt\HD-Adb.exe",
            r"C:\LDPlayer\LDPlayer9\adb.exe", r"C:\Program Files (x86)\Nox\bin\nox_adb.exe",
            os.path.expanduser(r"~\AppData\Local\Android\Sdk\platform-tools\adb.exe"),
        ]
        for path in common_paths:
            if os.path.exists(os.path.normpath(path)):
                return os.path.normpath(path)
        print("警告: 未找到 ADB，使用系统PATH中的adb")
        return 'adb'

    def get_adb_command(self, *args):
        adb_path = os.path.normpath(self.adb_path) if os.path.exists(self.adb_path) else self.adb_path
        return [adb_path] + list(args)

    def check_adb(self):
        try:
            subprocess.run(self.get_adb_command('start-server'), capture_output=True, timeout=3)
            result = subprocess.run(self.get_adb_command('version'), capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except Exception as e:
            print(f"ADB检查失败: {e}")
            return False

    def take_screenshot(self):
        """修复截图：替换为兼容所有模拟器的截图方式"""
        try:
            # 第一步：先把截图保存到模拟器内部
            temp_path = "/sdcard/screenshot_temp.png"
            cmd_save = self.get_adb_command('shell', 'screencap', '-p', temp_path)
            subprocess.run(cmd_save, capture_output=True, timeout=5, check=True)

            # 第二步：把截图从模拟器拉到本地
            local_path = os.path.join(self.screenshot_dir, "temp_screenshot.png")
            cmd_pull = self.get_adb_command('pull', temp_path, local_path)
            subprocess.run(cmd_pull, capture_output=True, timeout=5, check=True)

            # 第三步：读取本地截图（支持中文路径）
            pil_image = Image.open(local_path).convert('RGB')
            img = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

            # 第四步：删除临时文件
            subprocess.run(self.get_adb_command('shell', 'rm', temp_path), capture_output=True, timeout=2)
            return img
        except Exception as e:
            print(f"截图失败: {e}")
            return None

    def save_scan_screenshot(self, image, physical_row, col, step_type):
        """
        严格按：行1_列1_左滑.png 命名
        """
        try:
            filename = f"行{physical_row}_列{col}_{step_type}.png"
            save_path = os.path.join(self.scan_screenshot_dir, filename)
            # 覆盖保存（不重复）
            cv2.imencode('.png', image)[1].tofile(save_path)
        except Exception as e:
            print(f"❌ 保存失败: {e}")

    # ===================== 滑屏逻辑 =====================
    def fast_drag(self, direction='left', retry=2):
        for _ in range(retry + 1):
            try:
                start_x, start_y = self.base_x, self.base_y
                end_x, end_y = start_x, start_y

                if direction == 'left':
                    end_x = start_x - self.slide_step_x_px
                elif direction == 'right':
                    end_x = start_x + self.slide_step_x_px
                elif direction == 'down':
                    end_y = start_y - self.slide_step_y_px * 2

                cmd = self.get_adb_command(
                    'shell', 'input', 'swipe',
                    str(start_x), str(start_y),
                    str(end_x), str(end_y),
                    '800'
                )
                subprocess.run(cmd, capture_output=True, timeout=5)
                time.sleep(0.8)
                return True
            except Exception:
                time.sleep(0.2)
        return False

    # ===================== 核心扫图逻辑（仅滑屏+截图，无模板匹配） =====================
    def scan_200x200(self, region_name, region_coords):
        if region_coords is None or not self.is_scanning:
            return

        x, y, w, h = region_coords
        total_rows = 22
        total_cols = 53
        physical_row = 1  # 真实行号

        for cycle_row in range(total_rows):
            if not self.is_scanning:
                break

            print(f"\n=== 正在扫描：第 {physical_row} 行 ===")

            # ====================== 左滑 ======================
            for col in range(total_cols):
                if not self.is_scanning:
                    break
                self.step_counter += 1
                current_col = col + 1

                if self.step_counter % self.detect_every_n_steps == 0:
                    time.sleep(0.35)
                    screenshot = self.take_screenshot()
                    if screenshot is not None:
                        # 命名：行1_列1_左滑.png
                        self.save_scan_screenshot(screenshot, physical_row, current_col, "左滑")

                if col < total_cols - 1:
                    self.fast_drag(direction='left')

            # 左滑 → 下滑
            self.fast_drag(direction='down')
            self.fast_drag(direction='down')
            time.sleep(0.15)
            screenshot = self.take_screenshot()
            if screenshot is not None:
                self.save_scan_screenshot(screenshot, physical_row + 1, 0, "左滑后下滑")

            # ====================== 右滑复位 ======================
            for col in range(total_cols):
                if not self.is_scanning:
                    break
                self.step_counter += 1
                current_col = col + 1

                if self.step_counter % self.detect_every_n_steps == 0:
                    time.sleep(0.35)
                    screenshot = self.take_screenshot()
                    if screenshot is not None:
                        self.save_scan_screenshot(screenshot, physical_row + 1, current_col, "右滑复位")

                if col < total_cols - 1:
                    self.fast_drag(direction='right')

            # 右滑 → 下滑
            self.fast_drag(direction='down')
            self.fast_drag(direction='down')
            time.sleep(0.15)
            screenshot = self.take_screenshot()
            if screenshot is not None:
                self.save_scan_screenshot(screenshot, physical_row + 2, 0, "右滑后下滑")

            # 行号 +2，完全匹配你的视觉：行1 → 行2 → 行3 → 行4…
            physical_row += 2

    # ===================== 扫描主逻辑（全局扫图） =====================
    def start_scanning(self):
        self.is_scanning = True

        # 直接扫描全局200×200区域
        scanned_regions = ["全局"]
        self.regions["全局"] = (0, 0, self.emulator_width, self.emulator_height)

        print(f"=== 全局扫图启动，开始扫描全局区域 ===")

        if self.progress_callback:
            self.progress_callback("开始全局200×200网格扫图", 0)

        region_coords = self.regions["全局"]
        print(f"\n=====================================")
        print(f"开始全局200×200网格扫图")
        print(f"=====================================")

        # 执行全局扫图（仅滑屏+截图）
        self.scan_200x200("全局", region_coords)

        # 扫描结束处理
        self.is_scanning = False
        self.clean_screenshots()

        print("=== 全局扫图完成，所有截图已保存到 scan_screenshots 文件夹 ===")
        messagebox.showinfo("扫描完成", "全局扫图结束！所有截图已保存到 scan_screenshots 文件夹")

    def stop_scanning(self):
        self.is_scanning = False
        self.clean_screenshots()
        print("扫图已停止，已清理临时截图缓存")

    def clean_screenshots(self):
        """清理临时截图缓存"""
        try:
            for filename in os.listdir(self.screenshot_dir):
                file_path = os.path.join(self.screenshot_dir, filename)
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            print("临时截图缓存清理完成")
        except Exception as e:
            print(f"清理截图缓存失败: {e}")


# ===================== UI代码（已删除阈值设置区和模板管理区） =====================
class RegionSelector:
    def __init__(self, scanner):
        self.scanner = scanner
        self.root = tk.Tk()
        self.root.title("游戏区域扫图工具 v2.2（仅扫图）")
        self.root.geometry("900x700")
        # 修复中文显示
        self.root.option_add('*Font', 'SimHei 9')
        self.canvas = None
        self.current_image = None
        # 绑定进度回调
        self.scanner.progress_callback = self.update_progress
        self.setup_ui()
        self.root.after(100, self.load_screenshot)

    def setup_ui(self):
        # ========== ADB设置区 ==========
        adb_frame = ttk.LabelFrame(self.root, text="ADB 设置")
        adb_frame.pack(pady=5, padx=10, fill=tk.X)
        adb_inner = ttk.Frame(adb_frame)
        adb_inner.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(adb_inner, text="ADB路径:").pack(side=tk.LEFT, padx=5)
        self.adb_path_label = ttk.Label(adb_inner, text=self.scanner.adb_path, foreground="blue", cursor="hand2")
        self.adb_path_label.pack(side=tk.LEFT, padx=5)
        self.adb_path_label.bind("<Button-1>", lambda e: self.set_adb_path())
        ttk.Button(adb_inner, text="设置ADB路径", command=self.set_adb_path).pack(side=tk.LEFT, padx=5)
        ttk.Button(adb_inner, text="测试连接", command=self.test_adb_connection).pack(side=tk.LEFT, padx=5)

        # ========== 控制区 ==========
        control_frame = ttk.Frame(self.root)
        control_frame.pack(pady=10)
        ttk.Button(control_frame, text="刷新截图", command=self.load_screenshot).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="开始扫图", command=self.start_scanning).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="停止扫图", command=self.stop_scanning).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="清理临时截图", command=self.clean_screenshots).pack(side=tk.LEFT, padx=5)

        # ========== 扫描进度区 ==========
        progress_frame = ttk.LabelFrame(self.root, text="扫图进度")
        progress_frame.pack(pady=5, padx=10, fill=tk.X)
        progress_inner = ttk.Frame(progress_frame)
        progress_inner.pack(fill=tk.X, padx=5, pady=5)
        self.progress_label = ttk.Label(progress_inner, text="准备就绪")
        self.progress_label.pack(side=tk.LEFT, padx=5)
        self.progress_bar = ttk.Progressbar(progress_inner, orient=tk.HORIZONTAL, length=300, mode='determinate')
        self.progress_bar.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # ========== 截图显示区 ==========
        canvas_frame = ttk.Frame(self.root)
        canvas_frame.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(canvas_frame, bg="white")
        self.canvas.pack(fill=tk.BOTH, expand=True)

    def update_progress(self, text, progress):
        """更新扫图进度"""
        self.progress_label.config(text=text)
        self.progress_bar['value'] = progress
        self.root.update_idletasks()

    def load_screenshot(self):
        """加载截图"""
        self.progress_label.config(text="正在获取截图...")
        self.root.update_idletasks()

        screenshot = self.scanner.take_screenshot()
        if screenshot is None:
            messagebox.showwarning("警告", "无法获取截图，请检查ADB连接")
            self.progress_label.config(text="准备就绪")
            return

        self.root.update_idletasks()
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        cw, ch = cw if cw > 1 else 600, ch if ch > 1 else 400
        h, w = screenshot.shape[:2]
        scale = min(cw / w, ch / h, 1.0)
        new_w, new_h = int(w * scale), int(h * scale)
        screenshot_resized = cv2.resize(screenshot, (new_w, new_h))
        screenshot_rgb = cv2.cvtColor(screenshot_resized, cv2.COLOR_BGR2RGB)
        self.current_image = Image.fromarray(screenshot_rgb)
        self.photo = ImageTk.PhotoImage(self.current_image)
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=self.photo, anchor=tk.CENTER)
        self.canvas.image = self.photo
        self.scale_factor = scale
        self.offset_x = (cw - new_w) // 2
        self.offset_y = (ch - new_h) // 2

        self.progress_label.config(text="准备就绪")

    # 以下模板相关方法仅保留空实现，避免报错（未删除，防止调用时报错）
    def add_template(self):
        pass

    def view_templates(self):
        pass

    def remove_template_ui(self):
        pass

    def set_adb_path(self):
        """设置ADB路径"""
        path = filedialog.askopenfilename(
            title="选择ADB可执行文件",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")]
        )
        if path:
            self.scanner.adb_path = os.path.normpath(path)
            self.adb_path_label.config(text=self.scanner.adb_path)
            messagebox.showinfo("成功", f"ADB路径已设置为：{self.scanner.adb_path}")

    def test_adb_connection(self):
        """测试ADB连接"""
        self.progress_label.config(text="正在测试ADB连接...")
        self.root.update_idletasks()

        if self.scanner.check_adb():
            messagebox.showinfo("成功", "ADB连接测试通过！")
            self.progress_label.config(text="准备就绪")
        else:
            messagebox.showerror("失败", "ADB连接测试失败，请检查ADB路径和设备连接")
            self.progress_label.config(text="准备就绪")

    def start_scanning(self):
        """开始扫图（线程执行）"""
        # 重置进度
        self.progress_bar['value'] = 0
        # 启动线程执行扫图，避免UI卡死
        scan_thread = threading.Thread(target=self.scanner.start_scanning)
        scan_thread.daemon = True
        scan_thread.start()

    def stop_scanning(self):
        """停止扫图"""
        self.scanner.stop_scanning()
        messagebox.showinfo("提示", "扫图已停止")

    def clean_screenshots(self):
        """清理临时截图缓存"""
        self.scanner.clean_screenshots()
        messagebox.showinfo("成功", "临时截图缓存已清理")


# 程序入口
if __name__ == "__main__":
    scanner = RebelScanner()
    app = RegionSelector(scanner)
    app.root.mainloop()