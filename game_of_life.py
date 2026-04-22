"""
Conway's Game of Life module
============================

Public interface:
- Exposes only `run(stdscr)` for dynamic loading by the main program.

Controls:
- Arrow keys: move cursor
- Space: toggle cell alive/dead
- P / Enter: pause or resume (edit mode <-> run mode)
- R: randomize grid
- C: clear grid
- + / -: speed up / slow down evolution
- G: place a glider at cursor
- Q: quit and return to main menu
"""

from __future__ import annotations

import curses
import random
import time
from dataclasses import dataclass


# -----------------------------
# 1) 数据结构定义
# -----------------------------


@dataclass
class LifeState:
	"""生命游戏运行状态容器。"""

	# 当前网格（True=活细胞，False=死细胞）
	grid: list[list[bool]]

	# 光标位置（用于编辑模式和 G 图案放置）
	cursor_y: int = 0
	cursor_x: int = 0

	# 运行控制
	running: bool = False
	generation: int = 0

	# 每代演化间隔（秒）
	delay: float = 0.20


# -----------------------------
# 2) curses 安全绘制辅助
# -----------------------------


def safe_addstr(stdscr: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
	"""安全写字符串，防止终端尺寸变化时因越界触发 curses.error。"""
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


def clip_text_to_width(text: str, max_x: int) -> str:
	"""Clip a text line to terminal width to avoid rendering artifacts."""
	if max_x <= 0:
		return ""
	# Avoid writing to the last column to reduce terminal edge errors.
	return text[: max(0, max_x - 1)]


def safe_draw_line(stdscr: curses.window, y: int, text: str, attr: int = 0) -> None:
	"""Clear a full line and draw text clipped to current terminal width."""
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
		stdscr.addnstr(y, 0, text, max_x, attr)
	except curses.error:
		pass


# -----------------------------
# 3) 网格与演化逻辑
# -----------------------------


def make_grid(height: int, width: int, alive: bool = False) -> list[list[bool]]:
	"""创建 `height x width` 网格。"""
	return [[alive for _ in range(width)] for _ in range(height)]


def randomize_grid(grid: list[list[bool]], alive_probability: float = 0.24) -> None:
	"""按概率随机填充网格。"""
	h = len(grid)
	w = len(grid[0]) if h else 0
	for y in range(h):
		row = grid[y]
		for x in range(w):
			row[x] = random.random() < alive_probability


def clear_grid(grid: list[list[bool]]) -> None:
	"""清空网格（全部死亡）。"""
	h = len(grid)
	w = len(grid[0]) if h else 0
	for y in range(h):
		row = grid[y]
		for x in range(w):
			row[x] = False


def count_neighbors(grid: list[list[bool]], y: int, x: int) -> int:
	"""统计 (y, x) 周围 8 邻域活细胞数量（边界外视为死）。"""
	h = len(grid)
	w = len(grid[0]) if h else 0

	total = 0
	# 通过 dy, dx 双循环遍历八个邻居；跳过中心点 (0, 0)。
	for dy in (-1, 0, 1):
		ny = y + dy
		if ny < 0 or ny >= h:
			continue
		for dx in (-1, 0, 1):
			nx = x + dx
			if dx == 0 and dy == 0:
				continue
			if nx < 0 or nx >= w:
				continue
			total += 1 if grid[ny][nx] else 0
	return total


def step(grid: list[list[bool]]) -> list[list[bool]]:
	"""计算下一代网格（标准生命游戏规则）。"""
	h = len(grid)
	w = len(grid[0]) if h else 0
	next_grid = make_grid(h, w, alive=False)

	for y in range(h):
		for x in range(w):
			alive = grid[y][x]
			neighbors = count_neighbors(grid, y, x)

			# 规则：
			# 1) 活细胞且邻居数为 2 或 3 -> 存活
			# 2) 死细胞且邻居数为 3 -> 复活
			# 3) 其他情况 -> 死亡
			if alive and neighbors in (2, 3):
				next_grid[y][x] = True
			elif (not alive) and neighbors == 3:
				next_grid[y][x] = True
			else:
				next_grid[y][x] = False

	return next_grid


def place_glider(grid: list[list[bool]], top: int, left: int) -> None:
	"""在 (top, left) 作为左上角放置经典 Glider 图案。"""
	# 经典 glider（3x3）
	# . # .
	# . . #
	# # # #
	pattern = [
		(0, 1),
		(1, 2),
		(2, 0),
		(2, 1),
		(2, 2),
	]

	h = len(grid)
	w = len(grid[0]) if h else 0

	for dy, dx in pattern:
		y = top + dy
		x = left + dx
		if 0 <= y < h and 0 <= x < w:
			grid[y][x] = True


def resize_grid_preserve(
	old_grid: list[list[bool]], new_h: int, new_w: int
) -> list[list[bool]]:
	"""终端尺寸变化时，创建新网格并尽可能保留旧内容。"""
	new_grid = make_grid(new_h, new_w, alive=False)

	old_h = len(old_grid)
	old_w = len(old_grid[0]) if old_h else 0

	copy_h = min(old_h, new_h)
	copy_w = min(old_w, new_w)

	for y in range(copy_h):
		for x in range(copy_w):
			new_grid[y][x] = old_grid[y][x]

	return new_grid


# -----------------------------
# 4) UI 渲染与键盘处理
# -----------------------------


def calc_playfield_size(stdscr: curses.window) -> tuple[int, int, int, int]:
	"""根据当前终端尺寸计算可用网格区域。

	返回：
	- origin_y, origin_x: 网格左上角在屏幕中的起始位置
	- grid_h, grid_w: 网格尺寸

	约定：
	- 顶部占 2 行（标题+状态）；
	- 底部占 1 行（帮助提示）。
	"""
	max_y, max_x = stdscr.getmaxyx()
	origin_y, origin_x = 2, 0

	# 至少保留 3 行用于“标题/状态/帮助”，网格最小 1x1。
	grid_h = max(1, max_y - 3)
	grid_w = max(1, max_x)
	return origin_y, origin_x, grid_h, grid_w


def render(stdscr: curses.window, state: LifeState) -> None:
	"""绘制整个界面（标题、状态条、网格、帮助）。"""
	stdscr.erase()
	max_y, _ = stdscr.getmaxyx()

	origin_y, origin_x, grid_h, grid_w = calc_playfield_size(stdscr)

	mode_text = "RUN" if state.running else "EDIT"
	speed_text = f"{state.delay:.2f}s/gen"

	# 顶部标题。
	title = "Conway's Game of Life"
	safe_draw_line(stdscr, 0, title, curses.A_BOLD)

	# 状态栏：显示模式、代数、速度、当前坐标。
	coord_y = state.cursor_y + 1
	coord_x = state.cursor_x + 1
	status = (
		f"Mode: {mode_text} | Gen: {state.generation} | Speed: {speed_text} "
		f"| Cursor: ({coord_y}, {coord_x})"
	)
	safe_draw_line(stdscr, 1, status)

	# 网格绘制：
	# - 活细胞使用实心块 '█'
	# - 死细胞使用空格 ' '
	# - 光标位置使用反色高亮，便于编辑
	for y in range(grid_h):
		row = state.grid[y]
		sy = origin_y + y
		for x in range(grid_w):
			sx = origin_x + x
			ch = "█" if row[x] else " "

			# 光标高亮：无论编辑/运行模式都可见，便于定位和投放图案。
			if y == state.cursor_y and x == state.cursor_x:
				attr = curses.A_REVERSE
				# 若是活细胞，再叠加粗体提升辨识度。
				if row[x]:
					attr |= curses.A_BOLD
				safe_addch(stdscr, sy, sx, ch, attr)
			else:
				safe_addch(stdscr, sy, sx, ch)

	# 帮助行。
	help_text = (
		"Arrows move | Space toggle | P/Enter run/pause | R random | C clear | +/- speed | G glider | Q back"
	)
	safe_draw_line(stdscr, max_y - 1, help_text, curses.A_DIM)

	stdscr.refresh()


def clamp_cursor(state: LifeState, grid_h: int, grid_w: int) -> None:
	"""确保光标始终落在合法网格范围内。"""
	state.cursor_y = min(max(state.cursor_y, 0), grid_h - 1)
	state.cursor_x = min(max(state.cursor_x, 0), grid_w - 1)


def handle_key(stdscr: curses.window, state: LifeState, key: int) -> bool:
	"""处理按键。

	返回：
	- True：继续游戏循环
	- False：退出当前游戏
	"""
	_, _, grid_h, grid_w = calc_playfield_size(stdscr)

	# 方向键：移动光标。
	if key == curses.KEY_UP:
		state.cursor_y -= 1
	elif key == curses.KEY_DOWN:
		state.cursor_y += 1
	elif key == curses.KEY_LEFT:
		state.cursor_x -= 1
	elif key == curses.KEY_RIGHT:
		state.cursor_x += 1

	# 空格：切换当前细胞状态。
	elif key == ord(" "):
		y, x = state.cursor_y, state.cursor_x
		state.grid[y][x] = not state.grid[y][x]

	# P / Enter：运行与暂停切换。
	elif key in (ord("p"), ord("P"), 10, 13, curses.KEY_ENTER):
		state.running = not state.running

	# R：随机初始化。
	elif key in (ord("r"), ord("R")):
		randomize_grid(state.grid)
		state.generation = 0

	# C：清空画布。
	elif key in (ord("c"), ord("C")):
		clear_grid(state.grid)
		state.generation = 0

	# +：加快（减小 delay）。
	elif key in (ord("+"), ord("=")):
		state.delay = max(0.03, state.delay * 0.80)

	# -：减慢（增大 delay）。
	elif key in (ord("-"), ord("_")):
		state.delay = min(2.00, state.delay * 1.25)

	# G：在光标处放置 glider。
	elif key in (ord("g"), ord("G")):
		place_glider(state.grid, state.cursor_y, state.cursor_x)

	# Q：退出。
	elif key in (ord("q"), ord("Q")):
		return False

	# 任何按键处理后都夹紧光标，避免越界。
	clamp_cursor(state, grid_h, grid_w)
	return True


# -----------------------------
# 5) 对外统一入口
# -----------------------------


def run(stdscr: curses.window) -> None:
	"""统一游戏入口：供主程序通过动态加载调用。

	这个函数只依赖 `stdscr`，不依赖主程序内部状态，便于插件化扩展。
	"""
	# 保存（并在 finally 中恢复）当前窗口阻塞策略，避免影响主菜单。
	# 兼容说明：
	# - 部分 curses 实现（尤其 Windows 的适配实现）没有 `getdelay()` 方法；
	# - 因此这里使用“有则取值、无则降级”的策略，避免 AttributeError。
	prev_delay = None
	if hasattr(stdscr, "getdelay"):
		try:
			prev_delay = stdscr.getdelay()
		except Exception:
			# 即使读取失败也不影响游戏主体逻辑，后续走默认恢复路径。
			prev_delay = None

	# 子游戏内部初始化。
	stdscr.keypad(True)
	# 强制整屏清除，避免主菜单字符残留到子游戏界面。
	stdscr.clear()
	stdscr.refresh()
	try:
		curses.curs_set(0)
	except curses.error:
		pass

	# 根据当前窗口尺寸创建网格。
	_, _, grid_h, grid_w = calc_playfield_size(stdscr)
	state = LifeState(grid=make_grid(grid_h, grid_w, alive=False))

	# 记录运行模式中的上次演化时间点。
	last_tick = time.monotonic()

	try:
		while True:
			# 处理终端尺寸变化：
			# 每帧重新计算尺寸，如果变化则保留旧内容后扩缩容。
			_, _, new_h, new_w = calc_playfield_size(stdscr)
			if new_h != len(state.grid) or new_w != len(state.grid[0]):
				state.grid = resize_grid_preserve(state.grid, new_h, new_w)
				clamp_cursor(state, new_h, new_w)

			# 绘制当前帧。
			render(stdscr, state)

			# 键盘监听策略：
			# - 编辑模式：阻塞等待（CPU 占用低，交互直观）
			# - 运行模式：按 delay 超时等待（到点自动演化，期间可抢占按键）
			if state.running:
				stdscr.timeout(max(1, int(state.delay * 1000)))
			else:
				stdscr.timeout(-1)

			key = stdscr.getch()

			# 先处理按键（若按 Q 会直接退出）。
			if key != -1:
				keep_going = handle_key(stdscr, state, key)
				if not keep_going:
					break

			# 在运行模式下：当超时或到达节拍时推进一代。
			if state.running:
				now = time.monotonic()
				if (now - last_tick) >= state.delay:
					state.grid = step(state.grid)
					state.generation += 1
					last_tick = now

	finally:
		# 离开子游戏前恢复窗口 timeout 模式，尽量不污染主程序状态。
		if prev_delay is None:
			# 无法读取原始 delay 时，恢复为阻塞模式（与主菜单默认一致）。
			stdscr.timeout(-1)
		else:
			stdscr.timeout(prev_delay)
