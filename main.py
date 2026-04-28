import argparse
from pathlib import Path
import sys

from fcatbot.__main__ import Bot


        

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="fcatbot", description="Fcatbot CLI：启动 Bot。"
    )
    sub = parser.add_subparsers(dest="cmd", help="子命令")

    p_start = sub.add_parser("start", help="启动 Bot")
    p_start.add_argument("-u", "--url", required=True, help="WebSocket 地址")
    p_start.add_argument("-t", "--token", help="鉴权 token")
    p_start.add_argument("-p", "--plugin-dir", type=Path, help="额外插件目录")
    p_start.add_argument("--data-dir", type=Path, default="data", help="数据目录")
    p_start.add_argument("--debug", action="store_true", help="调试模式")

    args = parser.parse_args()

    if args.cmd == "start":
        bot = Bot(
            root_id=0,
            url=args.url,
            token=args.token,
            plugin_dir=args.plugin_dir,
            data_dir=args.data_dir,
            debug=args.debug,
        )
        try:
            bot.run()
        except KeyboardInterrupt:
            sys.exit(0)
    else:
        parser.print_help()