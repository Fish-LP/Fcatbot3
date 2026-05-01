from fcatbot.utils.color import Color


class LogFormats:
    """日志格式系统 - 提供多种实用风格"""

    # ================ 简洁实用风格 ================

    @staticmethod
    def simple(group_id, nick, uid, msg, group_name=None):
        """极简风格 - 最高效"""
        if group_id:
            return (
                f"{Color.Green}{group_name or f'G{group_id}'}{Color.Reset} | "
                f"{Color.Yellow}{nick}{Color.Gray}({uid}){Color.Reset}: {msg}"
            )
        return (
            f"{Color.Magenta}PM{Color.Reset} | "
            f"{Color.Yellow}{nick}{Color.Gray}({uid}){Color.Reset}: {Color.Cyan}{msg}{Color.Reset}"
        )

    @staticmethod
    def tag(group_id, nick, uid, msg, group_name=None):
        """标签风格 - 清晰明确"""
        if group_id:
            return (
                f"{Color.Gray}[{Color.Green}GROUP{Color.Gray}] "
                f"{Color.Blue}{group_name}{Color.Gray}: "
                f"{Color.Yellow}{nick}{Color.Gray}[{uid}]{Color.Reset} » {msg}"
            )
        return (
            f"{Color.Gray}[{Color.Magenta}PRIVATE{Color.Gray}] "
            f"{Color.Yellow}{nick}{Color.Gray}[{uid}]{Color.Reset} » {Color.Cyan}{msg}{Color.Reset}"
        )

    # ================ 专业风格 ================

    @staticmethod
    def professional(group_id, nick, uid, msg, group_name=None):
        """专业风格 - 适合监控"""
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S")

        if group_id:
            return (
                f"{Color.Gray}{timestamp} {Color.Green}[GRP]{Color.Reset} "
                f"{Color.White}{group_name:<15} {Color.Yellow}{nick:<10} "
                f"{Color.Gray}({uid}){Color.Reset} : {msg}"
            )
        return (
            f"{Color.Gray}{timestamp} {Color.Magenta}[PVT]{Color.Reset} "
            f"{Color.Yellow}{nick:<10} {Color.Gray}({uid}){Color.Reset} : {Color.Cyan}{msg}{Color.Reset}"
        )

    @staticmethod
    def network(group_id, nick, uid, msg, group_name=None):
        """网络风格 - 类似网络包格式"""
        if group_id:
            return (
                f"{Color.Cyan}GROUP:{Color.Green}{group_name} "
                f"{Color.Gray}[ID:{group_id}] {Color.Yellow}{nick} "
                f"{Color.Gray}<{uid}>{Color.White} > {msg}{Color.Reset}"
            )
        return (
            f"{Color.Magenta}PRIVATE {Color.Yellow}{nick} "
            f"{Color.Gray}<{uid}>{Color.White} >> {Color.Cyan}{msg}{Color.Reset}"
        )

    # ================ 开发调试风格 ================

    @staticmethod
    def debug(group_id, nick, uid, msg, group_name=None):
        """调试风格 - 详细信息"""
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        if group_id:
            return (
                f"{Color.Gray}{timestamp} | "
                f"{Color.Blue}Type:Group{Color.Reset} | "
                f"{Color.Green}Name:{group_name}{Color.Reset} | "
                f"{Color.Yellow}User:{nick}{Color.Reset} | "
                f"{Color.Cyan}UID:{uid}{Color.Reset} | "
                f"{Color.White}Msg:{msg}{Color.Reset}"
            )
        return (
            f"{Color.Gray}{timestamp} | "
            f"{Color.Magenta}Type:Private{Color.Reset} | "
            f"{Color.Yellow}User:{nick}{Color.Reset} | "
            f"{Color.Cyan}UID:{uid}{Color.Reset} | "
            f"{Color.Green}Msg:{msg}{Color.Reset}"
        )

    @staticmethod
    def minimal(group_id, nick, uid, msg, group_name=None):
        """最小化风格 - 最少字符"""
        if group_id:
            return f"{Color.Green}G{Color.Reset} {nick}: {msg}"
        return f"{Color.Magenta}P{Color.Reset} {nick}: {msg}"

    # ================ 层次结构风格 ================

    @staticmethod
    def hierarchical(group_id, nick, uid, msg, group_name=None):
        """层次结构风格 - 适合大量消息"""
        if group_id:
            return (
                f"{Color.Cyan}└─ {Color.Green}{group_name}{Color.Reset}\n"
                f"    {Color.Yellow}├─ {nick}{Color.Gray} ({uid}){Color.Reset}\n"
                f"    {Color.White}└─ {msg}{Color.Reset}"
            )
        return (
            f"{Color.Magenta}├─ {Color.Yellow}{nick}{Color.Gray} ({uid}){Color.Reset}\n"
            f"{Color.Magenta}└─ {Color.Cyan}{msg}{Color.Reset}"
        )

    @staticmethod
    def segment(group_id, nick, uid, msg, group_name=None):
        """分段风格 - 视觉分隔"""
        if group_id:
            return (
                f"{Color.Cyan}╞ {Color.Green}{group_name} {Color.Gray}[{group_id}]{Color.Reset}\n"
                f"{Color.Cyan}╞ {Color.Yellow}{nick} {Color.Gray}<{uid}>{Color.Reset}\n"
                f"{Color.Cyan}╰─ {Color.White}{msg}{Color.Reset}"
            )
        return (
            f"{Color.Magenta}╞ {Color.Yellow}{nick} {Color.Gray}<{uid}>{Color.Reset}\n"
            f"{Color.Magenta}╰─ {Color.Cyan}{msg}{Color.Reset}"
        )

    # ================ 数据表格风格 ================

    @staticmethod
    def table(group_id, nick, uid, msg, group_name=None):
        """表格风格 - 对齐美观"""
        if group_id:
            return (
                f"{Color.Cyan}│ {Color.Green}{str(group_name)[:20]:<20} "
                f"{Color.Yellow}│ {nick[:12]:<12} "
                f"{Color.Blue}│ {uid:<10} "
                f"{Color.White}│ {msg[:40]}{Color.Reset}"
            )
        return (
            f"{Color.Magenta}│ {Color.Yellow}{'Private':<20} "
            f"{Color.Yellow}│ {nick[:12]:<12} "
            f"{Color.Cyan}│ {uid:<10} "
            f"{Color.Green}│ {msg[:40]}{Color.Reset}"
        )

    @staticmethod
    def table_header():
        """表格标题"""
        return (
            f"{Color.Cyan}├{'─'*80}┤{Color.Reset}\n"
            f"{Color.Cyan}│ {Color.White}{'Source':<20} {'User':<12} {'ID':<10} {'Message':<38}{Color.Cyan} │{Color.Reset}\n"
            f"{Color.Cyan}├{'─'*80}┤{Color.Reset}"
        )

    # ================ 状态机风格 ================

    @staticmethod
    def state_machine(group_id, nick, uid, msg, group_name=None):
        """状态机风格 - 显示处理流程"""
        if group_id:
            return (
                f"{Color.Gray}[RECV] {Color.Green}[GROUP] "
                f"{Color.White}← {Color.Yellow}{nick} "
                f"{Color.Gray}({uid}) {Color.White}@ {Color.Cyan}{group_name}"
                f"{Color.Gray} → {Color.White}{msg[:50]}...{Color.Reset}"
            )
        return (
            f"{Color.Gray}[RECV] {Color.Magenta}[PRIVATE] "
            f"{Color.White}← {Color.Yellow}{nick} "
            f"{Color.Gray}({uid}){Color.Gray} → {Color.Cyan}{msg[:50]}...{Color.Reset}"
        )

    # ================ 通信协议风格 ================

    @staticmethod
    def protocol(group_id, nick, uid, msg, group_name=None):
        """协议风格 - 类似网络协议格式"""
        msg_len = len(str(msg))
        if group_id:
            return (
                f"{Color.Gray}[MESSAGE]{Color.Reset}\n"
                f"{Color.Blue}  TYPE:   GROUP{Color.Reset}\n"
                f"{Color.Green}  FROM:   {nick}{Color.Reset}\n"
                f"{Color.Cyan}  UID:    {uid}{Color.Reset}\n"
                f"{Color.Yellow}  GROUP:  {group_name}{Color.Reset}\n"
                f"{Color.White}  LENGTH: {msg_len}{Color.Reset}\n"
                f"{Color.Magenta}  DATA:   {msg[:60]}{Color.Reset}"
            )
        return (
            f"{Color.Gray}[MESSAGE]{Color.Reset}\n"
            f"{Color.Blue}  TYPE:   PRIVATE{Color.Reset}\n"
            f"{Color.Green}  FROM:   {nick}{Color.Reset}\n"
            f"{Color.Cyan}  UID:    {uid}{Color.Reset}\n"
            f"{Color.White}  LENGTH: {msg_len}{Color.Reset}\n"
            f"{Color.Magenta}  DATA:   {msg[:60]}{Color.Reset}"
        )

    # ================ 现代化风格 ================

    @staticmethod
    def modern(group_id, nick, uid, msg, group_name=None):
        """现代风格 - 简洁美观"""
        if group_id:
            return (
                f"{Color.Reset}{Color.Green}{group_name} "
                f"{Color.Gray}• {Color.Yellow}{nick} "
                f"{Color.Gray}({uid}){Color.Cyan} ▸ {Color.Reset}{msg}{Color.Reset}"
            )
        return (
            f"{Color.Reset}{Color.Yellow}{nick} "
            f"{Color.Gray}({uid}){Color.Magenta} ▸ {Color.Reset}{msg}{Color.Reset}"
        )

    @staticmethod
    def compact(group_id, nick, uid, msg, group_name=None):
        """紧凑风格 - 节省空间"""
        if group_id:
            return f"{Color.Green}G{Color.Reset}:{Color.Yellow}{nick[:6]}{Color.Reset}:{msg[:40]}"
        return f"{Color.Magenta}P{Color.Reset}:{Color.Yellow}{nick[:6]}{Color.Reset}:{msg[:40]}"

    # ================ 特殊场景风格 ================

    @staticmethod
    def highlight(group_id, nick, uid, msg, group_name=None, highlight_words=None):
        """高亮风格 - 关键词高亮"""
        if highlight_words is None:
            highlight_words = []

        highlighted_msg = str(msg)
        for word in highlight_words:
            if word in highlighted_msg:
                highlighted_msg = highlighted_msg.replace(
                    word, f"{Color.Red}{word}{Color.Reset}"
                )

        if group_id:
            return (
                f"{Color.Green}⚠ {group_name}{Color.Reset} | "
                f"{Color.Yellow}{nick}{Color.Reset} | {highlighted_msg}"
            )
        return (
            f"{Color.Magenta}⚠ PRIVATE{Color.Reset} | "
            f"{Color.Yellow}{nick}{Color.Reset} | {highlighted_msg}"
        )

    @staticmethod
    def priority(group_id, nick, uid, msg, group_name=None, priority="NORMAL"):
        """优先级风格 - 根据重要性显示"""
        priority_colors = {
            "HIGH": Color.Red,
            "MEDIUM": Color.Yellow,
            "NORMAL": Color.Green,
            "LOW": Color.Blue,
        }
        color = priority_colors.get(priority, Color.White)

        if group_id:
            return (
                f"{color}[{priority}] {Color.Green}{group_name}{Color.Reset} | "
                f"{Color.Yellow}{nick}{Color.Reset}: {msg}"
            )
        return (
            f"{color}[{priority}] {Color.Magenta}PRIVATE{Color.Reset} | "
            f"{Color.Yellow}{nick}{Color.Reset}: {msg}"
        )


