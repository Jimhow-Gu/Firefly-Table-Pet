import requests
import os
import sys
import schedule
import time
import tkinter as tk
from tkinter import messagebox, Label
from PIL import *
from tkinter import messagebox
from PIL import ImageTk,Image
import ctypes
import ctypes.wintypes

def get_work_area():
    class RECT(ctypes.Structure):
        _fields_ = [
            ('left', ctypes.c_long),
            ('top', ctypes.c_long),
            ('right', ctypes.c_long),
            ('bottom', ctypes.c_long)
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ('cbSize', ctypes.wintypes.DWORD),
            ('rcMonitor', RECT),
            ('rcWork', RECT),
            ('dwFlags', ctypes.wintypes.DWORD)
        ]

    monitor_info = MONITORINFO()
    monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
    ctypes.windll.user32.GetMonitorInfoW(
        ctypes.windll.user32.MonitorFromWindow(0, 2),  # MONITOR_DEFAULTTOPRIMARY
        ctypes.byref(monitor_info)
    )
    return monitor_info.rcWork.right, monitor_info.rcWork.bottom

def get_public_ip():
    try:
        response = requests.get('https://api64.ipify.org?format=json')
        if response.status_code == 200:
            return response.json()['ip']
    except requests.RequestException:
        return None


def check_ip_for_proxy(ip):
    try:
        response = requests.get(f'http://ip-api.com/json/{ip}?fields=proxy')
        if response.status_code == 200:
            data = response.json()
            return data.get('proxy', False)
    except requests.RequestException:
        return False


def disconnect_internet():
    # 断开连接操作（根据实际情况实现）
    if os.name == 'nt':  # Windows
        os.system('netsh interface set interface "Wi-Fi" admin=disable')
    elif os.name == 'posix':  # Linux/MacOS
        os.system('sudo ifconfig eth0 down')
    else:
        print("Unsupported OS")
        sys.exit(1)


# 获取屏幕的宽度和高度
def get_screen_size(root):
    return root.winfo_screenwidth(), root.winfo_screenheight()



# 修改后的窗口定位函数
def center_window(root, width, height):
    work_right, work_bottom = get_work_area()
    x = work_right - width  # 右侧保留10像素边距
    y = work_bottom - height  # 底部保留10像素边距
    root.geometry(f'{width}x{height}+{x}+{y}')

# 创建弹窗函数
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




def check_and_disconnect():
    public_ip = get_public_ip()
    if public_ip:
        is_proxy = check_ip_for_proxy(public_ip)
        if is_proxy:
            print("Detected proxy or VPN. Disconnecting...")
            disconnect_internet()
            sys.exit(1)
        else:
            print("No proxy or VPN detected. Connection remains active.")

    else:
        print("Unable to retrieve public IP.")


def main():
    # 每隔5分钟执行一次检测任务
    schedule.every(5).minutes.do(check_and_disconnect)

    # 保持脚本运行
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    show_notification("流萤桌宠插件 \n已经启动")
    main()