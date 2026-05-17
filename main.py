# -*- coding: utf-8 -*-
import os
import shutil
import subprocess
import sys
import psutil
import pygame
import webbrowser
import json
import re
import random
import uuid
from datetime import datetime, timedelta
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
import time
from lunardate import LunarDate

def set_window_emoji_icon(window, emoji: str, size: int = 24):
    """将窗口图标替换为 emoji 字符"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    font = QFont("Segoe UI Emoji", size - 4)  # Windows 专用 emoji 字体，其他系统会自动 fallback
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, emoji)
    painter.end()
    window.setWindowIcon(QIcon(pixmap))

pluginsPath = 'plugins'
if os.path.exists(pluginsPath):
    QApplication.addLibraryPath(pluginsPath)

# ====================== 用户数据配置 ======================
USER_DATA_DIR = "user_data"
USER_CONFIG = "user_login.json"
if not os.path.exists(USER_DATA_DIR):
    os.makedirs(USER_DATA_DIR)

CODES_FILE = os.path.join(USER_DATA_DIR, "redeem_codes.json")

# ====================== 时装定义 ======================
AVAILABLE_CLOTHES = {
    "normal": {
        "name": "普通时装",
        "source_dir": "clothes/normal/assets",
        "description": "默认服装"
    },
    "26_Newyear": {
        "name": "柿柿如意",
        "source_dir": "clothes/new_year/assets",
        "description": "2026 春节签到获得"
    }
}

# ====================== 统一菜单样式 ======================
MENU_STYLE = """
    QMenu{
        border: 1px solid #dbdbdb;
        background-color: #ffffff;
        padding: 4px;
        border-radius: 6px;
    }
    QMenu::item{
        padding: 6px 20px;
        margin: 2px 4px;
        border-radius: 4px;
    }
    QMenu::item:selected{
        background-color: LightSkyBlue;
        color: #1E90FF;
    }
    QMenu::separator{
        height: 1px;
        background-color: #e9ecef;
        margin: 4px 0px;
    }
