"""
Rule 110 - One-dimensional Cellular Automaton
==============================================

Public interface:
- Exposes only `run(stdscr)` for dynamic loading by the main program.

Controls:
- P / Enter: pause or resume
- R: randomize a new first row and restart
- C: clear and restart from a single center live cell
- + / -: speed up / slow down
- Q: quit and return to main menu
"""

from __future__ import annotations

import curses
import random
import time
from dataclasses import dataclass


# -----------------------------
# 1) 状态与规则定义
# -----------------------------


@dataclass
class Rule110State:
	"""Rule 110 运行状态容器。"""

	# 历史行（每一行是长度为 width 的 0/1 列表）。
	# 由于是一维自动机，“时间”沿纵向展开：新一代追加到列表末尾。
	history: list[list[int]]

	# 自动演化控制。
	running: bool = True

	# 演化间隔（秒/代）。
	delay: float = 0.08

	# 已生成代数（第 1 行记为 generation = 0，随后递增）。
	generation: int = 0


# Rule 110 真值表（以 3bit 模式索引）：
# 邻域 -> next
# 111 -> 0
# 110 -> 1
# 101 -> 1
# 100 -> 0
# 011 -> 1
# 010 -> 1
# 001 -> 1
# 000 -> 0
#
# 索引方式：idx = (left << 2) | (center << 1) | right
# 例如 left=1, center=0, right=1 时 idx=5（即模式 101），next=1。
RULE110_TABLE: tuple[int, ...] = (
	0,  # 000
	1,  # 001
	1,  # 010
	1,  # 011
	0,  # 100
	1,  # 101
	1,  # 110
	0,  # 111
)


# -----------------------------
# 2) curses 安全绘制辅助
# -----------------------------


