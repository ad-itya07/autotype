import argparse
import os
import random
import sys
import time
import threading

import pyautogui
from pynput import keyboard

def read_text(args) -> str:
    if args.text is not None:
        return args.text
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            return f.read()
    print("No input given. Use --text '...' or --file path.txt", file=sys.stderr)
    sys.exit(2)

def split_lines_preserve(text: str):
    """
    Split into lines, preserving line endings.
    Returns list of tuples: (indent, content_no_indent, line_ending)
    """
    out = []
    start = 0
    while start < len(text):
        # find end of line
        i = text.find('\n', start)
        if i == -1:
            line = text[start:]
            line_ending = ""
            start = len(text)
        else:
            line = text[start:i]
            line_ending = "\n"
            start = i + 1

        # handle possible '\r' before '\n' (Windows CRLF)
        if line.endswith('\r'):
            line = line[:-1]
            line_ending = "\r\n"

        # split indent/content
        j = 0
        while j < len(line) and line[j] in (' ', '\t'):
            j += 1
        indent = line[:j]
        content = line[j:]
        out.append((indent, content, line_ending))
    if not out:
        out = [("", "", "")]
    return out

def make_indent_string(indent: str, normalize_tabs: bool, tab_size: int) -> str:
    if not normalize_tabs:
        return indent
    # Convert tabs to spaces, preserving spaces
    return indent.replace('\t', ' ' * tab_size)

# Fix PyAutoGUI X11 bug on Linux where '<' is mapped to ISO keycode 94 (which shifts to '>')
try:
    import pyautogui._pyautogui_x11 as _px
    if ',' in _px.keyboardMapping:
        _px.keyboardMapping['<'] = _px.keyboardMapping[',']
except Exception:
    pass

def true_type_char(ch: str, base_interval: float, jitter: float, word_pause: float, auto_brace_fix: bool = True):
    pyautogui.typewrite(ch, _pause=False)
    if ch == "{" and auto_brace_fix:
        # Monaco / LeetCode auto-inserts '}' right after '{'.
        # Delete the auto-inserted '}' so blocks don't close prematurely.
        time.sleep(0.04)
        pyautogui.press('delete')
    if ch == " " and word_pause > 0:
        time.sleep(word_pause)
        return
    sigma = base_interval * jitter
    dt = max(0.0, random.gauss(base_interval, sigma))
    time.sleep(dt)

def type_line(indent: str, content: str, base_interval: float, jitter: float, word_pause: float, auto_brace_fix: bool = True):
    # type indent, then content
    for ch in indent:
        true_type_char(ch, base_interval, jitter, word_pause, auto_brace_fix)
    for ch in content:
        true_type_char(ch, base_interval, jitter, word_pause, auto_brace_fix)

