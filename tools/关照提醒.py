from win10toast import ToastNotifier

T=ToastNotifier()
# 显示一个通知
T.show_toast("流萤桌宠", "萤宝不开心了，给她投喂或陪她玩玩吧！",
                   '../assets/images/firefly/Sadness/abandoned.ico',3)
