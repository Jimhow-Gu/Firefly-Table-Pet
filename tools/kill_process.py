# -*- coding: utf-8 -*-
import psutil
import time
import tkinter as tk
from tkinter import messagebox, Label
from PIL import ImageTk,Image

from tools.end import center_window


def kill_process_and_children(process_name_list):
    killed_pids = set()  # 记录已终止的PID避免重复操作

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            # 检查进程是否在目标列表中
            if proc.info['name'] in process_name_list:
                parent = psutil.Process(proc.info['pid'])
                children = parent.children(recursive=True)  # 获取所有子进程

                # 先终止子进程
                for child in children:
                    if child.pid not in killed_pids:
                        child.terminate()
                        killed_pids.add(child.pid)
                        print(f"终止子进程: {child.name()} (PID: {child.pid})")

                # 再终止父进程
                if proc.info['pid'] not in killed_pids:
                    proc.terminate()
                    killed_pids.add(proc.info['pid'])
                    print(f"终止主进程: {proc.info['name']} (PID: {proc.info['pid']})")



        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # 强制清理残留进程（如果terminate失败）
    time.sleep(1)
    for pid in killed_pids:
        try:
            p = psutil.Process(pid)
            if p.is_running():
                p.kill()
                print(f"强制终止残留进程: {p.name()} (PID: {pid})")
        except:
            pass

def show_notification(message):
    popup = tk.Tk()
    popup.title("插件")
    popup.wm_attributes("-topmost", True)
    popup_width = 300
    popup_height = 100
    popup.overrideredirect(True)
    center_window(popup, popup_width, popup_height)
    label = Label(popup, text=message, font=('Arial', 14), padx=20, pady=20)
    label.pack()
    label.place(x=90, y=0)
    image = Image.open("bg.png")
    image = image.resize((67, 86), Image.Resampling.LANCZOS)  # 调整图片大小
    photo = ImageTk.PhotoImage(image)

    # 创建一个Label组件来显示图片
    img_label = Label(popup, image=photo)
    img_label.image = photo  # 保持对图像的引用，防止被垃圾回收
    img_label.pack(side=tk.LEFT, padx=10, pady=10)
    # 延迟3秒后关闭窗口
    popup.after(5000, popup.destroy)

    popup.mainloop()


if __name__ == "__main__":
    show_notification(" 插件已关闭 \n感谢你的使用！")
    # 需要终止的进程列表（根据实际情况修改）
    target_processes = [
        "流萤桌宠.exe",
        "工具组件.exe",  # 子进程1
        "AI.exe",  # 子进程2
        "插件.exe",  # 子进程3
        "关闭程序.exe",
        "工具组件.exe"# 子进程4
    ]

    print("正在终止进程及释放资源...")
    kill_process_and_children(target_processes)
    print("操作完成。")

    # 可选：清理临时文件（根据实际情况添加路径）
    # temp_files = ["./normal", "./Large", "medium"]
    # for file in temp_files:
    #     if os.path.exists(file):
    #         os.remove(file)
    #         print(f"已清理临时文件: {file}")