def main():
    p = argparse.ArgumentParser(description="Auto typer with countdown & indentation correction (Insert or Ctrl+Enter=toggle, Esc=exit).")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--text", type=str, help="Text to type (quotes recommended).")
    src.add_argument("--file", type=str, help="Path to a text file to type.")

    p.add_argument("--gui", action="store_true", help="Launch the interactive Tkinter GUI interface.")
    p.add_argument("-c", "--countdown", type=int, default=5, help="Countdown in seconds before auto-starting (default: 5s, allows switching to remote desktop without hotkeys). Set to 0 to only use hotkeys.")
    p.add_argument("--wpm", type=float, default=200.0, help="Words per minute (true typing). Default 200 (safe for remote desktop latency).")
    p.add_argument("--jitter", type=float, default=0.06, help="Timing jitter ratio (0-0.5).")
    p.add_argument("--word-pause", type=float, default=0.03, help="Extra pause (seconds) after each space (default 0.03s, prevents dropped spaces).")
    p.add_argument("--auto-brace-fix", action=argparse.BooleanOptionalAction, default=True, help="Auto-delete editor's auto-inserted '}' when typing '{' (default True for LeetCode/VS Code).")
    p.add_argument("--mac", action=argparse.BooleanOptionalAction, default=True, help="Enable macOS remote target mode (clears stuck Cmd/Ctrl modifiers and avoids Home/End key issues).")
    p.add_argument("--start-delay", type=float, default=0.0, help="Delay after hotkey press before typing starts.")
    p.add_argument("--status-interval", type=float, default=2.0, help="Status print interval in seconds.")

    # Indentation control
    p.add_argument("--indent-fix", action="store_true", help="Enable indentation correction across lines.")
    p.add_argument("--delete-indent-max", type=int, default=40, help="(kept for compatibility; not used to delete).")
    p.add_argument("--normalize-tabs", action="store_true", help="Convert tabs to spaces when typing indentation.")
    p.add_argument("--tab-size", type=int, default=4, help="Spaces per tab when --normalize-tabs is used.")
    p.add_argument("--post-enter-wait", type=float, default=0.14, help="Wait after Enter so the editor creates/indents the new line.")

    args = p.parse_args()

    # If --gui requested or no input arguments provided, launch the Tkinter GUI
    if args.gui or (args.text is None and args.file is None):
        try:
            from gui import AutoTyperApp
            app = AutoTyperApp()
            app.mainloop()
            return
        except Exception as e:
            print(f"Could not launch GUI ({e}), falling back to CLI.", file=sys.stderr)

    text = read_text(args)

    # Wayland detection & advice
    is_wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland"
    if is_wayland:
        print("=" * 65)
        print("ℹ️  NOTE: WAYLAND SESSION DETECTED")
        print("Ubuntu's default Wayland blocks global hotkeys across apps.")
        print(f"-> Countdown mode ({args.countdown}s) is enabled to start automatically.")
        print("-> If simulated typing doesn't enter into Getscreen/Chrome,")
        print("   switch to 'Ubuntu on Xorg' at the Ubuntu login screen.")
        print("=" * 65)

    def release_all_modifiers():
        """Ensure no modifier keys (Ctrl/Cmd/Alt/Shift) stay stuck in the remote session."""
        for mod in ('ctrl', 'shift', 'alt', 'command', 'win', 'ctrlleft', 'ctrlright', 'shiftleft', 'shiftright', 'altleft', 'altright'):
            try:
                pyautogui.keyUp(mod)
            except Exception:
                pass

    pyautogui.FAILSAFE = True
    # Small pause (8ms) between keystroke events prevents remote WebRTC/macOS from dropping key-up packets
    pyautogui.PAUSE = 0.008

    cps = (args.wpm * 5.0) / 60.0 
    base_interval = 1.0 / max(1e-6, cps)

    lines = split_lines_preserve(text)
    total_chars = sum(len(i) + len(c) + len(le) for i, c, le in lines)

    print(f"Target WPM: {args.wpm:.1f} | CPS: {cps:.2f} | Total chars: {total_chars} | macOS mode: {args.mac}")
    print("Controls: INSERT or Ctrl+Enter = Pause/Resume | Esc = Exit")

    running = threading.Event()
    exiting = threading.Event()

    # position within the (line, offset) space
    line_idx = [0]
    col_idx = [0]

    ctrl_pressed = [False]

    def toggle_running():
        if running.is_set():
            running.clear()
            release_all_modifiers()
            print("\n[Paused] Press INSERT or Ctrl+Enter to resume.")
        else:
            if args.start_delay > 0:
                print(f"\nResuming in {args.start_delay:.2f}s…")
                time.sleep(args.start_delay)
            release_all_modifiers()
            running.set()
            print("\n[Typing...] Press INSERT or Ctrl+Enter to pause.")

    def on_press(key):
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
            ctrl_pressed[0] = True
            return

        if key == keyboard.Key.insert or (key == keyboard.Key.enter and ctrl_pressed[0]):
            toggle_running()
        elif key == keyboard.Key.esc:
            exiting.set()
            running.clear()
            release_all_modifiers()
            print("\n[Exiting] (Esc pressed).")
            return False

    def on_release(key):
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
            ctrl_pressed[0] = False

    listener = None
    try:
        from pynput import keyboard as kb
        listener = kb.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()
    except Exception as e:
        print(f"Warning: Could not start keyboard listener ({e}). Running in countdown-only mode.")

    # Countdown to auto-start if configured
    if args.countdown > 0:
        print(f"\nSwitch to your Getscreen / target window now!")
        for sec in range(args.countdown, 0, -1):
            print(f"  Starting in {sec}s...", end="\r", flush=True)
            time.sleep(1)
        print("  Started! Typing now...          ")
        release_all_modifiers()
        running.set()
    else:
        print("\nReady. Click into target window and press INSERT or Ctrl+Enter to start.")

    last_status = time.time()

    def clear_auto_indent(delete_max: int):
        if not args.mac:
            pyautogui.press('home')
            time.sleep(0.01)

    try:
        while not exiting.is_set() and line_idx[0] < len(lines):
            if not running.is_set():
                if time.time() - last_status >= args.status_interval:
                    done = sum(len(i) + len(c) for i, c, _ in lines[:line_idx[0]])
                    print(f"Paused. Progress line {line_idx[0]+1}/{len(lines)} "
                          f"({done}/{total_chars} chars). Insert to resume.")
                    last_status = time.time()
                time.sleep(0.02)
                continue

            # Periodically ensure modifiers haven't stuck on the remote machine
            if line_idx[0] % 5 == 0:
                release_all_modifiers()

            indent, content, ending = lines[line_idx[0]]

            # If at start of line and indentation fix requested:
            if col_idx[0] == 0 and args.indent_fix:
                clear_auto_indent(args.delete_indent_max)
                indent_str = make_indent_string(indent, args.normalize_tabs, args.tab_size)
                for ch in indent_str:
                    true_type_char(ch, base_interval, args.jitter, args.word_pause, args.auto_brace_fix)
                col_idx[0] = len(indent_str)

            # Type remaining part of this line (content)
            while col_idx[0] < len(indent) + len(content):
                if col_idx[0] < len(indent):    # (only happens if indent_fix is off)
                    ch = indent[col_idx[0]]
                else:
                    ch = content[col_idx[0] - len(indent)]
                true_type_char(ch, base_interval, args.jitter, args.word_pause, args.auto_brace_fix)
                col_idx[0] += 1

            # Type the line ending (press Enter)
            if ending:
                # On macOS and web editors, pressing 'End' jumps to document bottom.
                # The cursor is naturally already at the end of the line!
                if not args.mac:
                    pyautogui.press('end')
                    time.sleep(0.02)

                pyautogui.press('enter')
                time.sleep(args.post_enter_wait)

                line_idx[0] += 1
                col_idx[0] = 0
            else:
                line_idx[0] += 1
                col_idx[0] = 0

            if time.time() - last_status >= args.status_interval:
                print(f"Typing… line {line_idx[0]}/{len(lines)}")
                last_status = time.time()

        if line_idx[0] >= len(lines):
            print("Done. Reached end of input.")
    except pyautogui.FailSafeException:
        print("Aborted by moving mouse to top-left corner (PyAutoGUI failsafe).")
    finally:
        running.clear()
        exiting.set()
        release_all_modifiers()
        if listener:
            try:
                listener.stop()
            except Exception:
                pass

if __name__ == "__main__":
    main()
