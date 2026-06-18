"""research — general-purpose research assistant (read-only, offline-safe).

Live web search comes from a host-mounted tool (e.g. anysearch); this CLI
structures the inquiry and is dependency-free.
"""
import argparse
import sys

DOC = """research — usage:
  research_cli.py doc               show this help
  research_cli.py outline <topic>   structured research outline for a topic

For live search, mount a search tool (e.g. anysearch) via the host. This CLI is
offline-safe and never performs side-effecting operations.
"""

_ANGLES = [
    ("背景与定义", "这个主题是什么？核心概念、边界、为什么重要。"),
    ("现状与趋势", "最新进展、数据、近 12 个月的变化。"),
    ("关键参与者", "主要项目 / 公司 / 人物及其定位。"),
    ("证据与来源", "权威来源、原始数据、可复核的事实。"),
    ("争议与风险", "分歧点、未解问题、潜在偏差。"),
    ("结论与建议", "基于证据的结论与可执行的下一步。"),
]


def _outline(topic):
    print(f"# 研究提纲：{topic}\n")
    for i, (title, hint) in enumerate(_ANGLES, 1):
        print(f"{i}. **{title}** — {hint}")
    print("\n方法：每一节先检索再交叉验证，标注来源；不确定的不臆造。")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="research_cli.py", add_help=False)
    parser.add_argument("command", nargs="?", default="doc")
    parser.add_argument("topic", nargs="*", default=[])
    args, _ = parser.parse_known_args(argv)

    if args.command == "doc":
        print(DOC)
        return 0
    if args.command == "outline":
        topic = " ".join(args.topic) or "（未指定主题）"
        return _outline(topic)
    sys.stderr.write(f"unknown command: {args.command}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