# ================ 风格预览函数 ================
def preview_all_styles():
    """预览所有日志风格"""
    print(f"{Color.White}{Color.Bold}=== 日志风格预览 ==={Color.Reset}\n")

    test_cases = [
        ("群聊消息示例", "User123", 10001, "这是一个测试消息", "测试群组"),
        ("私聊消息示例", "Friend456", 20002, "你好，这是一个私聊测试", None),
    ]

    styles = [
        ("simple", "极简风格"),
        ("tag", "标签风格"),
        ("professional", "专业风格"),
        ("network", "网络风格"),
        ("debug", "调试风格"),
        ("minimal", "最小化风格"),
        ("hierarchical", "层次结构风格"),
        ("segment", "分段风格"),
        ("table", "表格风格"),
        ("state_machine", "状态机风格"),
        ("protocol", "协议风格"),
        ("modern", "现代风格"),
        ("compact", "紧凑风格"),
    ]

    for style_name, style_desc in styles:
        print(f"{Color.Cyan}{style_desc} ({style_name}):{Color.Reset}")

        for case_name, nick, uid, msg, group_name in test_cases:
            if group_name:
                log_text = getattr(LogFormats, style_name)(
                    123, nick, uid, msg, group_name
                )
            else:
                log_text = getattr(LogFormats, style_name)(None, nick, uid, msg)

            print(f"  {log_text}")

        print()


# 可以运行预览
if __name__ == "__main__":
    preview_all_styles()
