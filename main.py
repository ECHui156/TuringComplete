"""
Turing Complete - terminal app entry point
==========================================

This file is responsible for:
1) initializing the curses main UI;
2) maintaining an extensible game registry;
3) dispatching `stdscr` control to selected game modules;
4) restoring terminal state safely after a sub-game exits.

Design goals:
- avoid large if-elif chains when adding games;
- defensively handle curses context switching to reduce UI crashes.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional


if TYPE_CHECKING:
	import curses as curses_typing
	CursesWindow = curses_typing.window
else:
	CursesWindow = Any


def _bootstrap_curses() -> tuple[object | None, str | None]:
	"""加载 curses；在 Windows 下若缺失则尝试自动安装 windows-curses。

	返回：
	- (curses_module, None) 表示可用；
	- (None, error_message) 表示不可用并携带原因。
	"""
	try:
		import curses as loaded_curses
		return loaded_curses, None
	except ModuleNotFoundError as first_err:
		# Windows 平台的标准 Python 默认不内置 _curses，需要 windows-curses 适配包。
		if os.name == "nt":
			try:
				subprocess.check_call(
					[sys.executable, "-m", "pip", "install", "windows-curses"],
					stdout=subprocess.DEVNULL,
					stderr=subprocess.DEVNULL,
				)
				import curses as loaded_curses
				return loaded_curses, None
			except Exception as install_err:
				return None, (
					"当前 Python 环境缺少 curses 支持，且自动安装 windows-curses 失败。"
					f" 原始错误: {first_err}; 安装错误: {install_err}"
				)

		return None, f"当前 Python 环境缺少 curses 支持: {first_err}"


# 全局加载（后续函数都使用该对象）。
curses, CURSES_ERROR = _bootstrap_curses()


# -----------------------------
# 1) 游戏描述与注册中心
# -----------------------------


@dataclass(frozen=True)
class GameSpec:
	"""游戏元信息。

	字段说明：
	- `key`: 菜单按键（例如 '1'）。
	- `title`: 菜单展示名称（例如 '康威生命游戏'）。
	- `module`: 目标模块名（例如 'game_of_life'）。
	- `entry`: 模块中的统一入口函数名（默认 'run'）。
	"""

	key: str
	title: str
	module: str
	entry: str = "run"


class GameRegistry:
	"""统一游戏注册表。

	这是核心扩展点：
	- `register(...)`：注册一个游戏；
	- `list_menu_items()`：输出可用于渲染菜单的数据；
	- `resolve_runner(...)`：按 key 动态加载并返回游戏入口函数。

	未来扩展时，不需要在主循环中新增 if-elif，仅需注册游戏即可。
	"""

	def __init__(self) -> None:
		self._games: Dict[str, GameSpec] = {}

	def register(self, spec: GameSpec) -> None:
		"""注册一个游戏，若 key 冲突则抛错。"""
		if spec.key in self._games:
			raise ValueError(f"菜单键位冲突: {spec.key}")
		self._games[spec.key] = spec

	def list_menu_items(self) -> list[GameSpec]:
		"""按 key 排序返回已注册游戏。"""
		return [self._games[k] for k in sorted(self._games.keys())]

	def resolve_runner(self, key: str) -> Optional[Callable[[CursesWindow], None]]:
		"""根据 key 解析并返回游戏入口函数。

		返回值：
		- 若 key 无效，返回 None；
		- 若存在，动态 import 模块并读取入口函数。
		"""
		spec = self._games.get(key)
		if spec is None:
			return None

		# 动态导入：实现“模块可插拔”。
		module = importlib.import_module(spec.module)
		runner = getattr(module, spec.entry, None)
		if not callable(runner):
			raise AttributeError(
				f"模块 {spec.module} 缺少可调用入口 `{spec.entry}(stdscr)`"
			)
		return runner


def build_registry() -> GameRegistry:
	"""构建并返回默认注册表。"""
	registry = GameRegistry()

	# 当前版本仅注册一个游戏：生命游戏。
	registry.register(
		GameSpec(
			key="1",
			title="Conway's Game of Life",
			module="game_of_life",
			entry="run",
		)
	)

	# 未来新增游戏时，在这里追加 register(...) 即可。
	return registry


# -----------------------------
# 2) curses 绘制与安全辅助函数
# -----------------------------


def safe_addstr(stdscr: CursesWindow, y: int, x: int, text: str, attr: int = 0) -> None:
	"""安全写字符串。

	curses 在写到边界外时会抛 `curses.error`，这里统一吞掉，
	保证终端尺寸较小/动态变化时不至于直接崩溃。
	"""
	try:
		stdscr.addstr(y, x, text, attr)
	except curses.error:
		pass


def reset_main_screen_state(stdscr: CursesWindow) -> None:
	"""恢复主菜单期望的 curses 状态。

	子游戏可能改动：
	- `nodelay/timeout`
	- 光标可见性
	- keypad 等

	回到主菜单前统一重置，确保菜单交互稳定。
	"""
	stdscr.nodelay(False)
	stdscr.timeout(-1)
	stdscr.keypad(True)
	try:
		curses.curs_set(0)
	except curses.error:
		# 某些终端不支持修改光标形态。
		pass


def draw_splash(stdscr: CursesWindow) -> None:
	"""绘制启动页。"""
	stdscr.clear()
	h, w = stdscr.getmaxyx()
	title = "Turing Complete"
	subtitle = "Terminal Playground for Turing-Complete Systems"
	hint = "Press any key to open the main menu"

	safe_addstr(stdscr, max(0, h // 2 - 1), max(0, (w - len(title)) // 2), title, curses.A_BOLD)
	safe_addstr(stdscr, max(0, h // 2), max(0, (w - len(subtitle)) // 2), subtitle)
	safe_addstr(stdscr, max(0, h // 2 + 2), max(0, (w - len(hint)) // 2), hint, curses.A_DIM)
	stdscr.refresh()
	stdscr.getch()


def draw_menu(stdscr: CursesWindow, registry: GameRegistry, message: str = "") -> None:
	"""渲染主菜单。"""
	stdscr.clear()
	h, w = stdscr.getmaxyx()

	# 标题区
	safe_addstr(stdscr, 1, 2, "=== Turing Complete ===", curses.A_BOLD)
	safe_addstr(stdscr, 2, 2, "Select a system/game:", curses.A_UNDERLINE)

	# 动态菜单区：遍历注册表，而不是硬编码 if-elif。
	line = 4
	for spec in registry.list_menu_items():
		safe_addstr(stdscr, line, 4, f"{spec.key}. {spec.title}")
		line += 1

	# 固定退出项（也可后续改成注册项）。
	safe_addstr(stdscr, line, 4, "0. Exit")
	line += 2

	safe_addstr(stdscr, line, 2, "Enter a number and press Enter, or press a digit key directly.", curses.A_DIM)

	if message:
		safe_addstr(stdscr, min(h - 2, line + 2), 2, message, curses.A_BOLD)

	safe_addstr(stdscr, h - 1, 2, "Tip: Press Q in a game to return to the main menu.", curses.A_DIM)
	stdscr.refresh()


def read_menu_choice(stdscr: CursesWindow) -> str:
	"""读取菜单选择。

	交互策略：
	- 若用户直接按数字键，立即返回；
	- 若用户输入文本后回车，返回首字符（兼容输入 "1"、"0"）。
	"""
	key = stdscr.getch()

	# 直接数字键（主路径）。
	if ord("0") <= key <= ord("9"):
		return chr(key)

	# 兼容回车输入模式。
	if key in (10, 13, curses.KEY_ENTER):
		return ""

	return ""


def run_game_with_guard(stdscr: CursesWindow, runner: Callable[[CursesWindow], None]) -> Optional[str]:
	"""运行子游戏，并在异常时回传错误信息给主菜单显示。"""
	try:
		runner(stdscr)
		return None
	except Exception:
		# 捕获完整堆栈，但仅返回简要文本给菜单；详细堆栈可按需写日志。
		tb = traceback.format_exc(limit=6)
		return f"子游戏异常：{tb.splitlines()[-1]}"
	finally:
		# 无论子游戏是否崩溃，都尽最大努力恢复主菜单状态。
		reset_main_screen_state(stdscr)


# -----------------------------
# 3) 主程序入口
# -----------------------------


def app(stdscr: CursesWindow) -> None:
	"""curses wrapper 回调。"""
	# 主界面初始化。
	reset_main_screen_state(stdscr)

	registry = build_registry()

	# 启动页。
	draw_splash(stdscr)

	# 菜单循环。
	message = ""
	while True:
		draw_menu(stdscr, registry, message=message)
		message = ""

		choice = read_menu_choice(stdscr)

		# 退出。
		if choice == "0":
			break

		# 无效输入。
		if not choice:
			message = "Please enter a valid option."
			continue

		# 动态解析子游戏入口。
		try:
			runner = registry.resolve_runner(choice)
		except Exception as exc:
			message = f"Load failed: {exc}"
			continue

		if runner is None:
			message = f"Option {choice} is not registered."
			continue

		# 移交控制权给子游戏。
		err = run_game_with_guard(stdscr, runner)
		if err:
			message = err


def main() -> None:
	"""程序总入口。"""
	if curses is None:
		# 友好提示，避免“窗口一闪而过”。
		print("[Turing Complete] Startup failed: cannot import curses.")
		print(CURSES_ERROR or "Unknown error")
		print("\nSuggestions:")
		print("1) In a networked environment run: python -m pip install windows-curses")
		print("2) Re-run after installation: python main.py")
		try:
			input("\nPress Enter to exit...")
		except EOFError:
			pass
		return

	# 正常路径：进入 curses 主循环。
	curses.wrapper(app)


if __name__ == "__main__":
	main()
