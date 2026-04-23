"""
Turing Machine - terminal simulator module
=========================================

Public interface:
- Exposes only `run(stdscr)` for dynamic loading by the main program.

Core controls:
- Tab: switch Edit / Run mode
- Q: quit and return to main menu
- R: reset to initial tape, state=q0, steps=0

Edit mode:
- Left / Right: move tape edit cursor
- 0 / 1 / _ / Space: write symbol at cursor
- Up / Down: select rule row (enters rules focus)
- Left / Right in rules focus: select editable column
- Enter: cycle selected rule field
- 0 / 1 / _ / Space: set write symbol (rules col=WRITE)
- L / R / S: set move direction (rules col=MOVE)
- [ / ] or N: previous/next state (rules col=NEXT)
- T: back to tape focus

Run mode:
- Space: play/pause auto running
- Right / Enter: single step
"""

from __future__ import annotations

import curses
import time
from dataclasses import dataclass, field


SYMBOLS: tuple[str, ...] = ("0", "1", "_")
MOVE_SET: tuple[str, ...] = ("L", "R", "S")
STATES: tuple[str, ...] = ("q0", "q1", "q_accept", "q_reject")
HALT_STATES: set[str] = {"q_accept", "q_reject"}


@dataclass
class TMState:
	"""图灵机运行态。"""

	# 仅存非空白符号；空白 `_` 视为不存在。
	tape: dict[int, str] = field(default_factory=dict)
	initial_tape: dict[int, str] = field(default_factory=dict)

	# 运行指针
	head: int = 0
	cursor: int = 0
	current_state: str = "q0"
	steps: int = 0

	# 模式与运行控制
	mode: str = "EDIT"  # EDIT / RUN
	auto_run: bool = False
	delay: float = 0.20

	# 编辑焦点：tape / rules
	edit_focus: str = "tape"
	rules_selected_row: int = 0
	rules_selected_col: int = 0  # 0=WRITE, 1=MOVE, 2=NEXT
	rules_scroll: int = 0

	# 状态提示
	message: str = ""

	# 规则表：(state, read) -> (write, move, next_state)
	rules: dict[tuple[str, str], tuple[str, str, str]] = field(default_factory=dict)