"""


def ensure_user_fields(user_data, filepath=None):
    modified = False
    defaults = {
        "balance": 20,
        "credit": 99999 if user_data.get("uid", "").lower().startswith("trailblazer") else 0,
        "last_sign_date": None,
        "banned": False,
        "banned_until": None,
        "redeemed_codes": [],
        "redeem_history": [],
        "cursor_style": "None",
        "pet_size": "normal",
        "owned_clothes": ["normal"],
        "last_state": "Standby",
        "mailbox": [],
        "last_x": None,
        "last_y": None,
        "star_rail_tickets": 0,               # 新增：星铁专票
        "last_birthday_greet_year": None      # 新增：上次生日祝福年份
    }
    for key, default_val in defaults.items():
        if key not in user_data:
            user_data[key] = default_val
            modified = True
    if not isinstance(user_data.get("owned_clothes"), list):
        user_data["owned_clothes"] = ["normal"]
        modified = True
    if not isinstance(user_data.get("mailbox"), list):
        user_data["mailbox"] = []
        modified = True
    if modified and filepath:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
    return user_data


def load_all_codes():
    if not os.path.exists(CODES_FILE):
        default_codes = {
            "Firefly": {
                "reward": 10,
                "max_uses": 1,
                "used_count": 0,
                "created_by": "system",
                "created_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "target_user": None,
                "item_type": "cake",
                "expire_time": None,
                "revoked": False,
                "revoked_users": [],
                "revoked_by": None,
                "revoked_time": None,
                "clothes_id": None
            }
        }
        with open(CODES_FILE, "w", encoding="utf-8") as f:
            json.dump(default_codes, f, indent=2)
        return default_codes
    with open(CODES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        for code, info in data.items():
            # 向后兼容：如果没有 items 字段，从旧字段生成
            if "items" not in info:
                itype = info.get("item_type", "cake")
                reward = info.get("reward", 0)
                cid = info.get("clothes_id")
                if itype == "cake":
                    info["items"] = [{"type": "cake", "amount": reward}]
                elif itype == "clothes":
                    info["items"] = [{"type": "clothes", "id": cid}]
                elif itype == "credit":
                    info["items"] = [{"type": "credit", "amount": reward}]
            # 确保其他默认字段
            info.setdefault("expire_time", None)
            info.setdefault("revoked", False)
            info.setdefault("revoked_users", [])
            info.setdefault("revoked_by", None)
            info.setdefault("revoked_time", None)
        return data


def save_all_codes(codes):
    with open(CODES_FILE, "w", encoding="utf-8") as f:
        json.dump(codes, f, indent=2)


def parse_duration(duration_str):
    pattern = re.compile(r'(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?')
    match = pattern.match(duration_str.upper())
    if not match:
        return None
    years = int(match.group(1)) if match.group(1) else 0
    months = int(match.group(2)) if match.group(2) else 0
    days = int(match.group(3)) if match.group(3) else 0
    total_days = years * 365 + months * 30 + days
    return timedelta(days=total_days)


def parse_expire_time(expire_str):
    if not expire_str:
        return None
    try:
        dt = datetime.strptime(expire_str, "%Y-%m-%d")
        return dt.isoformat()
    except:
        pass
    delta = parse_duration(expire_str)
    if delta is not None:
        expire_dt = datetime.now() + delta
        return expire_dt.isoformat()
    return None


# ====================== 邮箱核心函数 ======================
def clean_expired_mails(user_data):
    """删除超过6个月的邮件"""
    if "mailbox" not in user_data:
        return
    cutoff = datetime.now() - timedelta(days=180)
    new_mailbox = []
    for mail in user_data["mailbox"]:
        try:
            mail_time = datetime.fromisoformat(mail["timestamp"])
            if mail_time >= cutoff:
                new_mailbox.append(mail)
        except:
            new_mailbox.append(mail)
    user_data["mailbox"] = new_mailbox


def send_mail(user_data, title, content, items):
    """向用户邮箱中添加一封邮件，并返回邮件对象"""
    ensure_user_fields(user_data)
    clean_expired_mails(user_data)
    mail = {
        "id": str(uuid.uuid4()),
        "title": title,
        "content": content,
        "sender": "系统",
        "timestamp": datetime.now().isoformat(),
        "read": False,
        "claimed": False,
        "items": items  # list of {"type": "cake"/"credit"/"clothes"/"star_rail_ticket", "amount"/"id": ...}
    }
    user_data["mailbox"].append(mail)
    return mail


def claim_mail_items(user_data, mail):
    """领取单封邮件的物品，返回 (是否成功, 物品描述列表)"""
    if mail["claimed"]:
        return False, []
    items_desc = []
    for item in mail["items"]:
        itype = item["type"]
        if itype == "cake":
            user_data["balance"] = user_data.get("balance", 0) + item["amount"]
            items_desc.append(f"橡木蛋糕卷 x{item['amount']}")
        elif itype == "credit":
            user_data["credit"] = user_data.get("credit", 0) + item["amount"]
            if user_data["credit"] > 99999999:
                user_data["credit"] = 99999999
            items_desc.append(f"信用点 x{item['amount']}")
        elif itype == "clothes":
            clothes_id = item["id"]
            if clothes_id in AVAILABLE_CLOTHES:
                owned = user_data.get("owned_clothes", ["normal"])
                if clothes_id not in owned:
                    owned.append(clothes_id)
                    user_data["owned_clothes"] = owned
                    items_desc.append(f"时装 [{AVAILABLE_CLOTHES[clothes_id]['name']}]")
        elif itype == "star_rail_ticket":
            user_data["star_rail_tickets"] = user_data.get("star_rail_tickets", 0) + item["amount"]
            items_desc.append(f"星铁专票 x{item['amount']}")
    mail["claimed"] = True
    # 记录到兑换明细
    history = user_data.get("redeem_history", [])
    history.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 邮件领取: {', '.join(items_desc) if items_desc else '空邮件'}")
    user_data["redeem_history"] = history
    return True, items_desc


# ====================== 邮箱窗口 ======================
class MailboxWindow(QDialog):
    def __init__(self, firefly, parent=None):
        super().__init__(parent)
        set_window_emoji_icon(self, "📬")
        self.firefly = firefly
        self.user_data = firefly.current_user
        self.setWindowTitle("邮箱")
        self.setFixedSize(820, 550)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setStyleSheet("""
            QDialog { background-color: #1E1E1E; border-radius: 10px; }
            QLabel { color: #888888; font-size: 14px; }
            QListWidget { background-color: #2D2D2D; border: 1px solid #555555; border-radius: 8px; color: #CCCCCC; font-size: 13px; padding: 5px; }
            QPushButton { background-color: #4CAF50; color: white; border: none; border-radius: 8px; padding: 8px 16px; font-size: 14px; }
            QPushButton:hover { background-color: #45A049; }
            QPushButton:disabled { background-color: #666666; }
        """)
        self.init_ui()
        self.load_mails()
        self.apply_rounded_mask()
        if self.mail_list.count() > 0:
            self.mail_list.setCurrentRow(0)
            self.show_detail_for_current()

        screen_center = QApplication.primaryScreen().availableGeometry().center()
        self.move(screen_center - self.rect().center())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_pos)
            event.accept()

    def create_rounded_mask(self):
        """生成圆角矩形遮罩区域"""
        radius = 15  # 圆角半径（像素）
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), radius, radius)
        # 转换为 QRegion
        return QRegion(path.toFillPolygon().toPolygon())

    def apply_rounded_mask(self):
        """将当前窗口裁剪为圆角"""
        self.setMask(self.create_rounded_mask())

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(10)

        title = QLabel("📬 邮箱")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:18px; font-weight:bold; color:#FFFFFF;")
        main_layout.addWidget(title)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(10)

        self.mail_list = QListWidget()
        self.mail_list.itemClicked.connect(self.on_mail_clicked)
        content_layout.addWidget(self.mail_list, 2)

        right_frame = QFrame()
        right_frame.setStyleSheet("""
            QFrame {
                background-color: #2D2D2D;
                border: 1px solid #555555;
                border-radius: 8px;
            }
            QTextEdit {
                background-color: #2D2D2D;
                border: none;
                color: #CCCCCC;
                font-size: 13px;
                padding: 10px;
            }
        """)
        right_layout_inner = QVBoxLayout(right_frame)
        right_layout_inner.setContentsMargins(0, 0, 0, 0)
        right_layout_inner.setSpacing(0)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        right_layout_inner.addWidget(self.detail_text)

        # 星铁专票专属标签（带悬浮提示）
        self.ticket_label = QLabel()
        self.ticket_label.setStyleSheet("color: #FFD700; font-size: 14px; margin: 8px;")
        self.ticket_label.setToolTip("来自列车的祝福")
        self.ticket_label.hide()
        right_layout_inner.addWidget(self.ticket_label)

        self.claim_btn = QPushButton("领取")
        self.claim_btn.setObjectName("claim_btn")
        self.claim_btn.setStyleSheet("""
            QPushButton#claim_btn {
                background-color: #FF9800;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 14px;
                margin: 8px;
            }
            QPushButton#claim_btn:hover {
                background-color: #F57C00;
            }
            QPushButton#claim_btn:disabled {
                background-color: #666666;
            }
        """)
        self.claim_btn.clicked.connect(self.claim_current_mail)
        self.claim_btn.setEnabled(False)
        right_layout_inner.addWidget(self.claim_btn, alignment=Qt.AlignRight)

        content_layout.addWidget(right_frame, 3)
        main_layout.addLayout(content_layout)

        btn_layout = QHBoxLayout()
        self.claim_all_btn = QPushButton("一键领取")
        self.claim_all_btn.clicked.connect(self.claim_all)
        self.read_all_btn = QPushButton("全部已读")
        self.read_all_btn.clicked.connect(self.read_all)
        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.claim_all_btn)
        btn_layout.addWidget(self.read_all_btn)
        btn_layout.addWidget(self.close_btn)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)

    def load_mails(self):
        clean_expired_mails(self.user_data)
        self.firefly._save_current_user()
        self.mail_list.blockSignals(True)
        self.mail_list.clear()
        mails = self.user_data.get("mailbox", [])
        for i, mail in enumerate(reversed(mails)):
            title = mail["title"]
            if not mail["read"]:
                title = "● " + title
            if mail["claimed"]:
                title += " [已领取]"
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, i)
            self.mail_list.addItem(item)
        self.mail_list.blockSignals(False)

    def get_mail_by_item(self, item):
        if item is None:
            return None
        index = item.data(Qt.UserRole)
        mails = self.user_data.get("mailbox", [])
        if index is None or index < 0 or index >= len(mails):
            return None
        real_index = len(mails) - 1 - index
        if real_index < 0 or real_index >= len(mails):
            return None
        return mails[real_index]

    def on_mail_clicked(self, item):
        self.show_detail_for_item(item)

    def show_detail_for_current(self):
        item = self.mail_list.currentItem()
        self.show_detail_for_item(item)

    def show_detail_for_item(self, item):
        mail = self.get_mail_by_item(item)
        if mail is None:
            self.detail_text.clear()
            self.ticket_label.hide()
            self.claim_btn.setEnabled(False)
            return

        if not mail["read"]:
            mail["read"] = True
            self.firefly._save_current_user()
            title = mail["title"]
            if mail["claimed"]:
                title += " [已领取]"
            self.mail_list.blockSignals(True)
            item.setText(title)
            self.mail_list.blockSignals(False)

        items_str = []
        has_ticket = False
        for it in mail["items"]:
            if it["type"] == "cake":
                items_str.append(f"橡木蛋糕卷 x{it['amount']}")
            elif it["type"] == "credit":
                items_str.append(f"信用点 x{it['amount']}")
            elif it["type"] == "clothes":
                clothes_info = AVAILABLE_CLOTHES.get(it["id"], {})
                items_str.append(f"时装 [{clothes_info.get('name', it['id'])}]")
            elif it["type"] == "star_rail_ticket":
                has_ticket = True
                # 票务信息单独在 ticket_label 显示，这里也加一行以便文本查看
                items_str.append(f"星铁专票 x{it['amount']}")

        items_text = ', '.join(items_str) if items_str else "无"

        status = "已领取" if mail["claimed"] else "未领取"
        detail = (
            f"发件人：{mail['sender']}\n"
            f"时间：{mail['timestamp'][:19]}\n"
            f"状态：{status}\n"
            f"标题：{mail['title']}\n"
            f"──────────────────\n"
            f"{mail['content']}\n"
            f"──────────────────\n"
            f"物品：{items_text}"
        )
        self.detail_text.setPlainText(detail)

        # 控制星铁专票悬浮标签
        if has_ticket:
            self.ticket_label.setText("星铁专票 x1")
            self.ticket_label.show()
        else:
            self.ticket_label.hide()

        self.claim_btn.setEnabled(not mail["claimed"])

    def claim_current_mail(self):
        item = self.mail_list.currentItem()
        mail = self.get_mail_by_item(item)
        if mail is None or mail["claimed"]:
            return

        success, desc = claim_mail_items(self.user_data, mail)
        if success:
            self.firefly._save_current_user()
            self.firefly.update_bag_display()
            title = mail["title"] + " [已领取]"
            self.mail_list.blockSignals(True)
            item.setText(title)
            self.mail_list.blockSignals(False)
            self.show_detail_for_item(item)
            QMessageBox.information(self, "成功", f"物品已领取！获得 {', '.join(desc)}")

    def claim_all(self):
        mails = self.user_data.get("mailbox", [])
        total_desc = []
        for mail in mails:
            if not mail["claimed"]:
                success, desc = claim_mail_items(self.user_data, mail)
                if success:
                    total_desc.extend(desc)
        self.firefly._save_current_user()
        self.firefly.update_bag_display()
        old_row = self.mail_list.currentRow()
        self.load_mails()
        if old_row >= 0 and old_row < self.mail_list.count():
            self.mail_list.setCurrentRow(old_row)
        elif self.mail_list.count() > 0:
            self.mail_list.setCurrentRow(0)
        self.show_detail_for_current()
        if total_desc:
            QMessageBox.information(self, "提示", f"已领取所有未领取邮件，获得：{', '.join(total_desc)}")
        else:
            QMessageBox.information(self, "提示", "没有可领取的邮件")

    def read_all(self):
        mails = self.user_data.get("mailbox", [])
        for mail in mails:
            mail["read"] = True
        self.firefly._save_current_user()
        old_row = self.mail_list.currentRow()
        self.load_mails()
        if old_row >= 0 and old_row < self.mail_list.count():
            self.mail_list.setCurrentRow(old_row)
        elif self.mail_list.count() > 0:
            self.mail_list.setCurrentRow(0)
        self.show_detail_for_current()

    def closeEvent(self, event):
        if self.current_user:
            self.current_user["last_state"] = self.persistent_state
            pos = self.pos()
            self.current_user["last_x"] = pos.x()
            self.current_user["last_y"] = pos.y()
            self._save_current_user()
        self.settings.setValue("geometry", self.saveGeometry())
        event.accept()


# ====================== 兑换码输入对话框 ======================
class RedeemCodeDialog(QDialog):
    code_submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        set_window_emoji_icon(self, "🎟️")
        self.setWindowTitle("使用兑换码")
        self.setFixedSize(350, 150)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)
        self.setStyleSheet("""
            QDialog { background-color: #1E1E1E; border-radius: 10px; }
            QLabel { color: #888888; font-size: 14px; }
            QLineEdit {
                border: 1px solid #555555; border-radius: 8px; padding: 8px;
                background-color: #2D2D2D; color: #888888; font-size: 14px;
            }
            QLineEdit:focus { border-color: #4CAF50; }
            QPushButton {
                background-color: #4CAF50; color: white; border: none;
                border-radius: 8px; padding: 8px 16px; font-size: 14px;
            }
            QPushButton:hover { background-color: #45A049; }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        label = QLabel("请输入兑换码：")
        layout.addWidget(label)

        self.code_edit = QLineEdit()
        layout.addWidget(self.code_edit)

        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("确定")
        self.cancel_btn = QPushButton("取消")
        self.ok_btn.clicked.connect(self.on_ok)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)
        screen_center = QApplication.primaryScreen().availableGeometry().center()
        self.move(screen_center - self.rect().center())

    def on_ok(self):
        code = self.code_edit.text().strip()
        if not code:
            QMessageBox.warning(self, "提示", "请输入兑换码")
            return
        self.code_submitted.emit(code)


class RoundedMenu(QMenu):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(MENU_STYLE)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            super().mouseReleaseEvent(event)

    def showEvent(self, event):
        self.style().unpolish(self)
        self.style().polish(self)
        super().showEvent(event)


# ====================== 兑换明细窗口 ======================
class HistoryWindow(QDialog):
    def __init__(self, user_data, is_admin=False, parent=None):
        super().__init__(parent)
        set_window_emoji_icon(self, "📋")
        self.user_data = user_data
        self.is_admin = is_admin
        self.setWindowTitle("兑换明细")
        self.setFixedSize(550, 400)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #1E1E1E;
                border-radius: 10px;
            }
            QLabel {
                color: #888888;
                font-size: 14px;
            }
            QListWidget {
                background-color: #2D2D2D;
                border: 1px solid #555555;
                border-radius: 8px;
                color: #CCCCCC;
                font-size: 12px;
                padding: 5px;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45A049;
            }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel("历史记录")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:18px; font-weight:bold; color:#FFFFFF;")
        layout.addWidget(title)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

        self.setLayout(layout)
        self.load_history()
        screen_center = QApplication.primaryScreen().availableGeometry().center()
        self.move(screen_center - self.rect().center())

    def load_history(self):
        history = self.user_data.get("redeem_history", [])
        for record in history:
            self.list_widget.addItem(record)
        if not history:
            self.list_widget.addItem("暂无记录")


# ====================== 商店窗口 ======================
class ShopWindow(QDialog):
    def __init__(self, firefly, parent=None):
        super().__init__(parent)
        set_window_emoji_icon(self, "🛒")
        self.firefly = firefly
        self.user_data = firefly.current_user
        self.setWindowTitle("商店 - 橡木蛋糕卷")
        self.setFixedSize(550, 420)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #1E1E1E;
                border-radius: 12px;
            }
            QLabel {
                color: #888888;
                font-size: 14px;
            }
            QLineEdit {
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 8px;
                background-color: #2D2D2D;
                color: #888888;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #4CAF50;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45A049;
            }
            QSpinBox {
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 5px;
                background-color: #2D2D2D;
                color: #888888;
                font-size: 14px;
            }
        """)
        self.init_ui()
        screen_center = QApplication.primaryScreen().availableGeometry().center()
        self.move(screen_center - self.rect().center())

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        title = QLabel("信用点商店")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:20px; font-weight:bold; color:#FFFFFF;")
        layout.addWidget(title)

        image_label = QLabel()
        possible_paths = [
            "assets/images/foods/Cake.png",
            "./assets/images/foods/Cake.png",
            os.path.join(os.path.dirname(sys.argv[0]), "assets/images/foods/Cake.png")
        ]
        pixmap = None
        for path in possible_paths:
            if os.path.exists(path):
                pixmap = QPixmap(path)
                break
        if pixmap and not pixmap.isNull():
            pixmap = pixmap.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            image_label.setPixmap(pixmap)
            image_label.setAlignment(Qt.AlignCenter)
        else:
            image_label.setText("📦 橡木蛋糕卷")
            image_label.setAlignment(Qt.AlignCenter)
            image_label.setStyleSheet("font-size: 40px;")
        layout.addWidget(image_label)

        price_label = QLabel("单价：3600 信用点 / 个")
        price_label.setAlignment(Qt.AlignCenter)
        price_label.setStyleSheet("font-size: 16px; color: #FFD700;")
        layout.addWidget(price_label)

        credit = self.user_data.get("credit", 0)
        credit_label = QLabel(f"当前信用点：{credit}")
        credit_label.setAlignment(Qt.AlignCenter)
        credit_label.setStyleSheet("font-size: 14px; color: #AAAAAA;")
        layout.addWidget(credit_label)

        amount_layout = QHBoxLayout()
        amount_label = QLabel("购买数量：")
        self.amount_spin = QSpinBox()
        self.amount_spin.setRange(1, 1)
        self.amount_spin.setValue(1)
        self.amount_spin.setSuffix(" 个")
        self.amount_spin.valueChanged.connect(self.update_total)
        amount_layout.addWidget(amount_label)
        amount_layout.addWidget(self.amount_spin)
        layout.addLayout(amount_layout)

        self.total_price_label = QLabel("总计：3600 信用点")
        self.total_price_label.setAlignment(Qt.AlignCenter)
        self.total_price_label.setStyleSheet("font-size: 14px; color: #AAAAAA;")
        layout.addWidget(self.total_price_label)

        buy_btn = QPushButton("购买")
        buy_btn.clicked.connect(self.buy)
        layout.addWidget(buy_btn)

        self.setLayout(layout)
        self.update_max_amount()
        self.update_total()

    def update_max_amount(self):
        credit = self.user_data.get("credit", 0)
        max_can_buy = credit // 3600
        if max_can_buy < 1:
            max_can_buy = 1
        self.amount_spin.setMaximum(max_can_buy)

    def update_total(self):
        amount = self.amount_spin.value()
        total = amount * 3600
        self.total_price_label.setText(f"总计：{total} 信用点")
        credit = self.user_data.get("credit", 0)
        if total > credit:
            self.total_price_label.setStyleSheet("font-size: 14px; color: #FF5555;")
        else:
            self.total_price_label.setStyleSheet("font-size: 14px; color: #AAAAAA;")

    def buy(self):
        amount = self.amount_spin.value()
        total_credit = amount * 3600
        credit = self.user_data.get("credit", 0)
        if credit < total_credit:
            QMessageBox.warning(self, "提示", f"信用点不足！需要 {total_credit} 信用点，当前拥有 {credit} 点。")
            return
        self.user_data["credit"] = credit - total_credit
        self.user_data["balance"] = self.user_data.get("balance", 0) + amount
        self.firefly.save_user_data(self.user_data)
        self.firefly._save_current_user()
        history = self.user_data.get("redeem_history", [])
        history.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 商店购买 {amount} 个橡木蛋糕卷，花费 {total_credit} 信用点")
        self.user_data["redeem_history"] = history
        self.firefly._save_current_user()
        QMessageBox.information(self, "成功", f"购买成功！获得 {amount} 个橡木蛋糕卷，剩余信用点：{self.user_data['credit']}")
        self.accept()
        self.firefly.update_bag_display()


# ====================== 重置密码窗口 ======================
class ResetPasswordWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        set_window_emoji_icon(self, "🔒")
        self.setWindowTitle("重置密码")
        self.setFixedSize(400, 520)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #1E1E1E;
                border-radius: 10px;
            }
            QLabel {
                font-size: 14px;
                color: #888888;
                background: transparent;
            }
            QLineEdit {
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                background-color: #2D2D2D;
                color: #888888;
            }
            QLineEdit:focus {
                border-color: #4CAF50;
                outline: none;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 15px;
                font-weight: 500;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            QPushButton:hover {
                background-color: #45A049;
                box-shadow: 0 4px 8px rgba(0,0,0,0.15);
            }
            QPushButton:pressed {
                background-color: #3D8B40;
            }
            QDateEdit {
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                background-color: #2D2D2D;
                color: #888888;
            }
            QDateEdit::drop-down {
                border: none;
                subcontrol-origin: padding;
                subcontrol-position: right center;
                width: 20px;
            }
            QDateEdit::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #888888;
                width: 0px;
                height: 0px;
                margin-right: 8px;
            }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(15)
        title = QLabel("重置密码")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:22px; font-weight:bold; color:#FFFFFF;")
        layout.addWidget(title)
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("请输入用户名或用户ID")
        layout.addWidget(QLabel("账号："))
        layout.addWidget(self.user_input)
        self.new_pwd_input = QLineEdit()
        self.new_pwd_input.setPlaceholderText("请输入新密码")
        self.new_pwd_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(QLabel("新密码："))
        layout.addWidget(self.new_pwd_input)
        self.confirm_pwd_input = QLineEdit()
        self.confirm_pwd_input.setPlaceholderText("请再次输入新密码")
        self.confirm_pwd_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(QLabel("确认新密码："))
        layout.addWidget(self.confirm_pwd_input)
        reset_btn = QPushButton("重置密码")
        reset_btn.clicked.connect(self.do_reset)
        layout.addWidget(reset_btn)
        spacer = QSpacerItem(20, 80, QSizePolicy.Minimum, QSizePolicy.Expanding)
        layout.addItem(spacer)
        self.setLayout(layout)
        screen_center = QApplication.primaryScreen().availableGeometry().center()
        self.move(screen_center - self.rect().center())

    def do_reset(self):
        key = self.user_input.text().strip()
        new_pwd = self.new_pwd_input.text().strip()
        confirm_pwd = self.confirm_pwd_input.text().strip()
        if not key or not new_pwd or not confirm_pwd:
            QMessageBox.warning(self, "提示", "请填写完整信息")
            return
        if new_pwd != confirm_pwd:
            QMessageBox.warning(self, "提示", "两次密码输入不一致")
            return
        user_file = None
        user_data = None
        for filename in os.listdir(USER_DATA_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(USER_DATA_DIR, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("username") == key or data.get("userid") == key:
                    user_file = filepath
                    user_data = data
                    break
        if user_file is None:
            QMessageBox.warning(self, "提示", "账号不存在")
            return
        user_data["password"] = new_pwd
        user_data["reset_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_data["redeem_history"] = user_data.get("redeem_history", [])
        user_data["redeem_history"].append(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 重置密码")
        with open(user_file, "w", encoding="utf-8") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "成功", "密码重置成功！请使用新密码登录")
        self.accept()


# ====================== 注册窗口 ======================
class RegisterWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        set_window_emoji_icon(self, "📝")
        self.setWindowTitle("注册账号")
        self.setFixedSize(400, 560)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #1E1E1E;
                border-radius: 10px;
            }
            QLabel {
                font-size: 14px;
                color: #888888;
                background: transparent;
            }
            QLineEdit {
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                background-color: #2D2D2D;
                color: #888888;
            }
            QLineEdit:focus {
                border-color: #4CAF50;
                outline: none;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 15px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #45A049;
            }
            QDateEdit {
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 10px;
                background-color: #2D2D2D;
                color: #888888;
            }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(12)
        title = QLabel("用户注册")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:20px; font-weight:bold; color:#FFFFFF;")
        layout.addWidget(title)
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("用户名（唯一）")
        layout.addWidget(QLabel("用户名："))
        layout.addWidget(self.user_input)
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("用户ID（长度<20，仅字母数字下划线）")
        layout.addWidget(QLabel("用户ID："))
        layout.addWidget(self.id_input)
        self.pwd_input = QLineEdit()
        self.pwd_input.setPlaceholderText("密码")
        self.pwd_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(QLabel("密码："))
        layout.addWidget(self.pwd_input)
        self.pwd2_input = QLineEdit()
        self.pwd2_input.setPlaceholderText("确认密码")
        self.pwd2_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(QLabel("确认密码："))
        layout.addWidget(self.pwd2_input)
        self.birth_input = QDateEdit()
        self.birth_input.setCalendarPopup(True)
        self.birth_input.setDate(QDate.currentDate().addYears(-18))
        layout.addWidget(QLabel("生日："))
        layout.addWidget(self.birth_input)
        reg_btn = QPushButton("完成注册")
        reg_btn.clicked.connect(self.do_register)
        layout.addWidget(reg_btn)
        self.setLayout(layout)
        screen_center = QApplication.primaryScreen().availableGeometry().center()
        self.move(screen_center - self.rect().center())

    def generate_unique_uid(self):
        existing_uids = set()
        for filename in os.listdir(USER_DATA_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(USER_DATA_DIR, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "uid" in data:
                        existing_uids.add(data["uid"])
        while True:
            rand_num = str(random.randint(0, 10 ** 9 - 1)).zfill(9)
            uid_candidate = f"user-{rand_num}"
            if uid_candidate not in existing_uids:
                return uid_candidate

    def do_register(self):
        username = self.user_input.text().strip()
        userid = self.id_input.text().strip()
        pwd = self.pwd_input.text().strip()
        pwd2 = self.pwd2_input.text().strip()
        birth = self.birth_input.date().toString("yyyy-MM-dd")
        if not username or not userid or not pwd or not pwd2:
            QMessageBox.warning(self, "提示", "请填写完整信息")
            return
        if pwd != pwd2:
            QMessageBox.warning(self, "提示", "两次密码不一致")
            return
        if len(userid) >= 20:
            QMessageBox.warning(self, "提示", "用户ID长度必须小于20")
            return
        if not re.match(r'^[a-zA-Z0-9_]+$', userid):
            QMessageBox.warning(self, "提示", "用户ID只能包含字母、数字和下划线")
            return
        userid_path = os.path.join(USER_DATA_DIR, f"{userid}.json")
        if os.path.exists(userid_path):
            QMessageBox.warning(self, "提示", "用户ID已存在")
            return
        for filename in os.listdir(USER_DATA_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(USER_DATA_DIR, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if existing.get("username") == username:
                    QMessageBox.warning(self, "提示", "用户名已存在")
                    return
        uid = self.generate_unique_uid()
        initial_credit = 99999 if uid.lower().startswith("trailblazer") else 0
        data = {
            "uid": uid,
            "username": username,
            "userid": userid,
            "password": pwd,
            "birthday": birth,
            "register_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "balance": 20,
            "credit": initial_credit,
            "last_sign_date": None,
            "banned": False,
            "banned_until": None,
            "redeemed_codes": [],
            "redeem_history": [f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 注册账号，获得20橡木蛋糕卷" + (f"，获得{initial_credit}信用点" if initial_credit > 0 else "")],
            "cursor_style": "None",
            "pet_size": "normal",
            "owned_clothes": ["normal"],
            "mailbox": [],
            "star_rail_tickets": 0,
            "last_birthday_greet_year": None
        }
        with open(userid_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "成功", f"注册成功！\n用户ID：{userid}\nUID：{uid}")
        self.accept()


# ====================== 登录窗口 ======================
class LoginWindow(QDialog):
    login_success = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        set_window_emoji_icon(self, "🔑")
        self.setWindowTitle("用户登录")
        self.setFixedSize(400, 520)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #1E1E1E;
                border-radius: 10px;
            }
            QLabel {
                font-size: 14px;
                color: #888888;
                background: transparent;
            }
            QLineEdit {
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                background-color: #2D2D2D;
                color: #888888;
            }
            QLineEdit:focus {
                border-color: #4CAF50;
                outline: none;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 15px;
                font-weight: 500;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            QPushButton:hover {
                background-color: #45A049;
                box-shadow: 0 4px 8px rgba(0,0,0,0.15);
            }
            QPushButton:pressed {
                background-color: #3D8B40;
            }
            QCheckBox {
                font-size: 13px;
                color: #888888;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 2px solid #555555;
                background-color: #2D2D2D;
            }
            QCheckBox::indicator:hover {
                border-color: #4CAF50;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF90;
                border-color: #FFFFFF;
            }
            QLabel#forgetPwdLabel {
                color: #4CAF50;
                font-size: 13px;
                text-decoration: underline;
            }
            QLabel#forgetPwdLabel:hover {
                color: #45A049;
                cursor: pointer;
            }
        """)
        self.current_user = None
        self.init_ui()
        self.load_remember()
        screen_center = QApplication.primaryScreen().availableGeometry().center()
        self.move(screen_center - self.rect().center())


    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(15)

        title = QLabel("登录")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:22px; font-weight:bold; color:#FFFFFF;")
        layout.addWidget(title)

        logo_label = QLabel()
        pixmap = QPixmap("./assets/images/icon/Login_img.png")
        pixmap = pixmap.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        transparent_pixmap = QPixmap(pixmap.size())
        transparent_pixmap.fill(Qt.transparent)
        painter = QPainter(transparent_pixmap)
        painter.setOpacity(0.5)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        logo_label.setPixmap(transparent_pixmap)
        logo_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo_label)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("用户名 / 用户ID")
        layout.addWidget(QLabel("账号："))
        layout.addWidget(self.user_edit)

        self.pwd_edit = QLineEdit()
        self.pwd_edit.setPlaceholderText("密码")
        self.pwd_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(QLabel("密码："))
        layout.addWidget(self.pwd_edit)

        remember_forget_layout = QHBoxLayout()
        self.remember = QCheckBox("记住登录状态")
        self.remember.setStyleSheet("color:#888888;")
        self.forget_pwd_label = QLabel("忘记密码？")
        self.forget_pwd_label.setObjectName("forgetPwdLabel")
        self.forget_pwd_label.setAlignment(Qt.AlignRight)
        self.forget_pwd_label.mousePressEvent = self.open_reset_password
        remember_forget_layout.addWidget(self.remember)
        remember_forget_layout.addWidget(self.forget_pwd_label)
        layout.addLayout(remember_forget_layout)

        btn_layout = QHBoxLayout()
        login_btn = QPushButton("登录")
        reg_btn = QPushButton("注册")
        login_btn.clicked.connect(self.do_login)
        reg_btn.clicked.connect(self.open_reg)
        btn_layout.addWidget(login_btn)
        btn_layout.addWidget(reg_btn)
        layout.addLayout(btn_layout)

        spacer = QSpacerItem(20, 60, QSizePolicy.Minimum, QSizePolicy.Expanding)
        layout.addItem(spacer)
        self.setLayout(layout)

    def open_reset_password(self, event):
        reset_win = ResetPasswordWindow(self)
        reset_win.open()

    def closeEvent(self, event):
        sys.exit(0)

    def load_remember(self):
        if not os.path.exists(USER_CONFIG):
            return
        try:
            with open(USER_CONFIG, encoding="utf-8") as f:
                d = json.load(f)
                if d.get("remember"):
                    self.user_edit.setText(d.get("userid", ""))
                    self.pwd_edit.setText(d.get("password", ""))
                    self.remember.setChecked(True)
        except:
            pass

    def save_remember(self):
        d = {
            "userid": self.current_user["userid"],
            "password": self.current_user["password"],
            "remember": self.remember.isChecked()
        }
        with open(USER_CONFIG, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)

    def open_reg(self):
        reg_win = RegisterWindow(self)
        reg_win.open()

    def do_login(self):
        key = self.user_edit.text().strip()
        pwd = self.pwd_edit.text().strip()
        if not key or not pwd:
            QMessageBox.warning(self, "提示", "账号和密码不能为空")
            return
        found_user = None
        user_filepath = None
        for filename in os.listdir(USER_DATA_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(USER_DATA_DIR, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("username") == key or data.get("userid") == key:
                    found_user = data
                    user_filepath = filepath
                    break
        if found_user is None:
            QMessageBox.warning(self, "错误", "账号不存在")
            return
        if found_user["password"] != pwd:
            QMessageBox.warning(self, "错误", "密码错误")
            return
        found_user = ensure_user_fields(found_user, user_filepath)
        banned_until = found_user.get("banned_until")
        if banned_until:
            try:
                until_date = datetime.fromisoformat(banned_until)
                if datetime.now() < until_date:
                    remaining = until_date - datetime.now()
                    days = remaining.days
                    QMessageBox.warning(self, "提示",
                                        f"此用户已被封禁，剩余 {days} 天，解封日期：{until_date.strftime('%Y-%m-%d')}")
                    return
                else:
                    found_user["banned"] = False
                    found_user["banned_until"] = None
                    with open(user_filepath, "w", encoding="utf-8") as f:
                        json.dump(found_user, f, ensure_ascii=False, indent=2)
            except:
                pass
        if found_user.get("banned"):
            QMessageBox.warning(self, "提示", "此用户已被禁止使用流萤桌宠")
            return
        self.current_user = found_user
        self.save_remember()
        self.login_success.emit(found_user)
        self.accept()


# -------------------------- 核心桌宠类 --------------------------
class Firefly(QWidget):
    def __init__(self, user_data=None, parent=None):
        super(Firefly, self).__init__(parent)
        self.current_user = user_data
        self.label = QLabel("", self)
        self.label.resize(500, 500)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.tray_icon = None
        self.movie = None
        self.draggable = False
        self.offset = None
        self.current_animation_state = "Standby"
        self.last_animation_state = "Standby"
        self.last_update_time = time.time()
        self.settings = QSettings("GUCNMC", "流萤桌宠")
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        windowState = self.settings.value("windowState")
        if windowState is not None:
            self.restoreWindowState(windowState)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.changeToDiscomfort)
        self.timer.start(1800000)

        self.music_file = "./Large_Music/不眠之夜.wav"
        self.music_file2 = "./Large_Music/打上花火.wav"
        self.music_file3 = "./Large_Music/520AM.wav"
        self.music_file4 = "./Large_Music/Dream of firefly.wav"
        self.music = None
        self.possible_file_names = ["流萤指针", "萨姆指针", "无指针"]
        self.GUI_file_names = ["Large", "small", "normal", "medium"]
        self.current_file_name = self.get_existing_file_name()
        self.setMouseTracking(True)
        self.installEventFilter(self)
        self.persistent_state = self.current_user.get("last_state", "Standby") if self.current_user else "Standby"

        if self.current_user:
            self.current_user = ensure_user_fields(self.current_user)
            self.apply_cursor_style()
            self.apply_pet_size()
        self.last_interaction_time = time.time()
        self.emo_random_delay = random.randint(0, 15 * 60)
        self.sleep_start_time = None
        self.anim_restore_timer = None
        self.wake_action_tray = None

        if hasattr(self, 'timer') and self.timer:
            self.timer.stop()
        self.emo_check_timer = QTimer(self)
        self.emo_check_timer.timeout.connect(self.check_emo)
        self.emo_check_timer.start(1000)

    def restore_last_position(self):
        if not self.current_user:
            return
        x = self.current_user.get("last_x")
        y = self.current_user.get("last_y")
        if x is not None and y is not None:
            screen = QApplication.primaryScreen().availableGeometry()
            if x < screen.x():
                x = screen.x()
            if y < screen.y():
                y = screen.y()
            if x > screen.right() - self.width():
                x = screen.right() - self.width()
            if y > screen.bottom() - self.height():
                y = screen.bottom() - self.height()
            self.move(x, y)

    def show_exit_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("退出桌宠")
        dialog.setFixedSize(350, 180)
        dialog.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        dialog.setStyleSheet("""
                    QDialog {
                        background-color: #1E1E1E;
                        border: 2px solid #4CAF50;
                        border-top-left-radius: 0px;
                        border-top-right-radius: 0px;
                        border-bottom-left-radius: 8px;
                        border-bottom-right-radius: 8px;
                    }
                    QLabel {
                        color: #CCCCCC;
                        font-size: 15px;
                        font-weight: bold;
                    }
                    QPushButton {
                        background-color: #3A3A3A;
                        color: #EEEEEE;
                        border: 1px solid #555555;
                        border-radius: 8px;
                        padding: 10px;
                        font-size: 14px;
                    }
                    QPushButton:hover {
                        background-color: #4CAF50;
                        color: white;
                        border: 1px solid #4CAF50;
                    }
                    QPushButton#logout_btn {
                        background-color: #D32F2F;
                        border: 1px solid #D32F2F;
                    }
                    QPushButton#logout_btn:hover {
                        background-color: #F44336;
                    }
                    QPushButton#exit_btn {
                        background-color: #4CAF50;
                        border: 1px solid #4CAF50;
                    }
                    QPushButton#exit_btn:hover {
                        background-color: #45A049;
                    }
                """)

        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 20)
        layout.setSpacing(20)

        label = QLabel("确定要退出桌宠吗？")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)

        exit_btn = QPushButton("退出")
        exit_btn.setObjectName("exit_btn")
        exit_btn.clicked.connect(lambda: self._handle_exit_choice(dialog, clear_login=False))

        logout_btn = QPushButton("退出并登出")
        logout_btn.setObjectName("logout_btn")
        logout_btn.clicked.connect(lambda: self._handle_exit_choice(dialog, clear_login=True))

        btn_layout.addWidget(exit_btn)
        btn_layout.addWidget(logout_btn)
        layout.addLayout(btn_layout)

        dialog.setLayout(layout)
        set_window_emoji_icon(dialog, "🚪")
        screen_center = QApplication.primaryScreen().availableGeometry().center()
        dialog.move(screen_center - dialog.rect().center())
        dialog.exec_()

    def _handle_exit_choice(self, dialog, clear_login=False):
        dialog.accept()
        if clear_login:
            if os.path.exists(USER_CONFIG):
                os.remove(USER_CONFIG)
            self._perform_logout()
        else:
            self.out_win()

    def _perform_logout(self):
        self.current_user["last_state"] = self.persistent_state
        pos = self.pos()
        self.current_user["last_x"] = pos.x()
        self.current_user["last_y"] = pos.y()
        self._save_current_user()
        self.current_user = None
        self.hide()
        self.tray_icon.setVisible(False)
        self.show_login_again()

    def record_interaction(self, extra_seconds=0):
        self.last_interaction_time = time.time() + extra_seconds
        self.emo_random_delay = random.randint(0, 15 * 60)
        if self.current_animation_state == "Discomfort":
            self.changeToStandby()
            self.last_animation_state = "Standby"

    def check_emo(self):
        if self.current_animation_state == "Sleep":
            return
        if self.current_animation_state == "Discomfort":
            return

        elapsed = time.time() - self.last_interaction_time
        threshold = 20 * 60 + self.emo_random_delay
        if elapsed >= threshold:
            self.changeToDiscomfort()

    def apply_cursor_style(self):
        if not self.current_user:
            return
        style = self.current_user.get("cursor_style", "None")
        self._apply_cursor_by_style(style)

    def _apply_cursor_by_style(self, style):
        if style == "Firefly":
            pixmap = QPixmap('mouse/Firefly/p1.gif')
            if not pixmap.isNull():
                self.setCursor(QCursor(pixmap))
            else:
                self.setCursor(QCursor(Qt.ArrowCursor))
        elif style == "Sam":
            pixmap = QPixmap('mouse/Sam/p2.gif')
            if not pixmap.isNull():
                self.setCursor(QCursor(pixmap))
            else:
                self.setCursor(QCursor(Qt.ArrowCursor))
        else:
            self.setCursor(QCursor(Qt.ArrowCursor))

    def set_cursor_style(self, style):
        if not self.current_user:
            return
        self._apply_cursor_by_style(style)
        self.current_user["cursor_style"] = style
        self._save_current_user()

    def _set_pet_size(self, size, save=True):
        target = size
        existing = None
        for name in ["Large", "small", "normal", "medium"]:
            if os.path.exists(name):
                existing = name
                break
        if existing and existing != target:
            try:
                os.rename(existing, target)
            except Exception as e:
                print(f"重命名大小标记文件失败: {e}")
        elif not existing:
            with open(target, "w") as f:
                f.write("")
        self._init_movie_from_file()
        if save and self.current_user:
            self.current_user["pet_size"] = target
            self._save_current_user()

    def apply_pet_size(self):
        if not self.current_user:
            return
        size = self.current_user.get("pet_size", "normal")
        self._set_pet_size(size, save=False)

    def _init_movie_from_file(self):
        state = "Standby"
        if self.current_user and "last_state" in self.current_user:
            if self.current_user["last_state"] == "Discomfort":
                state = "Discomfort"
        files = os.listdir(".")
        if 'Large' in files:
            self.movie = QMovie(f'./assets/images/firefly/actions/{state}/{state}_Large.gif')
        elif 'small' in files:
            self.movie = QMovie(f'./assets/images/firefly/actions/{state}/{state}_small.gif')
        elif 'normal' in files:
            self.movie = QMovie(f'./assets/images/firefly/actions/{state}/{state}.gif')
        elif 'medium' in files:
            self.movie = QMovie(f'./assets/images/firefly/actions/{state}/{state}_medium.gif')
        else:
            self.movie = QMovie(f'./assets/images/firefly/actions/{state}/{state}.gif')
        self.label.setMovie(self.movie)
        self.movie.start()
        self.current_animation_state = state
        self.persistent_state = state

    def init_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        if os.path.exists('icon/setting.ico'):
            self.tray_icon.setIcon(QIcon('icon/setting.ico'))
        else:
            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setBrush(QBrush(QColor(0, 123, 255)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(0, 0, 16, 16, 4, 4)
            painter.end()
            self.tray_icon.setIcon(QIcon(pixmap))
        self.create_menu()
        self.tray_icon.show()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and obj is self:
            self.wheelEvent(event)
            return True
        return super().eventFilter(obj, event)

    def get_existing_file_name(self):
        for name in self.possible_file_names:
            if os.path.exists(name):
                return name
        return None

    def play_music(self):
        if pygame.mixer.get_num_channels() > 0:
            if self.music is None:
                self.music = pygame.mixer.music.load(self.music_file)
            pygame.mixer.music.play()
        else:
            print("未检测到扬声器，无法播放音频。")
            return False

    def open_settings(self):
        def check_process_running(process_name):
            for process in psutil.process_iter(['name']):
                if process.info['name'] == process_name:
                    return True
            return False
        process_name = '工具组件.exe'
        if not check_process_running(process_name):
            subprocess.Popen(["./tools/工具组件.exe"])

    def open_settings_tool(self):
        def check_process_running(process_name):
            for process in psutil.process_iter(['name']):
                if process.info['name'] == process_name:
                    return True
            return False
        process_name = '工具组件.exe'
        if not check_process_running(process_name):
            subprocess.Popen(["./tools/工具组件.exe"])

    def play_music2(self):
        if pygame.mixer.get_num_channels() > 0:
            if self.music is None:
                self.music = pygame.mixer.music.load(self.music_file2)
            pygame.mixer.music.play()
        else:
            print("未检测到扬声器，无法播放音频。")
            return False

    def play_music3(self):
        if pygame.mixer.get_num_channels() > 0:
            if self.music is None:
                self.music = pygame.mixer.music.load(self.music_file3)
            pygame.mixer.music.play()
        else:
            print("未检测到扬声器，无法播放音频。")
            return False

    def play_music4(self):
        if pygame.mixer.get_num_channels() > 0:
            if self.music is None:
                self.music = pygame.mixer.music.load(self.music_file4)
            pygame.mixer.music.play()
        else:
            print("未检测到扬声器，无法播放音频。")
            return False

    def stop_music(self):
        self.changeToStandby()
        pygame.mixer.music.stop()
        self.music = None

    def change_GUI_to_Large(self):
        self._set_pet_size("Large", save=True)

    def change_GUI_to_normal(self):
        self._set_pet_size("normal", save=True)

    def change_GUI_to_medium(self):
        self._set_pet_size("medium", save=True)

    def change_GUI_to_small(self):
        self._set_pet_size("small", save=True)

    def apply_clothes(self, clothes_id):
        info = AVAILABLE_CLOTHES.get(clothes_id)
        if not info:
            self.show_centered_message("错误", f"未知时装ID: {clothes_id}", QMessageBox.Warning)
            return
        source_dir = info["source_dir"]
        target_dir = "assets"
        if not os.path.exists(source_dir):
            self.show_centered_message("错误", f"时装资源目录不存在：{source_dir}\n请确保程序目录下有该文件夹。",
                                       QMessageBox.Warning)
            return
        try:
            # 统计复制文件数
            copied_count = 0
            for root, dirs, files in os.walk(source_dir):
                relative_path = os.path.relpath(root, source_dir)
                target_root = os.path.join(target_dir, relative_path)
                os.makedirs(target_root, exist_ok=True)
                for file in files:
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(target_root, file)
                    shutil.copy2(src_file, dst_file)
                    copied_count += 1
            self.show_centered_message("成功", f"时装已切换为：{info['name']}")
            # 刷新当前动画
            self._refresh_animation_after_clothes_change()
        except Exception as e:
            self.show_centered_message("错误", f"切换失败：{str(e)}", QMessageBox.Warning)

    def _refresh_animation_after_clothes_change(self):
        """切换时装后重新加载当前动画"""
        state = self.current_animation_state
        if state == "Standby":
            self.changeToStandby()
        elif state == "Discomfort":
            self.changeToDiscomfort()
        elif state == "Sleep":
            self.sleep()  # 重新播放睡眠动画
        else:
            # 处于 eat/love/sing 等临时状态，恢复待机
            self.changeToStandby()

    def copy_normal(self):
        self.apply_clothes("normal")

    def copy_new_year(self):
        self.apply_clothes("26_Newyear")

    # ====================== 用户数据操作 ======================
    def _save_current_user(self):
        if not self.current_user:
            return
        userid = self.current_user.get("userid")
        if userid:
            filepath = os.path.join(USER_DATA_DIR, f"{userid}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.current_user, f, ensure_ascii=False, indent=2)

    def find_user_by_identifier(self, identifier):
        for filename in os.listdir(USER_DATA_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(USER_DATA_DIR, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if (data.get("username") == identifier or
                        data.get("userid") == identifier or
                        data.get("uid") == identifier):
                    return data
        return None

    def find_users_by_identifiers(self, identifiers_str):
        if not identifiers_str or identifiers_str.strip() == "none":
            return None
        if identifiers_str.strip() == "@a":
            all_users = []
            for filename in os.listdir(USER_DATA_DIR):
                if filename.endswith(".json"):
                    filepath = os.path.join(USER_DATA_DIR, filename)
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    all_users.append(data)
            return all_users if all_users else None
        identifiers = [i.strip() for i in identifiers_str.split(',') if i.strip()]
        if not identifiers:
            return None
        found_users = []
        for ident in identifiers:
            user_data = self.find_user_by_identifier(ident)
            if not user_data:
                raise ValueError(f"用户不存在: {ident}")
            found_users.append(user_data)
        return found_users

    def save_user_data(self, user_data):
        userid = user_data.get("userid")
        if userid:
            filepath = os.path.join(USER_DATA_DIR, f"{userid}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(user_data, f, ensure_ascii=False, indent=2)

    def send_mail_to_user(self, target_user, title, content, items):
        send_mail(target_user, title, content, items)
        self.save_user_data(target_user)
        if target_user["userid"] == self.current_user["userid"]:
            self._save_current_user()

    def show_centered_message(self, title, text, icon=QMessageBox.Information, buttons=QMessageBox.Ok):
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setIcon(icon)
        msg.setStandardButtons(buttons)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #1E1E1E;
                border-radius: 10px;
            }
            QLabel {
                color: #888888;
                font-size: 14px;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45A049;
            }
        """)
        if buttons == (QMessageBox.Yes | QMessageBox.No):
            yes_btn = msg.button(QMessageBox.Yes)
            if yes_btn:
                yes_btn.setStyleSheet("background-color: #F44336;")
            no_btn = msg.button(QMessageBox.No)
            if no_btn:
                no_btn.setStyleSheet("background-color: #4CAF50;")
        screen_center = QApplication.primaryScreen().availableGeometry().center()
        msg.move(screen_center - msg.rect().center())
        return msg.exec_()

    # ---------- 信用点相关 ----------
    def give_credit(self, amount, target_identifiers_str=None):
        try:
            amount = int(amount)
            if amount <= 0 or amount > 99999999:
                raise ValueError
        except:
            self.show_centered_message("错误", "数量必须是 1-99999999 的整数", QMessageBox.Warning)
            return False
        if target_identifiers_str:
            try:
                target_users = self.find_users_by_identifiers(target_identifiers_str)
                if target_users is None:
                    self.show_centered_message("错误", "目标用户列表无效", QMessageBox.Warning)
                    return False
                current_uid = self.current_user.get("uid", "")
                is_current_admin = current_uid.lower().startswith("admin")
                for tu in target_users:
                    if is_current_admin and tu["uid"].lower().startswith("admin") and tu["userid"] != self.current_user["userid"]:
                        self.show_centered_message("错误", f"不能操作其他管理员用户: {tu['username']}", QMessageBox.Warning)
                        return False
                for tu in target_users:
                    self.send_mail_to_user(tu, "管理员赠送信用点",
                                           f"管理员 {self.current_user['username']} 赠送了 {amount} 信用点。",
                                           [{"type": "credit", "amount": amount}])
                self.show_centered_message("成功", f"已向 {len(target_users)} 个用户发送信用点邮件", QMessageBox.Information)
            except ValueError as e:
                self.show_centered_message("错误", str(e), QMessageBox.Warning)
                return False
        else:
            self.send_mail_to_user(self.current_user, "管理员添加信用点",
                                   f"给自己添加了 {amount} 信用点。",
                                   [{"type": "credit", "amount": amount}])
            self.show_centered_message("成功", "已给自己发送信用点邮件", QMessageBox.Information)
        return True

    def set_credit(self, amount, target_identifiers_str=None):
        try:
            amount = int(amount)
            if amount < 0 or amount > 99999999:
                raise ValueError
        except:
            self.show_centered_message("错误", "数量必须是 0-99999999 的整数", QMessageBox.Warning)
            return False
        if target_identifiers_str:
            try:
                target_users = self.find_users_by_identifiers(target_identifiers_str)
                if target_users is None:
                    self.show_centered_message("错误", "目标用户列表无效", QMessageBox.Warning)
                    return False
                for tu in target_users:
                    tu["credit"] = amount
                    self.save_user_data(tu)
                self.show_centered_message("成功", f"已设置 {len(target_users)} 个用户的信用点", QMessageBox.Information)
            except ValueError as e:
                self.show_centered_message("错误", str(e), QMessageBox.Warning)
                return False
        else:
            self.current_user["credit"] = amount
            self._save_current_user()
            self.show_centered_message("成功", "已设置自己的信用点", QMessageBox.Information)
        return True

    # ---------- 签到 ----------
    def sign_in(self):
        now = datetime.now()
        today_3am = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if now < today_3am:
            reset_time = today_3am - timedelta(days=1)
        else:
            reset_time = today_3am

        last_sign = self.current_user.get("last_sign_date")
        if last_sign:
            try:
                last_sign_dt = datetime.fromisoformat(last_sign)
                if last_sign_dt >= reset_time:
                    self.show_centered_message("提示", "今日已经签到过了，凌晨3点后再来哦！", QMessageBox.Warning)
                    self.create_menu()  # 刷新托盘菜单，确保按钮已禁用
                    return
            except:
                pass

        # --- 签到逻辑（原有代码）---
        uid = self.current_user.get("uid", "").lower()
        is_trailblazer = uid.startswith("trailblazer")
        base_credit = 36000 if is_trailblazer else 7200
        self.current_user["credit"] = self.current_user.get("credit", 0) + base_credit
        if self.current_user["credit"] > 99999999:
            self.current_user["credit"] = 99999999

        extra_msg = ""
        today_date = now.date()
        try:
            lunar = LunarDate.fromSolarDate(today_date.year, today_date.month, today_date.day)
            if today_date.year == 2026 and lunar.month == 1 and 1 <= lunar.day <= 15:
                self.current_user["credit"] = self.current_user.get("credit", 0) + 888
                if self.current_user["credit"] > 99999999:
                    self.current_user["credit"] = 99999999
                owned = self.current_user.get("owned_clothes", ["normal"])
                if "26_Newyear" not in owned:
                    owned.append("26_Newyear")
                    self.current_user["owned_clothes"] = owned
                    extra_msg = "，并获得新春时装[柿柿如意] + 888信用点"
                else:
                    extra_msg = "，并获得888信用点（已有时装不再赠送）"
        except:
            pass

        self.current_user["last_sign_date"] = now.isoformat()
        self._save_current_user()

        history = self.current_user.get("redeem_history", [])
        history.append(f"{now.strftime('%Y-%m-%d %H:%M:%S')} - 签到获得 {base_credit} 信用点{extra_msg}")
        self.current_user["redeem_history"] = history
        self._save_current_user()

        # 刷新托盘菜单（签到成功后）
        self.create_menu()

        self.show_centered_message("成功", f"签到成功！获得 {base_credit} 信用点{extra_msg}。", QMessageBox.Information)

    def is_signed_today(self):
        """判断今天是否已签到（基于凌晨3点重置规则）"""
        last_sign = self.current_user.get("last_sign_date")
        if not last_sign:
            return False
        try:
            last_sign_dt = datetime.fromisoformat(last_sign)
            now = datetime.now()
            today_3am = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if now < today_3am:
                reset_time = today_3am - timedelta(days=1)
            else:
                reset_time = today_3am
            return last_sign_dt >= reset_time
        except:
            return False

    def update_bag_display(self):
        pass

    def open_shop(self):
        shop = ShopWindow(self, self)
        shop.open()

    def give_item(self, amount, item_type, target_identifiers_str=None, clothes_id=None):
        if item_type not in ("cake", "clothes"):
            self.show_centered_message("错误", f"未知物品类型: {item_type}", QMessageBox.Warning)
            return False
        if item_type == "clothes" and not clothes_id:
            self.show_centered_message("错误", "时装必须指定 clothes_id", QMessageBox.Warning)
            return False
        try:
            amount = int(amount)
            if amount <= 0 or amount > 9999:
                raise ValueError
        except:
            self.show_centered_message("错误", "数量必须是 1-9999 的整数", QMessageBox.Warning)
            return False

        items = []
        if item_type == "cake":
            items.append({"type": "cake", "amount": amount})
        else:
            items.append({"type": "clothes", "id": clothes_id})

        if target_identifiers_str:
            try:
                target_users = self.find_users_by_identifiers(target_identifiers_str)
                if target_users is None:
                    self.show_centered_message("错误", "目标用户列表无效", QMessageBox.Warning)
                    return False
                current_uid = self.current_user.get("uid", "")
                is_current_admin = current_uid.lower().startswith("admin")
                for tu in target_users:
                    if is_current_admin and tu["uid"].lower().startswith("admin") and tu["userid"] != self.current_user["userid"]:
                        self.show_centered_message("错误", f"不能操作其他管理员用户: {tu['username']}", QMessageBox.Warning)
                        return False
                for tu in target_users:
                    self.send_mail_to_user(tu, "管理员赠送物品",
                                           f"管理员 {self.current_user['username']} 赠送了 {'橡木蛋糕卷' if item_type=='cake' else '时装['+AVAILABLE_CLOTHES[clothes_id]['name']+']'}。",
                                           items)
                self.show_centered_message("成功", f"已向 {len(target_users)} 个用户发送物品邮件", QMessageBox.Information)
            except ValueError as e:
                self.show_centered_message("错误", str(e), QMessageBox.Warning)
                return False
        else:
            self.send_mail_to_user(self.current_user, "管理员添加物品",
                                   f"给自己添加了 {'橡木蛋糕卷' if item_type=='cake' else '时装['+AVAILABLE_CLOTHES[clothes_id]['name']+']'}。",
                                   items)
            self.show_centered_message("成功", "已给自己发送物品邮件", QMessageBox.Information)
        return True

    def clear_item(self, item_type, target_identifiers_str=None):
        if item_type != "cake":
            self.show_centered_message("错误", "当前仅支持清空橡木蛋糕卷", QMessageBox.Warning)
            return False
        if target_identifiers_str:
            try:
                target_users = self.find_users_by_identifiers(target_identifiers_str)
                if target_users is None:
                    self.show_centered_message("错误", "目标用户列表无效", QMessageBox.Warning)
                    return False
                for tu in target_users:
                    tu["balance"] = 0
                    self.save_user_data(tu)
                self.show_centered_message("成功", f"已清空 {len(target_users)} 个用户的蛋糕卷", QMessageBox.Information)
            except ValueError as e:
                self.show_centered_message("错误", str(e), QMessageBox.Warning)
                return False
        else:
            self.current_user["balance"] = 0
            self._save_current_user()
            self.show_centered_message("成功", "已清空自己的蛋糕卷", QMessageBox.Information)
        return True

    def revoke_code(self, code, target_spec=None):
        all_codes = load_all_codes()
        if code not in all_codes:
            self.show_centered_message("错误", f"兑换码 {code} 不存在", QMessageBox.Warning)
            return
        cinfo = all_codes[code]

        # 构建物品描述字符串（用于日志）
        def describe_items(items):
            desc = []
            for item in items:
                t = item["type"]
                if t == "cake":
                    desc.append(f"蛋糕卷x{item['amount']}")
                elif t == "credit":
                    desc.append(f"信用点x{item['amount']}")
                elif t == "clothes":
                    name = AVAILABLE_CLOTHES.get(item["id"], {}).get("name", item["id"])
                    desc.append(f"时装[{name}]")
            return ", ".join(desc) if desc else "无"

        if target_spec is None or target_spec.strip().lower() == "none":
            # 全局撤销
            if cinfo.get("revoked"):
                self.show_centered_message("提示", f"兑换码 {code} 已经被全局撤销过了", QMessageBox.Warning)
                return
            cinfo["revoked"] = True
            cinfo["revoked_by"] = self.current_user["username"]
            cinfo["revoked_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            items_to_remove = cinfo.get("items", [])
            item_desc = describe_items(items_to_remove)

            revoked_users_list = []
            for filename in os.listdir(USER_DATA_DIR):
                if not filename.endswith(".json"):
                    continue
                filepath = os.path.join(USER_DATA_DIR, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    user_data = json.load(f)
                redeemed = user_data.get("redeemed_codes", [])
                if code not in redeemed:
                    continue

                # 扣除所有物品
                for item in items_to_remove:
                    itype = item["type"]
                    if itype == "cake":
                        user_data["balance"] = user_data.get("balance", 0) - item["amount"]
                        if user_data["balance"] < 0:
                            user_data["balance"] = 0
                    elif itype == "credit":
                        user_data["credit"] = user_data.get("credit", 0) - item["amount"]
                        if user_data["credit"] < 0:
                            user_data["credit"] = 0
                    elif itype == "clothes":
                        owned = user_data.get("owned_clothes", [])
                        cid = item["id"]
                        if cid in owned:
                            owned.remove(cid)
                            user_data["owned_clothes"] = owned

                redeemed.remove(code)
                user_data["redeemed_codes"] = redeemed
                history = user_data.get("redeem_history", [])
                history.append(
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [系统] 兑换码 {code} 被管理员 {self.current_user['username']} 撤销，已扣除：{item_desc}"
                )
                user_data["redeem_history"] = history
                self.save_user_data(user_data)
                revoked_users_list.append(user_data["username"])

            history = self.current_user.get("redeem_history", [])
            history.append(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [管理员] 全局撤销兑换码 {code}，影响用户：{', '.join(revoked_users_list) if revoked_users_list else '无'}"
            )
            self.current_user["redeem_history"] = history
            self._save_current_user()
            save_all_codes(all_codes)
            self.show_centered_message("成功", f"已全局撤销兑换码 {code}，影响 {len(revoked_users_list)} 个用户",
                                       QMessageBox.Information)

        else:
            # 指定用户撤销
            try:
                target_users = self.find_users_by_identifiers(target_spec)
                if not target_users:
                    self.show_centered_message("错误", "未找到任何有效用户", QMessageBox.Warning)
                    return
            except ValueError as e:
                self.show_centered_message("错误", str(e), QMessageBox.Warning)
                return

            items_to_remove = cinfo.get("items", [])
            item_desc = describe_items(items_to_remove)

            revoked_count = 0
            for tu in target_users:
                userid = tu["userid"]
                if userid in cinfo.get("revoked_users", []):
                    continue
                redeemed = tu.get("redeemed_codes", [])
                if code not in redeemed:
                    # 该用户并未使用此兑换码，仍标记为已撤销（防止将来使用）
                    cinfo["revoked_users"].append(userid)
                    continue

                # 扣除物品
                for item in items_to_remove:
                    itype = item["type"]
                    if itype == "cake":
                        tu["balance"] = tu.get("balance", 0) - item["amount"]
                        if tu["balance"] < 0:
                            tu["balance"] = 0
                    elif itype == "credit":
                        tu["credit"] = tu.get("credit", 0) - item["amount"]
                        if tu["credit"] < 0:
                            tu["credit"] = 0
                    elif itype == "clothes":
                        owned = tu.get("owned_clothes", [])
                        cid = item["id"]
                        if cid in owned:
                            owned.remove(cid)
                            tu["owned_clothes"] = owned

                redeemed.remove(code)
                tu["redeemed_codes"] = redeemed
                history = tu.get("redeem_history", [])
                history.append(
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [系统] 兑换码 {code} 被管理员 {self.current_user['username']} 撤销，已扣除：{item_desc}"
                )
                tu["redeem_history"] = history
                self.save_user_data(tu)
                revoked_count += 1
                cinfo["revoked_users"].append(userid)

            history = self.current_user.get("redeem_history", [])
            history.append(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [管理员] 撤销用户 {target_spec} 对兑换码 {code} 的使用资格，实际扣除 {revoked_count} 人"
            )
            self.current_user["redeem_history"] = history
            self._save_current_user()
            save_all_codes(all_codes)
            self.show_centered_message("成功", f"已撤销指定用户对兑换码 {code} 的使用资格，扣除 {revoked_count} 个用户",
                                       QMessageBox.Information)

    def show_help(self):
        uid_prefix = self.current_user.get("uid", "").lower()
        is_admin = uid_prefix.startswith("admin")
        if is_admin:
            help_text = """【管理员命令】（所有命令以 / 开头）

/give <数量> <物品类型> [id=时装ID] [for <用户列表>]
    给予物品，示例：/give 100 cake for Gubwin,Firefly
    信用点物品类型为 credit，示例：/give 5000 credit for @a

/clear <物品类型> [for <用户列表>]
    清空物品，示例：/clear cake for Gubwin

/set cake <数量> [for <用户列表>]
    设置蛋糕卷数量，示例：/set cake 50 for Gubwin

/set credit <数量> [for <用户列表>]
    设置信用点数量（覆盖），示例：/set credit 100000 for @a

/set newcode <兑换码> <数量> <1/0> [for <用户列表>] [item=<物品>] [id=时装ID] [expire=<有效期>]
    创建兑换码，有效期格式 YYYY-MM-DD 或 1Y2M3D

/revoke code <兑换码> [for <用户列表>]
    撤销兑换码，不指定用户则全局撤销

/set user <标识> Admin
    提升用户为管理员

/ban <标识>[,<标识2>...] [时长]
    封禁用户，时长如 30D、1Y6M15D

/unban <标识>[,<标识2>...]
    解封用户

/help
    显示此帮助
"""
        else:
            help_text = """【普通用户命令】
直接输入兑换码字符串即可兑换。
可用命令：
/help  - 显示此帮助

签到：右键菜单 → 每日签到
商店：右键菜单 → 商店
邮箱：右键菜单 → 📬 邮箱
"""
        dialog = QDialog(self)
        dialog.setWindowTitle("帮助")
        dialog.setMinimumSize(550, 400)
        dialog.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #1E1E1E;
                border-radius: 12px;
            }
            QTextEdit {
                background-color: #2D2D2D;
                color: #CCCCCC;
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45A049;
            }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        text_edit = QTextEdit()
        text_edit.setPlainText(help_text)
        text_edit.setReadOnly(True)
        layout.addWidget(text_edit)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignCenter)
        dialog.setLayout(layout)
        set_window_emoji_icon(dialog, "❓")
        screen_center = QApplication.primaryScreen().availableGeometry().center()
        dialog.move(screen_center - dialog.rect().center())
        dialog.open()

    def process_admin_command(self, code):
        if not code.startswith('/'):
            return False
        cmd_line = code[1:].strip()
        if not cmd_line:
            return False
        if cmd_line == "help" or cmd_line.startswith("help"):
            self.show_help()
            return True
        if cmd_line.startswith("give "):
            # 尝试匹配新格式：/give clothes <clothes_id> [for ...]（数量默认为1）
            new_pattern = r'give\s+clothes\s+(\S+)(?:\s+for\s+(.+))?$'
            new_match = re.match(new_pattern, cmd_line, re.IGNORECASE)
            if new_match:
                clothes_id = new_match.group(1)
                target = new_match.group(2) if new_match.group(2) else None
                self.give_item(1, "clothes", target, clothes_id=clothes_id)
                return True

            # 原格式：/give <数量> <物品类型> [id=时装ID] [for <用户列表>]
            pattern = r'give\s+(\d+)\s+(\w+)(?:\s+id=(\S+))?(?:\s+for\s+(.+))?$'
            match = re.match(pattern, cmd_line, re.IGNORECASE)
            if not match:
                self.show_centered_message("错误",
                                           "命令格式：/give <数量> <物品类型> [id=时装ID] [for <用户列表>] 或 /give clothes <时装ID> [for ...]",
                                           QMessageBox.Warning)
                return True
            amount = match.group(1)
            item_type = match.group(2).lower()
            clothes_id = match.group(3) if match.group(3) else None
            target = match.group(4) if match.group(4) else None
            if item_type == "credit":
                self.give_credit(amount, target)
            elif item_type == "cake":
                self.give_item(amount, "cake", target)
            elif item_type == "clothes":
                if not clothes_id:
                    self.show_centered_message("错误", "时装必须指定 id= 参数", QMessageBox.Warning)
                else:
                    self.give_item(1, "clothes", target, clothes_id=clothes_id)
            else:
                self.show_centered_message("错误", f"未知物品类型: {item_type}", QMessageBox.Warning)
            return True

        if cmd_line.startswith("clear "):
            pattern = r'clear\s+(\w+)(?:\s+for\s+(.+))?$'
            match = re.match(pattern, cmd_line, re.IGNORECASE)
            if not match:
                self.show_centered_message("错误", "命令格式：/clear <物品类型> [for <用户列表>]", QMessageBox.Warning)
                return True
            item_type = match.group(1).lower()
            target = match.group(2) if match.group(2) else None
            if item_type == "cake":
                self.clear_item("cake", target)
            else:
                self.show_centered_message("错误", "暂不支持清理其他类型", QMessageBox.Warning)
            return True

        if cmd_line.startswith("set newcode "):
            # 新格式：/set newcode <兑换码> <物品1>[,<物品2>,...] [for <用户列表>] [有效期]
            rest = cmd_line[len("set newcode "):].strip()
            # 用正则拆分：兑换码名称、物品列表、可选 for 和有效期
            # 物品列表可能包含逗号，且 for 和有效期相对固定位置
            # 简单方法：先按空格分割，然后处理
            parts = rest.split()
            if len(parts) < 2:
                self.show_centered_message("错误",
                                           "命令格式：/set newcode <兑换码> <物品列表> [for <用户列表>] [有效期]",
                                           QMessageBox.Warning)
                return True

            code = parts[0]
            items_str = parts[1]  # 例如 "cake:5,credit:1000,26_Newyear"
            idx = 2
            user_spec = None
            expire_str = None

            # 解析后续可选参数
            if idx < len(parts):
                if parts[idx].lower() == "for":
                    if idx + 1 >= len(parts):
                        self.show_centered_message("错误", "缺少用户列表", QMessageBox.Warning)
                        return True
                    user_spec = parts[idx + 1]
                    idx += 2
                # 剩余的是有效期
                if idx < len(parts):
                    expire_str = parts[idx]
                    idx += 1
                    if idx < len(parts):
                        # 多余参数
                        self.show_centered_message("错误", "命令参数过多", QMessageBox.Warning)
                        return True

            # 解析物品列表
            items_list = []
            for item_spec in items_str.split(','):
                item_spec = item_spec.strip()
                if not item_spec:
                    continue
                if ':' in item_spec:
                    # cake:数量 或 credit:数量
                    try:
                        itype, amount_str = item_spec.split(':', 1)
                        itype = itype.lower()
                        amount = int(amount_str)
                        if itype == "cake":
                            if amount <= 0 or amount > 9999:
                                raise ValueError
                        elif itype == "credit":
                            if amount <= 0 or amount > 99999999:
                                raise ValueError
                        else:
                            self.show_centered_message("错误", f"未知物品类型: {itype}", QMessageBox.Warning)
                            return True
                    except:
                        self.show_centered_message("错误", f"物品数量格式错误: {item_spec}，正确格式如 cake:5",
                                                   QMessageBox.Warning)
                        return True
                    items_list.append({"type": itype, "amount": amount})
                else:
                    # 时装ID（无冒号）
                    clothes_id = item_spec
                    if clothes_id not in AVAILABLE_CLOTHES:
                        self.show_centered_message("错误", f"未知时装ID: {clothes_id}", QMessageBox.Warning)
                        return True
                    items_list.append({"type": "clothes", "id": clothes_id})

            if not items_list:
                self.show_centered_message("错误", "物品列表不能为空", QMessageBox.Warning)
                return True

            # 解析有效期
            if expire_str:
                expire_time = parse_expire_time(expire_str)
                if expire_time is None:
                    self.show_centered_message("错误", "有效期格式错误，请使用 YYYY-MM-DD 或时长如 1d/1Y2M3D",
                                               QMessageBox.Warning)
                    return True
            else:
                expire_time = None

            # 验证目标用户
            all_codes = load_all_codes()
            if code in all_codes:
                self.show_centered_message("错误", "兑换码已存在", QMessageBox.Warning)
                return True

            target_identifier_str = None
            if user_spec and user_spec.strip().lower() != "none":
                try:
                    self.find_users_by_identifiers(user_spec)
                    target_identifier_str = user_spec
                except ValueError as e:
                    self.show_centered_message("错误", str(e), QMessageBox.Warning)
                    return True

            # 创建兑换码（固定 max_uses = 1）
            all_codes[code] = {
                "max_uses": 1,
                "used_count": 0,
                "created_by": self.current_user["username"],
                "created_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "target_user": target_identifier_str,
                "items": items_list,
                "expire_time": expire_time,
                "revoked": False,
                "revoked_users": [],
                "revoked_by": None,
                "revoked_time": None
            }
            save_all_codes(all_codes)

            # 记录日志
            history = self.current_user.get("redeem_history", [])
            history.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 创建兑换码 {code}")
            self.current_user["redeem_history"] = history
            self._save_current_user()

            self.show_centered_message("成功", f"兑换码 {code} 已创建", QMessageBox.Information)
            return True

        if cmd_line.startswith("set user "):
            pattern = r'set user\s+(\S+)\s+Admin$'
            match = re.match(pattern, cmd_line, re.IGNORECASE)
            if not match:
                self.show_centered_message("错误", "命令格式：/set user <标识> Admin", QMessageBox.Warning)
                return True
            target_identifier = match.group(1)
            target_user = self.find_user_by_identifier(target_identifier)
            if not target_user:
                self.show_centered_message("错误", f"未找到用户: {target_identifier}", QMessageBox.Warning)
                return True
            if target_user["uid"].lower().startswith("admin"):
                self.show_centered_message("错误", "目标用户已是管理员，无法重复设置", QMessageBox.Warning)
                return True
            old_uid = target_user.get("uid", "")
            digits = re.search(r'\d{9}$', old_uid)
            if digits:
                new_uid = f"Admin-{digits.group()}"
            else:
                rand_num = str(random.randint(0, 10 ** 9 - 1)).zfill(9)
                new_uid = f"Admin-{rand_num}"
            target_user["uid"] = new_uid
            self.save_user_data(target_user)
            history = self.current_user.get("redeem_history", [])
            history.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [管理员] 将用户 {target_identifier} 的UID改为 {new_uid}")
            self.current_user["redeem_history"] = history
            self._save_current_user()
            self.show_centered_message("成功", f"已将用户 {target_identifier} 的UID修改为 {new_uid}", QMessageBox.Information)
            return True

        if cmd_line.startswith("ban "):
            parts = cmd_line.split(maxsplit=2)
            if len(parts) < 2:
                self.show_centered_message("错误", "命令格式：/ban <标识>[,<标识2>...] [时长]", QMessageBox.Warning)
                return True
            identifiers_part = parts[1]
            duration_str = parts[2] if len(parts) > 2 else None
            try:
                target_users = self.find_users_by_identifiers(identifiers_part)
                if target_users is None:
                    self.show_centered_message("错误", "未指定有效目标用户", QMessageBox.Warning)
                    return True
            except ValueError as e:
                self.show_centered_message("错误", str(e), QMessageBox.Warning)
                return True
            current_uid = self.current_user.get("uid", "")
            is_current_admin = current_uid.lower().startswith("admin")
            for tu in target_users:
                if is_current_admin and tu["uid"].lower().startswith("admin") and tu["userid"] != self.current_user["userid"]:
                    self.show_centered_message("错误", f"不能封禁其他管理员用户: {tu['username']}", QMessageBox.Warning)
                    return True
            delta = None
            if duration_str:
                delta = parse_duration(duration_str)
                if delta is None:
                    self.show_centered_message("错误", "时长格式错误，示例：1Y6M15D（年Y/月M/日D）", QMessageBox.Warning)
                    return True
            success_list = []
            for tu in target_users:
                if delta:
                    until_date = datetime.now() + delta
                    tu["banned"] = True
                    tu["banned_until"] = until_date.isoformat()
                    self.save_user_data(tu)
                    success_list.append(f"{tu['username']} 至 {until_date.strftime('%Y-%m-%d')}")
                else:
                    tu["banned"] = True
                    tu["banned_until"] = None
                    self.save_user_data(tu)
                    success_list.append(f"{tu['username']} 永久")
            history = self.current_user.get("redeem_history", [])
            history.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [管理员] 封禁用户: {identifiers_part}，时长 {duration_str if duration_str else '永久'}")
            self.current_user["redeem_history"] = history
            self._save_current_user()
            self.show_centered_message("成功", f"已封禁用户:\n" + "\n".join(success_list), QMessageBox.Information)
            return True

        if cmd_line.startswith("unban "):
            parts = cmd_line.split(maxsplit=1)
            if len(parts) < 2:
                self.show_centered_message("错误", "命令格式：/unban <标识>[,<标识2>...]", QMessageBox.Warning)
                return True
            identifiers_part = parts[1]
            try:
                target_users = self.find_users_by_identifiers(identifiers_part)
                if target_users is None:
                    self.show_centered_message("错误", "未指定有效目标用户", QMessageBox.Warning)
                    return True
            except ValueError as e:
                self.show_centered_message("错误", str(e), QMessageBox.Warning)
                return True
            for tu in target_users:
                tu["banned"] = False
                tu["banned_until"] = None
                self.save_user_data(tu)
            history = self.current_user.get("redeem_history", [])
            history.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [管理员] 解封用户: {identifiers_part}")
            self.current_user["redeem_history"] = history
            self._save_current_user()
            self.show_centered_message("成功", f"已解封用户: {identifiers_part}", QMessageBox.Information)
            return True

        if cmd_line.startswith("revoke code "):
            pattern = r'revoke code\s+(\S+)(?:\s+for\s+(.+))?$'
            match = re.match(pattern, cmd_line, re.IGNORECASE)
            if not match:
                self.show_centered_message("错误", "命令格式：/revoke code <兑换码> [for <用户列表>]", QMessageBox.Warning)
                return True
            code = match.group(1)
            target = match.group(2) if match.group(2) else None
            self.revoke_code(code, target)
            return True

        if cmd_line.startswith("emo"):
            parts = cmd_line.split(maxsplit=1)
            target_str = parts[1].strip() if len(parts) > 1 else ""

            if target_str == "":
                self.persistent_state = "Discomfort"
                self.current_user["last_state"] = "Discomfort"
                self._save_current_user()
                self.changeToDiscomfort()
                self.show_centered_message("成功", "已进入 EMO 状态（下次启动仍为 EMO）", QMessageBox.Information)

            elif target_str.strip() == "@a":
                all_users = []
                for filename in os.listdir(USER_DATA_DIR):
                    if filename.endswith(".json"):
                        filepath = os.path.join(USER_DATA_DIR, filename)
                        with open(filepath, "r", encoding="utf-8") as f:
                            u = json.load(f)
                        all_users.append(u)
                for u in all_users:
                    u["last_state"] = "Discomfort"
                    self.save_user_data(u)
                self.show_centered_message("成功", "已设置所有用户下次启动进入 EMO 状态", QMessageBox.Information)

            else:
                try:
                    targets = self.find_users_by_identifiers(target_str)
                except ValueError as e:
                    self.show_centered_message("错误", str(e), QMessageBox.Warning)
                    return True
                for u in targets:
                    u["last_state"] = "Discomfort"
                    self.save_user_data(u)
                self.show_centered_message("成功", f"已设置 {len(targets)} 个用户下次启动进入 EMO 状态",
                                           QMessageBox.Information)

            return True

        if cmd_line.startswith("set "):
            pattern = r'set\s+(\w+)\s+(\d+)(?:\s+for\s+(.+))?$'
            match = re.match(pattern, cmd_line, re.IGNORECASE)
            if not match:
                self.show_centered_message("错误", "命令格式：/set <物品类型> <数量> [for <用户列表>]", QMessageBox.Warning)
                return True
            item_type = match.group(1).lower()
            amount = match.group(2)
            target = match.group(3) if match.group(3) else None
            if item_type == "credit":
                self.set_credit(amount, target)
            elif item_type == "cake":
                try:
                    int_amount = int(amount)
                except:
                    self.show_centered_message("错误", "数量错误", QMessageBox.Warning)
                    return True
                if target:
                    try:
                        target_users = self.find_users_by_identifiers(target)
                        for tu in target_users:
                            tu["balance"] = int_amount
                            self.save_user_data(tu)
                    except ValueError as e:
                        self.show_centered_message("错误", str(e), QMessageBox.Warning)
                else:
                    self.current_user["balance"] = int_amount
                    self._save_current_user()
                self.show_centered_message("成功", "已设置蛋糕卷数量", QMessageBox.Information)
            else:
                self.show_centered_message("错误", "未知物品类型", QMessageBox.Warning)
            return True

        self.show_centered_message("提示", "未知管理员命令", QMessageBox.Warning)
        return True

    def redeem_code(self):
        dialog = RedeemCodeDialog(self)
        self._redeem_dialog = dialog
        dialog.code_submitted.connect(self.handle_redeem_code)
        dialog.open()

    def handle_redeem_code(self, code):
        dialog = getattr(self, '_redeem_dialog', None)
        if dialog is None or not dialog.isVisible():
            return

        if not code:
            QMessageBox.warning(dialog, "提示", "请输入兑换码")
            return

        if code.startswith('/'):
            uid_prefix = self.current_user.get("uid", "").lower()
            is_admin = uid_prefix.startswith("admin")
            if is_admin:
                self.process_admin_command(code)
            else:
                if code.strip().lower() == '/help':
                    self.show_help()
                else:
                    QMessageBox.warning(dialog, "提示", "未知兑换码或权限不足")
            return

        all_codes = load_all_codes()
        redeemed = self.current_user.get("redeemed_codes", [])

        if code not in all_codes:
            QMessageBox.warning(dialog, "提示", "无效的兑换码！")
            return
        cinfo = all_codes[code]
        if cinfo.get("revoked"):
            QMessageBox.warning(dialog, "提示", "该兑换码已被管理员撤销")
            return
        if self.current_user["userid"] in cinfo.get("revoked_users", []):
            QMessageBox.warning(dialog, "提示", "您对该兑换码的使用资格已被撤销")
            return
        expire_time = cinfo.get("expire_time")
        if expire_time:
            try:
                expire_dt = datetime.fromisoformat(expire_time)
                if datetime.now() > expire_dt:
                    QMessageBox.warning(dialog, "提示", "该兑换码已过期")
                    return
            except:
                pass
        if code in redeemed and cinfo.get("max_uses", 1) == 1:
            QMessageBox.warning(dialog, "提示", "您已经使用过该兑换码！")
            return
        target_spec = cinfo.get("target_user")
        if target_spec:
            try:
                target_users = self.find_users_by_identifiers(target_spec)
                if target_users:
                    user_match = any(tu["userid"] == self.current_user["userid"] for tu in target_users)
                    if not user_match:
                        QMessageBox.warning(dialog, "提示", "未知兑换码")
                        return
            except:
                QMessageBox.warning(dialog, "提示", "兑换码配置错误")
                return
        if cinfo["max_uses"] != 0 and cinfo["used_count"] >= cinfo["max_uses"]:
            QMessageBox.warning(dialog, "提示", "该兑换码已失效（达到使用次数上限）")
            return

        items = []
        for item in cinfo.get("items", []):
            itype = item["type"]
            if itype == "cake":
                items.append({"type": "cake", "amount": item["amount"]})
            elif itype == "credit":
                items.append({"type": "credit", "amount": item["amount"]})
            elif itype == "clothes":
                items.append({"type": "clothes", "id": item["id"]})

        # 后续发邮件逻辑不变
        self.send_mail_to_user(self.current_user, "兑换码奖励",
                               f"成功使用兑换码 {code}，获得以下物品。", items)
        if cinfo["max_uses"] != 0:
            self.current_user["redeemed_codes"] = redeemed + [code]
        cinfo["used_count"] += 1
        save_all_codes(all_codes)
        history = self.current_user.get("redeem_history", [])
        history.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 使用兑换码 {code}")
        self.current_user["redeem_history"] = history
        self._save_current_user()

        QMessageBox.information(dialog, "成功", "兑换成功！物品已发送至邮箱，请查收。")

    def show_history(self):
        is_admin = self.current_user.get("uid", "").lower().startswith("admin")
        win = HistoryWindow(self.current_user, is_admin, self)
        win.open()

    def open_mailbox(self):
        mailbox_win = MailboxWindow(self, self)
        mailbox_win.exec_()

    # ---------- 动作方法 ----------
    def feed(self):
        balance = self.current_user.get("balance", 0)
        if balance <= 0:
            self.show_centered_message("提示", "橡木蛋糕卷不足，无法投喂！", QMessageBox.Warning)
            return
        self.current_user["balance"] = balance - 1
        self._save_current_user()

        self.last_animation_state = self.current_animation_state
        self.record_interaction(extra_seconds=10 * 60)

        if self.movie is None:
            return
        self.movie.stop()
        gif_path = None
        files = os.listdir(".")
        if 'Large' in files:
            gif_path = './assets/images/firefly/actions/eat/eat_Large.gif'
        elif 'small' in files:
            gif_path = './assets/images/firefly/actions/eat/eat_small.gif'
        elif 'normal' in files:
            gif_path = './assets/images/firefly/actions/eat/eat.gif'
        elif 'medium' in files:
            gif_path = './assets/images/firefly/actions/eat/eat_medium.gif'
        if gif_path and os.path.exists(gif_path):
            new_movie = QMovie(gif_path)
            self.label.setMovie(new_movie)
            self.movie = new_movie
            self.movie.start()
            QTimer.singleShot(5000, self.restore_previous_animation)
        else:
            self.restore_previous_animation()

    def heart(self):
        if self.movie is None:
            return
        self.last_animation_state = self.current_animation_state
        self.record_interaction(extra_seconds=2 * 60)
        self.movie.stop()
        gif_path = None
        files = os.listdir(".")
        if 'Large' in files:
            gif_path = './assets/images/firefly/actions/Love/Love_Large.gif'
        elif 'small' in files:
            gif_path = './assets/images/firefly/actions/Love/Love_small.gif'
        elif 'normal' in files:
            gif_path = './assets/images/firefly/actions/Love/Love.gif'
        elif 'medium' in files:
            gif_path = './assets/images/firefly/actions/Love/Love_medium.gif'
        if gif_path and os.path.exists(gif_path):
            new_movie = QMovie(gif_path)
            self.label.setMovie(new_movie)
            self.movie = new_movie
            self.movie.start()
            QTimer.singleShot(1300, self.restore_previous_animation)
        else:
            self.restore_previous_animation()

    def sleep(self):
        if self.anim_restore_timer:
            self.anim_restore_timer.stop()
            self.anim_restore_timer = None
        if self.movie is None:
            return
        self.last_animation_state = self.current_animation_state
        self.movie.stop()
        gif_path = None
        files = os.listdir(".")
        if 'Large' in files:
            gif_path = './assets/images/firefly/actions/sleep/sleep_Large.gif'
        elif 'small' in files:
            gif_path = './assets/images/firefly/actions/sleep/sleep_small.gif'
        elif 'normal' in files:
            gif_path = './assets/images/firefly/actions/sleep/sleep.gif'
        elif 'medium' in files:
            gif_path = './assets/images/firefly/actions/sleep/sleep_medium.gif'

        if gif_path and os.path.exists(gif_path):
            new_movie = QMovie(gif_path)
            self.label.setMovie(new_movie)
            self.movie = new_movie
            self.movie.start()

        self.current_animation_state = "Sleep"
        self.sleep_start_time = time.time()

    def restore_previous_animation(self):
        if self.last_animation_state == "Discomfort":
            self.changeToDiscomfort()
        else:
            self.changeToStandby()

    def changeToStandby(self):
        if self.movie is None:
            return
        self.movie.stop()
        files = os.listdir(".")
        if 'Large' in files:
            self.movie = QMovie('./assets/images/firefly/actions/Standby/Standby_Large.gif')
        elif 'small' in files:
            self.movie = QMovie('./assets/images/firefly/actions/Standby/Standby_small.gif')
        elif 'normal' in files:
            self.movie = QMovie('./assets/images/firefly/actions/Standby/Standby.gif')
        elif 'medium' in files:
            self.movie = QMovie('./assets/images/firefly/actions/Standby/Standby_medium.gif')
        self.label.setMovie(self.movie)
        self.movie.start()
        self.current_animation_state = "Standby"
        self.persistent_state = "Standby"
        if self.current_user:
            self.current_user["last_state"] = "Standby"
            self._save_current_user()

    def changeToDiscomfort(self):
        if self.movie is None:
            return
        self.movie.stop()
        files = os.listdir(".")
        if 'Large' in files:
            self.movie = QMovie('./assets/images/firefly/actions/Discomfort/Discomfort_Large.gif')
        elif 'small' in files:
            self.movie = QMovie('./assets/images/firefly/actions/Discomfort/Discomfort_small.gif')
        elif 'normal' in files:
            self.movie = QMovie('./assets/images/firefly/actions/Discomfort/Discomfort.gif')
        elif 'medium' in files:
            self.movie = QMovie('./assets/images/firefly/actions/Discomfort/Discomfort_medium.gif')
        self.label.setMovie(self.movie)
        self.movie.start()
        self.current_animation_state = "Discomfort"
        self.persistent_state = "Discomfort"
        if self.current_user:
            self.current_user["last_state"] = "Discomfort"
            self._save_current_user()

    def sing_and_dance(self):
        self.play_music()
        self.last_animation_state = self.current_animation_state
        self.movie.stop()
        gif_path = None
        files = os.listdir(".")
        if 'Large' in files:
            gif_path = './assets/images/firefly/actions/sing/sing_Large.gif'
        elif 'small' in files:
            gif_path = './assets/images/firefly/actions/sing/sing_small.gif'
        elif 'normal' in files:
            gif_path = './assets/images/firefly/actions/sing/sing.gif'
        elif 'medium' in files:
            gif_path = './assets/images/firefly/actions/sing/sing_medium.gif'
        if gif_path and os.path.exists(gif_path):
            new_movie = QMovie(gif_path)
            self.label.setMovie(new_movie)
            self.movie = new_movie
            self.movie.start()
            QTimer.singleShot(88000, self.restore_previous_animation)
        else:
            self.restore_previous_animation()

    def sing_and_dance2(self):
        self.play_music2()
        self.last_animation_state = self.current_animation_state
        self.movie.stop()
        gif_path = None
        files = os.listdir(".")
        if 'Large' in files:
            gif_path = './assets/images/firefly/actions/sing/sing_Large.gif'
        elif 'small' in files:
            gif_path = './assets/images/firefly/actions/sing/sing_small.gif'
        elif 'normal' in files:
            gif_path = './assets/images/firefly/actions/sing/sing.gif'
        elif 'medium' in files:
            gif_path = './assets/images/firefly/actions/sing/sing_medium.gif'
        if gif_path and os.path.exists(gif_path):
            new_movie = QMovie(gif_path)
            self.label.setMovie(new_movie)
            self.movie = new_movie
            self.movie.start()
            QTimer.singleShot(92000, self.restore_previous_animation)
        else:
            self.restore_previous_animation()

    def sing_and_dance3(self):
        self.play_music3()
        self.last_animation_state = self.current_animation_state
        self.movie.stop()
        gif_path = None
        files = os.listdir(".")
        if 'Large' in files:
            gif_path = './assets/images/firefly/actions/sing/sing_Large.gif'
        elif 'small' in files:
            gif_path = './assets/images/firefly/actions/sing/sing_small.gif'
        elif 'normal' in files:
            gif_path = './assets/images/firefly/actions/sing/sing.gif'
        elif 'medium' in files:
            gif_path = './assets/images/firefly/actions/sing/sing_medium.gif'
        if gif_path and os.path.exists(gif_path):
            new_movie = QMovie(gif_path)
            self.label.setMovie(new_movie)
            self.movie = new_movie
            self.movie.start()
            QTimer.singleShot(155000, self.restore_previous_animation)
        else:
            self.restore_previous_animation()

    def sing_and_dance4(self):
        self.play_music4()
        self.last_animation_state = self.current_animation_state
        self.movie.stop()
        gif_path = None
        files = os.listdir(".")
        if 'Large' in files:
            gif_path = './assets/images/firefly/actions/sing/sing_Large.gif'
        elif 'small' in files:
            gif_path = './assets/images/firefly/actions/sing/sing_small.gif'
        elif 'normal' in files:
            gif_path = './assets/images/firefly/actions/sing/sing.gif'
        elif 'medium' in files:
            gif_path = './assets/images/firefly/actions/sing/sing_medium.gif'
        if gif_path and os.path.exists(gif_path):
            new_movie = QMovie(gif_path)
            self.label.setMovie(new_movie)
            self.movie = new_movie
            self.movie.start()
            QTimer.singleShot(340000, self.restore_previous_animation)
        else:
            self.restore_previous_animation()

    def check_new(self):
        webbrowser.open("https://github.com/Jimhow-Gu/Firefly-Table-Pet/releases/tag/Firefly")

    def AI(self):
        def check_process_running(process_name):
            for process in psutil.process_iter(['name']):
                if process.info['name'] == process_name:
                    return True
            return False

        process_name = 'AI.exe'
        if not check_process_running(process_name):
            subprocess.Popen(["./tools/AI.exe"])

    def open_AI(self):
        def check_process_running(process_name):
            for process in psutil.process_iter(['name']):
                if process.info['name'] == process_name:
                    return True
            return False

        process_name = 'AI.exe'
        if not check_process_running(process_name):
            subprocess.Popen(["./tools/AI.exe"])

    def set_cursor(self, cursor_name):
        if self.current_file_name and os.path.exists(self.current_file_name):
            if not os.path.exists(cursor_name):
                os.rename(self.current_file_name, cursor_name)
            self.current_file_name = cursor_name

    def rename_file(self, new_name):
        if self.current_file_name and os.path.exists(self.current_file_name) and not os.path.exists(new_name):
            os.rename(self.current_file_name, new_name)
            self.current_file_name = new_name

    def set_default_cursor(self):
        self.setCursor(QCursor(Qt.ArrowCursor))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.draggable = True
            self.offset = event.pos()

    def mouseMoveEvent(self, event):
        if self.draggable:
            self.move(event.globalPos() - self.offset)
            self.movie.stop()
            files = os.listdir(".")
            for file in files:
                if 'Large' in file:
                    m = QMovie('./assets/images/firefly/actions/mention/mention_Large.gif')
                elif 'small' in file:
                    m = QMovie('./assets/images/firefly/actions/mention/mention_small.gif')
                elif 'normal' in file:
                    m = QMovie('./assets/images/firefly/actions/mention/mention.gif')
                elif 'medium' in file:
                    m = QMovie('./assets/images/firefly/actions/mention/mention_medium.gif')
            self.label.setMovie(m)
            m.start()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.draggable = False
            if self.movie:
                self.label.setMovie(self.movie)
                self.movie.start()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            try:
                pygame.mixer.music.load("./music/我将，点燃心海！.wav")
                pygame.mixer.music.set_volume(0.5)
                pygame.mixer.music.play()
            except Exception as e:
                print(f"双击播放失败: {e}")

    # ---------- 生日检测与欢迎 ----------
    def is_birthday_today(self):
        if not self.current_user:
            return False
        birthday_str = self.current_user.get("birthday")
        if not birthday_str:
            return False
        try:
            bd = datetime.strptime(birthday_str, "%Y-%m-%d")
            today = datetime.now()
            return (bd.month == today.month and bd.day == today.day)
        except:
            return False

    def has_birthday_greeted_this_year(self):
        if not self.current_user:
            return True
        last_year = self.current_user.get("last_birthday_greet_year")
        return last_year == datetime.now().year

    def send_birthday_mail(self):
        uid = self.current_user.get("uid", "").lower()
        if uid.startswith("admin"):
            greeting_name = "管理员"
        elif uid.startswith("trailblazer"):
            greeting_name = "开拓者"
        else:
            greeting_name = "用户"

        items = [
            {"type": "credit", "amount": 5200},
            {"type": "star_rail_ticket", "amount": 1}
        ]
        self.send_mail_to_user(
            self.current_user,
            "流萤的祝福",
            f"{greeting_name}，生日快乐！",
            items
        )
        # 记录今年已祝福
        self.current_user["last_birthday_greet_year"] = datetime.now().year
        self._save_current_user()

    def hi_music(self):
        def play_welcome():
            try:
                uid = self.current_user.get("uid", "") if self.current_user else ""
                last_state = self.current_user.get("last_state", "Standby")

                # 生日处理
                if self.is_birthday_today() and not self.has_birthday_greeted_this_year():
                    # 尝试播放生日音频
                    birthday_sound = None
                    if uid.lower().startswith("admin"):
                        birthday_sound = "music/管理员生日快乐.wav"
                    elif uid.lower().startswith("trailblazer"):
                        birthday_sound = "music/开拓者生日快乐.wav"
                    else:
                        birthday_sound = "music/生日快乐.wav"
                    if os.path.exists(birthday_sound):
                        pygame.mixer.music.load(birthday_sound)
                        pygame.mixer.music.set_volume(0.5)
                        pygame.mixer.music.play()
                    # 发送生日邮件
                    self.send_birthday_mail()
                    return  # 播放完生日语音后不再播放常规欢迎

                # 常规欢迎流程
                if last_state == "Discomfort":
                    if uid.lower().startswith("admin"):
                        sound_file = "music/Admin_back.wav"
                    elif uid.lower().startswith("trailblazer"):
                        sound_file = "music/Trailblazer_back.wav"
                    else:
                        sound_file = "music/User_back.wav"
                    if os.path.exists(sound_file):
                        pygame.mixer.music.load(sound_file)
                        pygame.mixer.music.set_volume(0.5)
                        pygame.mixer.music.play()
                        return

                if uid.lower().startswith("trailblazer"):
                    sound_file = "music/开拓者！欢迎回来！.wav"
                elif uid.lower().startswith("admin"):
                    sound_file = "music/你好，管理员！欢迎回来！.wav"
                else:
                    sound_file = "./music/我叫流萤，是鸢尾花家系的译者。.wav"
                if os.path.exists(sound_file):
                    pygame.mixer.music.load(sound_file)
                    pygame.mixer.music.set_volume(0.5)
                    pygame.mixer.music.play()
                else:
                    print(f"欢迎音乐文件不存在: {sound_file}")
            except Exception as e:
                print(f"播放欢迎音乐失败: {e}")

        QTimer.singleShot(500, play_welcome)

    def contextMenuEvent(self, event):
        current_cursor = self.cursor()
        QApplication.setOverrideCursor(current_cursor)
        try:
            menu = RoundedMenu(self)
            menu.setToolTipsVisible(True)
            action0 = QAction('Firefly_Win64_v4.3.2_G', self)
            action0.setDisabled(True)
            action1 = QAction('🍖 投喂', self)  # 添加 emoji
            action2 = QAction('💖 比心', self)  # 添加 emoji
            action3 = QAction('😴 睡觉', self)  # 添加 emoji
            action_new = QAction('🔄 检查更新', self)  # 添加 emoji
            action9 = QAction('🔧 更多功能', self)  # 添加 emoji
            action100 = QAction('💬 在线对话', self)  # 添加 emoji

            menu.addAction(action0)
            menu.addAction(action1)
            menu.addAction(action2)
            menu.addAction(action3)

            if self.current_animation_state == "Sleep":
                action4 = QAction('✨ 唤醒', self)  # 添加 emoji
                action4.triggered.connect(self.wake_up)
                menu.addAction(action4)

            action_mailbox = QAction('📬 邮箱', self)
            menu.addAction(action_mailbox)
            shop_action = QAction('🛒 商店', self)  # 添加 emoji
            shop_action.triggered.connect(self.open_shop)
            menu.addAction(shop_action)
            bag = RoundedMenu(menu)
            bag.setTitle("🎒 背包")  # 子菜单标题也可加 emoji
            bag.setToolTipsVisible(True)
            balance = self.current_user.get("balance", 0)
            credit = self.current_user.get("credit", 0)
            tickets = self.current_user.get("star_rail_tickets", 0)
            action_backpack = QAction(f'🍰 橡木蛋糕卷：{balance}个', self)
            action_backpack.setDisabled(True)
            action_backpack.setToolTip("流萤最爱吃的食物")
            bag.addAction(action_backpack)
            action_credit = QAction(f'💰 信用点：{credit}', self)
            action_credit.setDisabled(True)
            action_credit.setToolTip("用于商店购买物品")
            bag.addAction(action_credit)
            action_tickets = QAction(f'🎫 星铁专票：{tickets}张', self)
            action_tickets.setDisabled(True)
            action_tickets.setToolTip("来自列车的祝福")
            bag.addAction(action_tickets)
            menu.addMenu(bag)

            clothes_menu = RoundedMenu(menu)
            clothes_menu.setTitle("👗 时装")  # 子菜单标题加 emoji
            clothes_menu.setToolTipsVisible(True)
            owned = self.current_user.get("owned_clothes", ["normal"])
            for clothes_id, info in AVAILABLE_CLOTHES.items():
                action = QAction(info["name"], self)
                if clothes_id in owned:
                    action.triggered.connect(lambda checked, cid=clothes_id: self.apply_clothes(cid))
                else:
                    action.setEnabled(False)
                    action.setToolTip(info.get("description", "未拥有"))
                clothes_menu.addAction(action)
            menu.addMenu(clothes_menu)

            if self.is_signed_today():
                sign_action = menu.addAction("✅ 今日已签到")
                sign_action.setDisabled(True)
            else:
                sign_action = menu.addAction("📅 每日签到")
                sign_action.triggered.connect(self.sign_in)
            menu.addAction(sign_action)
            sing = RoundedMenu(menu)
            sing.setTitle("🎤 AI唱歌&二创")  # 添加 emoji
            sing.addAction("🎵 AI合唱-不眠之夜", self.sing_and_dance)
            sing.addAction("🎶 AI独唱-打上花火", self.sing_and_dance2)
            sing.addAction("🎙️ AI独唱-5:20AM", self.sing_and_dance3)
            sing.addAction("✨ 二创-Dream of Firefly", self.sing_and_dance4)
            sing.addAction("⏹️ 停止音乐", self.stop_music)
            menu.addMenu(sing)

            mouse_GUI = RoundedMenu(menu)
            mouse_GUI.setTitle("🐭 更改桌宠大小")  # 添加 emoji
            mouse_GUI.addAction("🔍 更改：大号", self.change_GUI_to_Large)
            mouse_GUI.addAction("🖥️ 更改：默认", self.change_GUI_to_normal)
            mouse_GUI.addAction("📏 更改：中号", self.change_GUI_to_medium)
            mouse_GUI.addAction("🔬 更改：小号", self.change_GUI_to_small)
            menu.addMenu(mouse_GUI)

            mouse = RoundedMenu(menu)
            mouse.setTitle("🖱️ 修改指针")  # 添加 emoji
            mouse.addAction("🪲 流萤指针", lambda: self.set_cursor_style("Firefly"))
            mouse.addAction("🤖 萨姆指针", lambda: self.set_cursor_style("Sam"))
            mouse.addAction("🚫 停用指针", lambda: self.set_cursor_style("None"))
            menu.addMenu(mouse)

            menu.addAction(action9)
            menu.addAction(action_new)
            menu.addAction(action100)

            action_redeem = QAction('🎟️使用兑换码', self)  # 添加 emoji
            action_history = QAction('📋 兑换明细', self)  # 添加 emoji
            menu.addAction(action_redeem)
            menu.addAction(action_history)

            user_info = QAction(f"👤当前登录：{self.current_user['username']} (UID:{self.current_user['uid']})", self)
            user_info.setDisabled(True)
            menu.addAction(user_info)

            exit_all_action = QAction('🚪 退出桌宠', self)  # 添加 emoji
            exit_all_action.triggered.connect(self.show_exit_dialog)
            menu.addAction(exit_all_action)

            # 连接信号（保持不变）
            action1.triggered.connect(self.feed)
            action2.triggered.connect(self.heart)
            action3.triggered.connect(self.sleep)
            action9.triggered.connect(self.open_settings)
            action_new.triggered.connect(self.check_new)
            action100.triggered.connect(self.open_AI)
            action_redeem.triggered.connect(self.redeem_code)
            action_history.triggered.connect(self.show_history)
            action_mailbox.triggered.connect(self.open_mailbox)

            pixmap = QPixmap('mouse/Firefly/p1.gif') if os.path.exists('mouse/Firefly/p1.gif') else QPixmap(16, 16)
            cursor = QCursor(pixmap)
            menu.setCursor(cursor)
            menu.exec_(event.globalPos())
        finally:
            QApplication.restoreOverrideCursor()

    def wake_up(self):
        if self.anim_restore_timer and self.anim_restore_timer.isActive():
            self.anim_restore_timer.stop()
        self.anim_restore_timer = None

        self.sleep_start_time = None

        last_state = self.current_user.get("last_state", "Standby") if self.current_user else "Standby"

        if last_state == "Discomfort":
            QTimer.singleShot(50, self._do_wake_up_discomfort)
        else:
            QTimer.singleShot(50, self._do_wake_up_standby)

        if hasattr(self, 'wake_action_tray') and self.wake_action_tray:
            QTimer.singleShot(150, lambda: self.wake_action_tray.setVisible(False))

    def _do_wake_up_standby(self):
        self.changeToStandby()
        self.record_interaction()

    def _do_wake_up_discomfort(self):
        self.changeToDiscomfort()

    def create_menu(self):
        menu = RoundedMenu()
        menu.setToolTipsVisible(True)
        fuck_Manthe = menu.addAction("Firefly_Win64_v4.3.2_G")
        fuck_Manthe.setDisabled(True)
        feed_action = menu.addAction("🍖 投喂")
        love_action = menu.addAction("💖 比心")
        mailbox_action = menu.addAction("📬 邮箱")
        mailbox_action.triggered.connect(self.open_mailbox)

        if self.is_signed_today():
            sign_action = menu.addAction("✅ 今日已签到")
            sign_action.setDisabled(True)
        else:
            sign_action = menu.addAction("📅 每日签到")
            sign_action.triggered.connect(self.sign_in)

        menu.addAction("🔧 更多功能", self.open_settings_tool)
        menu.addAction("🔄 检查更新", self.check_new)
        menu.addAction("💬 在线对话", self.AI)
        redeem_action = menu.addAction("🎟️使用兑换码")
        redeem_action.triggered.connect(self.redeem_code)
        history_action = menu.addAction("📋 兑换明细")
        history_action.triggered.connect(self.show_history)
        user_info = menu.addAction(f"👤当前登录：{self.current_user['username']} (UID:{self.current_user['uid']})")
        user_info.setDisabled(True)
        exit_all_action = menu.addAction("🚪 退出桌宠")
        exit_all_action.triggered.connect(self.show_exit_dialog)
        feed_action.triggered.connect(self.feed)
        love_action.triggered.connect(self.heart)
        self.tray_icon.setContextMenu(menu)
        self.set_default_cursor()
        self.tray_icon.show()

    def logout(self):
        self.current_user["last_state"] = self.persistent_state
        self._save_current_user()
        self.current_user = None
        self.hide()
        self.tray_icon.setVisible(False)
        self.show_login_again()

    def show_login_again(self):
        login_win = LoginWindow()
        login_win.login_success.connect(self.on_login_success)
        login_win.open()

    def on_login_success(self, user_data):
        self.current_user = user_data
        self.show()
        self.tray_icon.setVisible(True)
        self.create_menu()
        self.apply_cursor_style()
        self.apply_pet_size()
        try:
            self.hi_music()
        except:
            pass

    def closeEvent(self, event):
        self.firefly._save_current_user()
        super().closeEvent(event)

    def kill_self_and_children(self):
        current_pid = os.getpid()
        current_process = psutil.Process(current_pid)
        try:
            for child in current_process.children(recursive=True):
                try:
                    child.kill()
                except:
                    pass
            current_process.kill()
        except:
            sys.exit()

    def out_win(self):
        if self.current_user:
            self.current_user["last_state"] = self.persistent_state
            pos = self.pos()
            self.current_user["last_x"] = pos.x()
            self.current_user["last_y"] = pos.y()
            self._save_current_user()
        try:
            subprocess.Popen(["./tools/kill_process.exe"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except:
            pass
        self.kill_self_and_children()


# ====================== 自动登录检查 ======================
def auto_login_check():
    if not os.path.exists(USER_CONFIG):
        return None
    try:
        with open(USER_CONFIG, encoding="utf-8") as f:
            config = json.load(f)
        if config.get("remember") and config.get("userid") and config.get("password"):
            userid = config["userid"]
            pwd = config["password"]
            user_path = os.path.join(USER_DATA_DIR, f"{userid}.json")
            if os.path.exists(user_path):
                with open(user_path, encoding="utf-8") as f:
                    user_data = json.load(f)
                if user_data["password"] == pwd:
                    user_data = ensure_user_fields(user_data, user_path)
                    banned_until = user_data.get("banned_until")
                    if banned_until:
                        try:
                            until_date = datetime.fromisoformat(banned_until)
                            if datetime.now() < until_date:
                                if os.path.exists(USER_CONFIG):
                                    os.remove(USER_CONFIG)
                                return None
                            else:
                                user_data["banned"] = False
                                user_data["banned_until"] = None
                                with open(user_path, "w", encoding="utf-8") as f:
                                    json.dump(user_data, f, ensure_ascii=False, indent=2)
                        except:
                            pass
                    if user_data.get("banned"):
                        if os.path.exists(USER_CONFIG):
                            os.remove(USER_CONFIG)
                        return None
                    return user_data
    except:
        pass
    return None


# ====================== 主程序 ======================
if __name__ == "__main__":
    firefly = None
    app = QApplication(sys.argv)
    transparent_pixmap = QPixmap(1, 1)
    transparent_pixmap.fill(Qt.transparent)
    app.setWindowIcon(QIcon(transparent_pixmap))
    app.setQuitOnLastWindowClosed(False)

    font_path = "./assets/font/HarmonyOS_Sans_SC_Bold.ttf"
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_families = QFontDatabase.applicationFontFamilies(font_id)
            if font_families:
                harmony_font = QFont(font_families[0])
                harmony_font.setPointSize(10)
                app.setFont(harmony_font)

    pygame.mixer.init()

    current_user = auto_login_check()

    if current_user:
        # 自动登录：直接将实例附加到 app 上，无需 global
        app.firefly = Firefly(user_data=current_user)
        app.firefly.init_tray_icon()
        app.firefly.create_menu()
        app.firefly.hi_music()
        app.firefly.show()
        app.firefly.restore_last_position()
    else:
        login_win = LoginWindow()


        def on_login_success(user_data):
            # 回调函数内，同样附加到 app 上
            app.firefly = Firefly(user_data=user_data)
            app.firefly.init_tray_icon()
            app.firefly.create_menu()
            app.firefly.hi_music()
            app.firefly.show()
            app.firefly.restore_last_position()


        login_win.login_success.connect(on_login_success)
        login_win.open()

    sys.exit(app.exec_())