def safe_addstr(stdscr: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
	"""安全写字符串，避免终端边界变化触发 curses.error。"""
	try:
		stdscr.addstr(y, x, text, attr)
	except curses.error:
		pass


def safe_addch(stdscr: curses.window, y: int, x: int, ch: str, attr: int = 0) -> None:
	"""安全写单字符。"""
	try:
		stdscr.addch(y, x, ch, attr)
	except curses.error:
		pass


def safe_draw_line(stdscr: curses.window, y: int, text: str, attr: int = 0) -> None:
	"""清空整行后，按当前宽度裁剪并绘制文本。"""
	max_y, max_x = stdscr.getmaxyx()
	if y < 0 or y >= max_y:
		return

	try:
		stdscr.move(y, 0)
		stdscr.clrtoeol()
	except curses.error:
		pass

	if max_x <= 0:
		return

	try:
		# addnstr 会按 n 限制长度，避免越界。
		stdscr.addnstr(y, 0, text, max_x, attr)
	except curses.error:
		pass


# -----------------------------
# 3) 核心算法（Rule 110）
# -----------------------------


def make_center_seed(width: int) -> list[int]:
	"""经典初始状态：中间一个活细胞，其余全死。"""
	row = [0] * width
	if width > 0:
		row[width // 2] = 1
	return row


def make_random_seed(width: int, alive_probability: float = 0.35) -> list[int]:
	"""随机初始状态。"""
	return [1 if random.random() < alive_probability else 0 for _ in range(width)]


def next_row_fixed_dead(current: list[int]) -> list[int]:
	"""基于 Rule 110 计算下一行（边界策略：边界外固定为 0/死细胞）。

	说明：
	- 这里采用“固定边界”为死细胞的策略；
	- 对 i=0 时，left 视作 0；对 i=last 时，right 视作 0；
	- 中间位置正常读取左右邻居。
	"""
	width = len(current)
	next_line = [0] * width

	for i in range(width):
		left = current[i - 1] if i > 0 else 0
		center = current[i]
		right = current[i + 1] if i < width - 1 else 0

		# 3 比特邻域编码为 0..7：
		# idx = (L C R)_2
		idx = (left << 2) | (center << 1) | right
		next_line[i] = RULE110_TABLE[idx]

	return next_line


def remap_row_to_width(row: list[int], new_w: int) -> list[int]:
	"""终端宽度变化时，将已有一行映射到新宽度。

	策略（稳定且直观）：
	- 缩小时：居中裁剪；
	- 放大时：居中填充，两侧补 0。
	"""
	old_w = len(row)
	if new_w <= 0:
		return []
	if old_w == new_w:
		return row[:]

	if old_w > new_w:
		start = (old_w - new_w) // 2
		return row[start : start + new_w]

	# old_w < new_w
	pad_left = (new_w - old_w) // 2
	pad_right = new_w - old_w - pad_left
	return ([0] * pad_left) + row + ([0] * pad_right)


def remap_history_width(history: list[list[int]], new_w: int) -> list[list[int]]:
	"""将历史所有行映射到新宽度，保证终端缩放后仍可继续演化。"""
	return [remap_row_to_width(row, new_w) for row in history]


# -----------------------------
# 4) 布局、渲染、交互
# -----------------------------


def calc_layout(stdscr: curses.window) -> tuple[int, int, int, int]:
	"""计算布局。

	返回：
	- origin_y, origin_x: 自动机画布起点
	- canvas_h, canvas_w: 可绘制自动机的区域大小

	约定：
	- 顶部 2 行：标题 + 状态栏
	- 底部 1 行：帮助栏
	"""
	max_y, max_x = stdscr.getmaxyx()
	origin_y, origin_x = 2, 0
	canvas_h = max(1, max_y - 3)
	canvas_w = max(1, max_x)
	return origin_y, origin_x, canvas_h, canvas_w


def render(stdscr: curses.window, state: Rule110State) -> None:
	"""渲染当前画面。

	纵向滚动机制说明（核心）：
	- `state.history` 持续 append 新一代；
	- 屏幕只能显示 `canvas_h` 行，因此每帧只取历史尾部 `visible = history[-canvas_h:]`；
	- 这样历史越长，显示窗口会自然“上滚”，最新行始终贴近底部；
	- 该方案比手动调用终端滚动命令更稳定，也更易处理缩放。
	"""
	stdscr.erase()
	max_y, _ = stdscr.getmaxyx()
	origin_y, origin_x, canvas_h, canvas_w = calc_layout(stdscr)

	mode_text = "RUN" if state.running else "PAUSE"
	speed_text = f"{state.delay:.3f}s/row"

	safe_draw_line(stdscr, 0, "Rule 110 - One-dimensional Cellular Automaton", curses.A_BOLD)
	safe_draw_line(
		stdscr,
		1,
		f"Mode: {mode_text} | Gen: {state.generation} | Speed: {speed_text} | Width: {canvas_w}",
	)

	# 只显示最后 canvas_h 行，形成“时间向下、旧行向上离开视野”的视觉效果。
	visible = state.history[-canvas_h:]

	# 若历史行不足一屏，需要把内容贴底显示：
	# 例如只有 3 行而画布有 20 行，则从 y = origin_y + 17 开始绘制。
	start_screen_y = origin_y + (canvas_h - len(visible))

	for row_idx, row in enumerate(visible):
		sy = start_screen_y + row_idx
		for x in range(min(canvas_w, len(row))):
			ch = "█" if row[x] else " "
			safe_addch(stdscr, sy, origin_x + x, ch)

	help_text = "P/Enter pause | R random reset | C center-seed reset | +/- speed | Q back"
	safe_draw_line(stdscr, max_y - 1, help_text, curses.A_DIM)

	stdscr.refresh()


def restart_with_seed(state: Rule110State, width: int, seed: list[int]) -> None:
	"""重置历史并从指定第一行重新开始。"""
	if len(seed) != width:
		seed = remap_row_to_width(seed, width)
	state.history = [seed]
	state.generation = 0


def handle_key(stdscr: curses.window, state: Rule110State, key: int) -> bool:
	"""处理按键。返回 True 继续循环，False 退出游戏。"""
	_, _, _, canvas_w = calc_layout(stdscr)

	if key in (ord("p"), ord("P"), 10, 13, curses.KEY_ENTER):
		state.running = not state.running

	elif key in (ord("r"), ord("R")):
		restart_with_seed(state, canvas_w, make_random_seed(canvas_w))
		state.running = True

	elif key in (ord("c"), ord("C")):
		restart_with_seed(state, canvas_w, make_center_seed(canvas_w))
		state.running = True

	elif key in (ord("+"), ord("=")):
		# 更快：减小延时。
		state.delay = max(0.01, state.delay * 0.80)

	elif key in (ord("-"), ord("_")):
		# 更慢：增大延时。
		state.delay = min(1.50, state.delay * 1.25)

	elif key in (ord("q"), ord("Q")):
		return False

	return True


# -----------------------------
# 5) 对外统一入口
# -----------------------------


def run(stdscr: curses.window) -> None:
	"""统一入口函数：供主程序动态加载调用。"""

	# 保存并在 finally 中恢复 timeout，避免污染主菜单输入策略。
	prev_delay = None
	if hasattr(stdscr, "getdelay"):
		try:
			prev_delay = stdscr.getdelay()
		except Exception:
			prev_delay = None

	stdscr.keypad(True)
	stdscr.nodelay(True)
	stdscr.timeout(0)  # 非阻塞输入

	try:
		curses.curs_set(0)
	except curses.error:
		pass

	# 初始化宽度与初始行：经典中心单活细胞。
	_, _, _, canvas_w = calc_layout(stdscr)
	state = Rule110State(history=[make_center_seed(canvas_w)])

	# 记录上一次“生成新行”的时间戳。
	last_tick = time.monotonic()

	try:
		while True:
			# 终端尺寸变化处理：
			# 1) 读新宽度；
			# 2) 若变更，把历史全部映射到新宽度，确保演化连续。
			_, _, _, new_w = calc_layout(stdscr)
			current_w = len(state.history[-1]) if state.history else new_w
			if new_w != current_w:
				state.history = remap_history_width(state.history, new_w)

			# 绘制当前帧。
			render(stdscr, state)

			# 非阻塞读键：无键时返回 -1。
			key = stdscr.getch()
			if key != -1:
				keep_going = handle_key(stdscr, state, key)
				if not keep_going:
					break

			# 运行模式：按节拍生成下一行。
			if state.running:
				now = time.monotonic()
				if (now - last_tick) >= state.delay:
					last = state.history[-1]
					nxt = next_row_fixed_dead(last)
					state.history.append(nxt)
					state.generation += 1
					last_tick = now

			# 控制 CPU 占用，避免忙等。
			time.sleep(0.005)

	finally:
		# 离开子游戏前恢复窗口输入等待模式。
		if prev_delay is None:
			stdscr.timeout(-1)
		else:
			stdscr.timeout(prev_delay)
		stdscr.nodelay(False)