def safe_addstr(stdscr: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
	try:
		stdscr.addstr(y, x, text, attr)
	except curses.error:
		pass


def safe_addnstr(stdscr: curses.window, y: int, x: int, text: str, n: int, attr: int = 0) -> None:
	if n <= 0:
		return
	try:
		stdscr.addnstr(y, x, text, n, attr)
	except curses.error:
		pass


def safe_draw_line(stdscr: curses.window, y: int, text: str, attr: int = 0) -> None:
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
	safe_addnstr(stdscr, y, 0, text, max_x, attr)


def _sorted_rule_keys() -> list[tuple[str, str]]:
	keys: list[tuple[str, str]] = []
	for s in STATES:
		for r in SYMBOLS:
			keys.append((s, r))
	return keys


def default_rules() -> dict[tuple[str, str], tuple[str, str, str]]:
	"""默认规则：示例性可运行配置，且可在界面中完全改写。"""
	rules: dict[tuple[str, str], tuple[str, str, str]] = {}

	# q0: 扫描连续 1，遇到 0 接受，遇到空白拒绝。
	rules[("q0", "1")] = ("1", "R", "q0")
	rules[("q0", "0")] = ("0", "S", "q_accept")
	rules[("q0", "_")] = ("_", "S", "q_reject")

	# q1: 预留状态，默认保持不变并右移。
	rules[("q1", "0")] = ("0", "R", "q1")
	rules[("q1", "1")] = ("1", "R", "q1")
	rules[("q1", "_")] = ("_", "S", "q_accept")

	# halt 状态：保持停机。
	for s in ("q_accept", "q_reject"):
		for r in SYMBOLS:
			rules[(s, r)] = (r, "S", s)

	return rules


def get_symbol(tape: dict[int, str], pos: int) -> str:
	return tape.get(pos, "_")


def set_symbol(tape: dict[int, str], pos: int, symbol: str) -> None:
	if symbol == "_":
		tape.pop(pos, None)
	else:
		tape[pos] = symbol


def step_forward(state: TMState) -> None:
	"""执行一步图灵机转移；无规则时进入 reject。"""
	if state.current_state in HALT_STATES:
		state.auto_run = False
		state.message = f"Machine halted at {state.current_state}."
		return

	read = get_symbol(state.tape, state.head)
	trans = state.rules.get((state.current_state, read))
	if trans is None:
		state.current_state = "q_reject"
		state.auto_run = False
		state.message = f"No rule for ({state.current_state}, {read}), forced reject."
		return

	write, move, next_state = trans
	set_symbol(state.tape, state.head, write)

	if move == "L":
		state.head -= 1
	elif move == "R":
		state.head += 1

	state.current_state = next_state
	state.steps += 1
	state.cursor = state.head

	if state.current_state in HALT_STATES:
		state.auto_run = False
		state.message = f"Machine halted at {state.current_state}."


def reset_machine(state: TMState) -> None:
	state.tape = dict(state.initial_tape)
	state.head = 0
	state.cursor = 0
	state.current_state = "q0"
	state.steps = 0
	state.auto_run = False
	state.message = "Reset to initial tape and q0."


def calc_layout(stdscr: curses.window) -> dict[str, int]:
	max_y, max_x = stdscr.getmaxyx()

	header_h = 2
	tape_h = 5
	help_h = 1

	rules_top = header_h + tape_h
	rules_h = max(3, max_y - rules_top - help_h)
	help_y = max(0, max_y - 1)

	return {
		"max_y": max_y,
		"max_x": max_x,
		"header_h": header_h,
		"tape_h": tape_h,
		"rules_top": rules_top,
		"rules_h": rules_h,
		"help_y": help_y,
	}


def _state_with_halt_mark(s: str) -> str:
	if s == "q_accept":
		return "q_accept✓"
	if s == "q_reject":
		return "q_reject✗"
	return s


def render_header(stdscr: curses.window, state: TMState, max_x: int) -> None:
	mode = state.mode
	auto = "AUTO" if state.auto_run else "PAUSE"
	title = "Turing Machine"
	header = (
		f"{title} | Mode: {mode} | State: {_state_with_halt_mark(state.current_state)} | "
		f"Steps: {state.steps} | Run: {auto}"
	)
	safe_draw_line(stdscr, 0, header, curses.A_BOLD)
	safe_draw_line(stdscr, 1, state.message if state.message else "", curses.A_DIM)


def render_tape(stdscr: curses.window, state: TMState, layout: dict[str, int]) -> None:
	max_x = layout["max_x"]
	y0 = layout["header_h"]

	if max_x <= 0:
		return

	window_w = max(5, max_x - 2)
	# 保证读写头接近中心，自动平移。
	start = state.head - (window_w // 2)
	end = start + window_w - 1

	safe_draw_line(stdscr, y0, f"Tape View [{start}..{end}]  Head={state.head}  Cursor={state.cursor}")

	# 纸带字符行
	line_chars: list[str] = []
	for pos in range(start, end + 1):
		sym = get_symbol(state.tape, pos)
		if pos == state.head:
			line_chars.append(f"[{sym}]")
		elif state.mode == "EDIT" and state.edit_focus == "tape" and pos == state.cursor:
			line_chars.append(f"<{sym}>")
		else:
			line_chars.append(f" {sym} ")

	tape_line = "".join(line_chars)
	safe_addnstr(stdscr, y0 + 1, 0, tape_line, max_x)

	# 读写头标记行
	head_col = (state.head - start) * 3 + 1
	marker = "^"
	try:
		stdscr.move(y0 + 2, 0)
		stdscr.clrtoeol()
	except curses.error:
		pass
	safe_addnstr(stdscr, y0 + 2, max(0, head_col), marker, max(0, max_x - head_col), curses.A_BOLD)

	# 索引刻度（稀疏）
	index_line = []
	for pos in range(start, end + 1):
		if pos % 5 == 0:
			index_line.append("│")
		else:
			index_line.append(" ")
	safe_addnstr(stdscr, y0 + 3, 0, " ".join(index_line), max_x, curses.A_DIM)

	separator = "-" * max(0, max_x)
	safe_addnstr(stdscr, y0 + 4, 0, separator, max_x, curses.A_DIM)


def _cycle(seq: tuple[str, ...], cur: str, delta: int = 1) -> str:
	if cur not in seq:
		return seq[0]
	idx = seq.index(cur)
	return seq[(idx + delta) % len(seq)]


def _ensure_rules_scroll(state: TMState, visible_rows: int, total_rows: int) -> None:
	if visible_rows <= 0:
		state.rules_scroll = 0
		return
	if state.rules_selected_row < state.rules_scroll:
		state.rules_scroll = state.rules_selected_row
	if state.rules_selected_row >= state.rules_scroll + visible_rows:
		state.rules_scroll = state.rules_selected_row - visible_rows + 1
	state.rules_scroll = max(0, min(state.rules_scroll, max(0, total_rows - visible_rows)))


def render_rules_table(stdscr: curses.window, state: TMState, layout: dict[str, int]) -> None:
	rules_top = layout["rules_top"]
	rules_h = layout["rules_h"]
	max_x = layout["max_x"]

	if rules_h <= 0:
		return

	header = "Rules: (State, Read) -> (Write, Move, Next)"
	if state.mode == "EDIT" and state.edit_focus == "rules":
		header += "  [RULE-EDIT]"
	safe_draw_line(stdscr, rules_top, header, curses.A_BOLD)

	rows = _sorted_rule_keys()
	visible_rows = max(1, rules_h - 1)
	_ensure_rules_scroll(state, visible_rows, len(rows))

	for i in range(visible_rows):
		y = rules_top + 1 + i
		row_idx = state.rules_scroll + i
		if row_idx >= len(rows):
			safe_draw_line(stdscr, y, "")
			continue

		sk = rows[row_idx]
		write, move, nxt = state.rules.get(sk, (sk[1], "S", "q_reject"))
		line = f"({sk[0]:8s}, {sk[1]}) -> ({write}, {move}, {nxt})"

		is_selected = (row_idx == state.rules_selected_row)
		attr = curses.A_NORMAL
		if is_selected:
			attr |= curses.A_REVERSE

		# 在选中行上突出当前编辑列。
		if is_selected and state.mode == "EDIT" and state.edit_focus == "rules":
			prefix = f"({sk[0]:8s}, {sk[1]}) -> ("
			col_spans = [
				(len(prefix), 1),
				(len(prefix) + 3, 1),
				(len(prefix) + 6, len(nxt)),
			]
			safe_addnstr(stdscr, y, 0, line, max_x, attr)
			hx, hlen = col_spans[state.rules_selected_col]
			hx = min(max(0, hx), max_x - 1)
			safe_addnstr(stdscr, y, hx, line[hx : hx + hlen], max(0, max_x - hx), curses.A_BOLD)
		else:
			safe_addnstr(stdscr, y, 0, line, max_x, attr)


def render_help(stdscr: curses.window, state: TMState, layout: dict[str, int]) -> None:
	help_y = layout["help_y"]
	if state.mode == "EDIT":
		help = (
			"Tab mode | Q quit | R reset | EDIT: ←/→ move, 0/1/_/Space write | "
			"↑/↓ rules, Enter cycle, L/R/S move, [/] next, T tape"
		)
	else:
		help = "Tab mode | Q quit | R reset | RUN: Space play/pause | →/Enter step"
	safe_draw_line(stdscr, help_y, help, curses.A_DIM)


def render(stdscr: curses.window, state: TMState) -> None:
	stdscr.erase()
	layout = calc_layout(stdscr)
	render_header(stdscr, state, layout["max_x"])
	render_tape(stdscr, state, layout)
	render_rules_table(stdscr, state, layout)
	render_help(stdscr, state, layout)
	stdscr.refresh()


def _edit_rule_set_write(state: TMState, symbol: str) -> None:
	keys = _sorted_rule_keys()
	if not keys:
		return
	key = keys[state.rules_selected_row]
	_, move, nxt = state.rules.get(key, (key[1], "S", "q_reject"))
	state.rules[key] = (symbol, move, nxt)


def _edit_rule_set_move(state: TMState, move: str) -> None:
	keys = _sorted_rule_keys()
	if not keys:
		return
	key = keys[state.rules_selected_row]
	write, _, nxt = state.rules.get(key, (key[1], "S", "q_reject"))
	state.rules[key] = (write, move, nxt)


def _edit_rule_cycle_next_state(state: TMState, delta: int = 1) -> None:
	keys = _sorted_rule_keys()
	if not keys:
		return
	key = keys[state.rules_selected_row]
	write, move, nxt = state.rules.get(key, (key[1], "S", "q_reject"))
	state.rules[key] = (write, move, _cycle(STATES, nxt, delta))


def _edit_rule_cycle_current_field(state: TMState) -> None:
	keys = _sorted_rule_keys()
	if not keys:
		return
	key = keys[state.rules_selected_row]
	write, move, nxt = state.rules.get(key, (key[1], "S", "q_reject"))
	if state.rules_selected_col == 0:
		state.rules[key] = (_cycle(SYMBOLS, write), move, nxt)
	elif state.rules_selected_col == 1:
		state.rules[key] = (write, _cycle(MOVE_SET, move), nxt)
	else:
		state.rules[key] = (write, move, _cycle(STATES, nxt))


def handle_edit_mode_key(stdscr: curses.window, state: TMState, key: int) -> None:
	rows = _sorted_rule_keys()
	max_row = max(0, len(rows) - 1)

	# 写入 tape（仅 tape 焦点）
	if state.edit_focus == "tape":
		if key == curses.KEY_LEFT:
			state.cursor -= 1
			state.message = ""
			return
		if key == curses.KEY_RIGHT:
			state.cursor += 1
			state.message = ""
			return
		if key in (ord("0"), ord("1"), ord("_"), ord(" ")):
			symbol = "_" if key == ord(" ") else chr(key)
			set_symbol(state.tape, state.cursor, symbol)
			set_symbol(state.initial_tape, state.cursor, symbol)
			state.message = f"Tape[{state.cursor}] = {symbol}"
			return
		if key == curses.KEY_UP:
			state.edit_focus = "rules"
			state.message = "Rules focus"
			return

	# rules 焦点
	if state.edit_focus == "rules":
		if key == curses.KEY_UP:
			state.rules_selected_row = max(0, state.rules_selected_row - 1)
			return
		if key == curses.KEY_DOWN:
			state.rules_selected_row = min(max_row, state.rules_selected_row + 1)
			return
		if key == curses.KEY_LEFT:
			state.rules_selected_col = max(0, state.rules_selected_col - 1)
			return
		if key == curses.KEY_RIGHT:
			state.rules_selected_col = min(2, state.rules_selected_col + 1)
			return
		if key in (10, 13, curses.KEY_ENTER):
			_edit_rule_cycle_current_field(state)
			state.message = "Rule updated"
			return
		if key in (ord("0"), ord("1"), ord("_"), ord(" ")) and state.rules_selected_col == 0:
			symbol = "_" if key == ord(" ") else chr(key)
			_edit_rule_set_write(state, symbol)
			state.message = "Rule write-symbol updated"
			return
		if key in (ord("l"), ord("L")) and state.rules_selected_col == 1:
			_edit_rule_set_move(state, "L")
			state.message = "Rule move=L"
			return
		if key in (ord("r"), ord("R")) and state.rules_selected_col == 1:
			_edit_rule_set_move(state, "R")
			state.message = "Rule move=R"
			return
		if key in (ord("s"), ord("S")) and state.rules_selected_col == 1:
			_edit_rule_set_move(state, "S")
			state.message = "Rule move=S"
			return
		if key in (ord("n"), ord("N"), ord("]")) and state.rules_selected_col == 2:
			_edit_rule_cycle_next_state(state, +1)
			state.message = "Rule next-state cycled"
			return
		if key == ord("[") and state.rules_selected_col == 2:
			_edit_rule_cycle_next_state(state, -1)
			state.message = "Rule next-state cycled"
			return
		if key in (ord("t"), ord("T")):
			state.edit_focus = "tape"
			state.message = "Tape focus"
			return


def handle_run_mode_key(state: TMState, key: int) -> None:
	if key == ord(" "):
		if state.current_state in HALT_STATES:
			state.message = "Machine already halted; press R to reset."
			state.auto_run = False
			return
		state.auto_run = not state.auto_run
		state.message = "Auto run" if state.auto_run else "Paused"
		return

	if key in (curses.KEY_RIGHT, 10, 13, curses.KEY_ENTER):
		step_forward(state)


def run(stdscr: curses.window) -> None:
	"""对外唯一入口：由主程序动态加载调用。"""
	prev_delay = None
	if hasattr(stdscr, "getdelay"):
		try:
			prev_delay = stdscr.getdelay()
		except Exception:
			prev_delay = None

	stdscr.keypad(True)
	stdscr.nodelay(True)
	stdscr.timeout(0)
	stdscr.clear()
	stdscr.refresh()
	try:
		curses.curs_set(0)
	except curses.error:
		pass

	state = TMState()
	state.rules = default_rules()
	state.message = "Edit tape/rules, then press Tab to run."

	last_tick = time.monotonic()

	try:
		while True:
			render(stdscr, state)

			key = stdscr.getch()
			if key == curses.KEY_RESIZE:
				continue

			if key != -1:
				# 全局键
				if key in (ord("q"), ord("Q")):
					break
				if key in (ord("r"), ord("R")):
					reset_machine(state)
					continue
				if key == 9:  # Tab
					state.mode = "RUN" if state.mode == "EDIT" else "EDIT"
					if state.mode == "EDIT":
						state.auto_run = False
						state.message = "Switched to EDIT mode."
					else:
						state.message = "Switched to RUN mode."
					continue

				# 模式内按键
				if state.mode == "EDIT":
					handle_edit_mode_key(stdscr, state, key)
				else:
					handle_run_mode_key(state, key)

			# 自动运行
			if state.mode == "RUN" and state.auto_run:
				now = time.monotonic()
				if (now - last_tick) >= state.delay:
					step_forward(state)
					last_tick = now

			time.sleep(0.005)

	finally:
		# 退出前恢复关键 curses 状态，避免污染主菜单。
		stdscr.nodelay(False)
		if prev_delay is None:
			stdscr.timeout(-1)
		else:
			stdscr.timeout(prev_delay)
		stdscr.keypad(True)
		try:
			curses.curs_set(0)
		except curses.error:
			pass
