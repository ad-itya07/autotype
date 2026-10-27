import os
import random
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

import pyautogui
from pynput import keyboard

# Fix PyAutoGUI X11 bug on Linux where '<' is mapped to ISO keycode 94 (which shifts to '>')
try:
    import pyautogui._pyautogui_x11 as _px
    if ',' in _px.keyboardMapping:
        _px.keyboardMapping['<'] = _px.keyboardMapping[',']
except Exception:
    pass

def split_lines_preserve(text: str):
    out = []
    start = 0
    while start < len(text):
        i = text.find('\n', start)
        if i == -1:
            line = text[start:]
            line_ending = ""
            start = len(text)
        else:
            line = text[start:i]
            line_ending = "\n"
            start = i + 1

        if line.endswith('\r'):
            line = line[:-1]
            line_ending = "\r\n"

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
    return indent.replace('\t', ' ' * tab_size)

def release_all_modifiers():
    for mod in ('ctrl', 'shift', 'alt', 'command', 'win', 'ctrlleft', 'ctrlright', 'shiftleft', 'shiftright', 'altleft', 'altright'):
        try:
            pyautogui.keyUp(mod)
        except Exception:
            pass

class AutoTyperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AutoTyper Pro — Remote Desktop & Code Editor")
        self.geometry("820x750")
        self.minsize(700, 600)

        # State events
        self.running_event = threading.Event()
        self.stop_event = threading.Event()
        self.typing_thread = None
        self.listener = None

        self._setup_style()
        self._build_ui()
        self._setup_hotkey_listener()

        # Load default input.txt if it exists
        default_file = os.path.join(os.path.dirname(__file__), "input.txt")
        if os.path.isfile(default_file):
            try:
                with open(default_file, "r", encoding="utf-8") as f:
                    self.text_area.insert("1.0", f.read())
                    self._update_stats()
            except Exception:
                pass

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_style(self):
        self.configure(bg="#181825")
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Color palette
        self.colors = {
            "bg": "#181825",
            "card_bg": "#1e1e2e",
            "card_border": "#313244",
            "text": "#cdd6f4",
            "text_muted": "#a6adc8",
            "primary": "#89b4fa",
            "success": "#a6e3a1",
            "warning": "#f9e2af",
            "danger": "#f38ba8",
            "accent": "#cba6f7",
            "input_bg": "#11111b"
        }

        self.style.configure(".", background=self.colors["bg"], foreground=self.colors["text"])
        self.style.configure("TFrame", background=self.colors["bg"])
        self.style.configure("Card.TFrame", background=self.colors["card_bg"], relief="flat")
        self.style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=("Segoe UI", 10))
        self.style.configure("Card.TLabel", background=self.colors["card_bg"], foreground=self.colors["text"], font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", background=self.colors["bg"], foreground=self.colors["accent"], font=("Segoe UI", 13, "bold"))
        self.style.configure("SubHeader.TLabel", background=self.colors["card_bg"], foreground=self.colors["primary"], font=("Segoe UI", 10, "bold"))
        self.style.configure("TCheckbutton", background=self.colors["card_bg"], foreground=self.colors["text"], font=("Segoe UI", 9))
        self.style.map("TCheckbutton", background=[("active", self.colors["card_bg"])])

        self.style.configure("TProgressbar", thickness=10, troughcolor=self.colors["card_border"], background=self.colors["primary"])

    def _build_ui(self):
        # Header banner
        header_frame = ttk.Frame(self)
        header_frame.pack(fill="x", padx=16, pady=(12, 6))

        title_lbl = ttk.Label(header_frame, text="⚡ AutoTyper Pro", style="Header.TLabel", font=("Segoe UI", 15, "bold"))
        title_lbl.pack(side="left")

        # Session badge (Wayland or X11)
        session_type = os.environ.get("XDG_SESSION_TYPE", "unknown").upper()
        badge_text = f"Session: {session_type}"
        badge_color = "#f38ba8" if "WAYLAND" in session_type else "#a6e3a1"
        session_lbl = tk.Label(header_frame, text=badge_text, bg="#313244", fg=badge_color, font=("Segoe UI", 8, "bold"), padx=8, pady=2)
        session_lbl.pack(side="right")

        # --- Top Section: Text Editor / Input ---
        input_card = ttk.Frame(self, style="Card.TFrame", padding=10)
        input_card.pack(fill="both", expand=True, padx=16, pady=6)

        # Input Card Header
        input_hdr = ttk.Frame(input_card, style="Card.TFrame")
        input_hdr.pack(fill="x", pady=(0, 6))

        ttk.Label(input_hdr, text="Text to Auto-Type:", style="SubHeader.TLabel").pack(side="left")

        self.stats_lbl = ttk.Label(input_hdr, text="0 lines | 0 chars", style="Card.TLabel", foreground=self.colors["text_muted"])
        self.stats_lbl.pack(side="right")

        # Buttons on toolbar
        tb_frame = ttk.Frame(input_card, style="Card.TFrame")
        tb_frame.pack(fill="x", pady=(0, 6))

        btn_open = tk.Button(tb_frame, text="📂 Load File", bg="#313244", fg="#cdd6f4", activebackground="#45475a",
                             activeforeground="#ffffff", relief="flat", font=("Segoe UI", 9), command=self._load_file, padx=8, pady=2)
        btn_open.pack(side="left", padx=(0, 6))

        btn_paste = tk.Button(tb_frame, text="📋 Paste Clipboard", bg="#313244", fg="#cdd6f4", activebackground="#45475a",
                              activeforeground="#ffffff", relief="flat", font=("Segoe UI", 9), command=self._paste_clipboard, padx=8, pady=2)
        btn_paste.pack(side="left", padx=(0, 6))

        btn_clear = tk.Button(tb_frame, text="🗑️ Clear", bg="#313244", fg="#f38ba8", activebackground="#45475a",
                              activeforeground="#ffffff", relief="flat", font=("Segoe UI", 9), command=self._clear_text, padx=8, pady=2)
        btn_clear.pack(side="left")

        # Scrolled Text Box
        self.text_area = ScrolledText(input_card, wrap="none", font=("DejaVu Sans Mono", 10), bg=self.colors["input_bg"],
                                      fg=self.colors["text"], insertbackground="#89b4fa", selectbackground="#45475a",
                                      relief="flat", bd=4, undo=True)
        self.text_area.pack(fill="both", expand=True)
        self.text_area.bind("<<Modified>>", self._on_text_modified)

        # --- Settings Section ---
        settings_card = ttk.Frame(self, style="Card.TFrame", padding=10)
        settings_card.pack(fill="x", padx=16, pady=6)

        ttk.Label(settings_card, text="Configuration & Target Settings", style="SubHeader.TLabel").pack(anchor="w", pady=(0, 8))

        grid_frame = ttk.Frame(settings_card, style="Card.TFrame")
        grid_frame.pack(fill="x")

        # Row 1: Countdown & Speed
        ttk.Label(grid_frame, text="Countdown (sec):", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        self.var_countdown = tk.IntVar(value=5)
        spin_cd = tk.Spinbox(grid_frame, from_=0, to=60, textvariable=self.var_countdown, width=6, bg=self.colors["input_bg"],
                             fg=self.colors["text"], insertbackground=self.colors["text"], relief="flat", bd=2)
        spin_cd.grid(row=0, column=1, sticky="w", padx=(6, 20), pady=4)

        ttk.Label(grid_frame, text="Speed (WPM):", style="Card.TLabel").grid(row=0, column=2, sticky="w", pady=4)
        self.var_wpm = tk.DoubleVar(value=200.0)
        spin_wpm = tk.Spinbox(grid_frame, from_=50, to=800, increment=25, textvariable=self.var_wpm, width=6, bg=self.colors["input_bg"],
                              fg=self.colors["text"], insertbackground=self.colors["text"], relief="flat", bd=2)
        spin_wpm.grid(row=0, column=3, sticky="w", padx=(6, 20), pady=4)

        ttk.Label(grid_frame, text="Word Pause (s):", style="Card.TLabel").grid(row=0, column=4, sticky="w", pady=4)
        self.var_word_pause = tk.DoubleVar(value=0.03)
        spin_wp = tk.Spinbox(grid_frame, from_=0.0, to=0.5, increment=0.01, textvariable=self.var_word_pause, width=6, bg=self.colors["input_bg"],
                             fg=self.colors["text"], insertbackground=self.colors["text"], relief="flat", bd=2)
        spin_wp.grid(row=0, column=5, sticky="w", padx=(6, 0), pady=4)

        # Row 2: Checkboxes for features
        self.var_mac = tk.BooleanVar(value=True)
        cb_mac = ttk.Checkbutton(grid_frame, text="macOS Mode (clear stuck Cmd/Ctrl & avoid Home/End)", variable=self.var_mac)
        cb_mac.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 4))

        self.var_autobrace = tk.BooleanVar(value=True)
        cb_brace = ttk.Checkbutton(grid_frame, text="Auto-Brace Fix (delete editor's auto-inserted '}')", variable=self.var_autobrace)
        cb_brace.grid(row=1, column=3, columnspan=3, sticky="w", pady=(8, 4))

        # Row 3: Advanced Indentation
        self.var_indent_fix = tk.BooleanVar(value=False)
        cb_indent = ttk.Checkbutton(grid_frame, text="Clear Auto-Indent (press Home)", variable=self.var_indent_fix)
        cb_indent.grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 4))

        self.var_normalize_tabs = tk.BooleanVar(value=False)
        cb_tabs = ttk.Checkbutton(grid_frame, text="Normalize Tabs to Spaces", variable=self.var_normalize_tabs)
        cb_tabs.grid(row=2, column=3, columnspan=3, sticky="w", pady=(2, 4))

        # --- Control & Status Section ---
        ctrl_card = ttk.Frame(self, style="Card.TFrame", padding=12)
        ctrl_card.pack(fill="x", padx=16, pady=(6, 12))

        # Progress bar
        self.prog_bar = ttk.Progressbar(ctrl_card, orient="horizontal", mode="determinate")
        self.prog_bar.pack(fill="x", pady=(0, 8))

        # Status Label / Countdown Display
        self.status_lbl = tk.Label(ctrl_card, text="Ready. Click 'Start AutoTyper' to begin.", bg=self.colors["card_bg"],
                                   fg="#a6e3a1", font=("Segoe UI", 11, "bold"))
        self.status_lbl.pack(pady=(0, 10))

        # Action Buttons
        btn_frame = ttk.Frame(ctrl_card, style="Card.TFrame")
        btn_frame.pack()

        self.btn_start = tk.Button(btn_frame, text="▶ Start AutoTyper", bg="#a6e3a1", fg="#181825", activebackground="#94e2d5",
                                   font=("Segoe UI", 11, "bold"), relief="flat", padx=18, pady=6, command=self._start_autotyper)
        self.btn_start.pack(side="left", padx=8)

        self.btn_pause = tk.Button(btn_frame, text="⏸ Pause", bg="#f9e2af", fg="#181825", activebackground="#fab387",
                                   font=("Segoe UI", 11, "bold"), relief="flat", padx=18, pady=6, state="disabled", command=self._toggle_pause)
        self.btn_pause.pack(side="left", padx=8)

        self.btn_stop = tk.Button(btn_frame, text="⏹ Stop", bg="#f38ba8", fg="#181825", activebackground="#eba0ac",
                                  font=("Segoe UI", 11, "bold"), relief="flat", padx=18, pady=6, state="disabled", command=self._stop_autotyper)
        self.btn_stop.pack(side="left", padx=8)

        # Hotkey legend
        hint_lbl = ttk.Label(ctrl_card, text="Global Shortcuts: INSERT or Ctrl+Enter = Pause/Resume | ESC = Stop",
                             style="Card.TLabel", foreground=self.colors["text_muted"], font=("Segoe UI", 8))
        hint_lbl.pack(pady=(8, 0))

    def _setup_hotkey_listener(self):
        ctrl_pressed = [False]

        def on_press(key):
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
                ctrl_pressed[0] = True
                return

            if key == keyboard.Key.insert or (key == keyboard.Key.enter and ctrl_pressed[0]):
                self.after(0, self._toggle_pause)
            elif key == keyboard.Key.esc:
                self.after(0, self._stop_autotyper)

        def on_release(key):
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
                ctrl_pressed[0] = False

        try:
            from pynput import keyboard as kb
            self.listener = kb.Listener(on_press=on_press, on_release=on_release)
            self.listener.daemon = True
            self.listener.start()
        except Exception:
            pass

    def _on_text_modified(self, event=None):
        if self.text_area.edit_modified():
            self._update_stats()
            self.text_area.edit_modified(False)

    def _update_stats(self):
        text = self.text_area.get("1.0", "end-1c")
        chars = len(text)
        lines = len(text.splitlines()) if text else 0
        self.stats_lbl.config(text=f"{lines} lines | {chars} chars")

    def _load_file(self):
        path = filedialog.askopenfilename(filetypes=[("Text/Code Files", "*.txt *.cpp *.py *.java *.c *.js *.ts *.html"), ("All Files", "*.*")])
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.text_area.delete("1.0", "end")
                self.text_area.insert("1.0", content)
                self._update_stats()
                self.status_lbl.config(text=f"Loaded: {os.path.basename(path)}", fg="#89b4fa")
            except Exception as e:
                messagebox.showerror("Error Loading File", str(e))

    def _paste_clipboard(self):
        try:
            content = self.clipboard_get()
            self.text_area.insert("insert", content)
            self._update_stats()
        except Exception:
            pass

    def _clear_text(self):
        self.text_area.delete("1.0", "end")
        self._update_stats()

    def _start_autotyper(self):
        text = self.text_area.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showwarning("No Text", "Please enter or paste the text you want to auto-type!")
            return

        self.btn_start.config(state="disabled")
        self.btn_pause.config(state="normal", text="⏸ Pause")
        self.btn_stop.config(state="normal")
        self.stop_event.clear()
        self.running_event.clear()

        self.typing_thread = threading.Thread(target=self._run_typing_worker, args=(text,), daemon=True)
        self.typing_thread.start()

    def _toggle_pause(self):
        if not self.typing_thread or not self.typing_thread.is_alive():
            return

        if self.running_event.is_set():
            self.running_event.clear()
            release_all_modifiers()
            self.status_lbl.config(text="⏸ PAUSED. Press 'Resume' or INSERT / Ctrl+Enter to continue.", fg="#f9e2af")
            self.btn_pause.config(text="▶ Resume", bg="#89b4fa")
        else:
            release_all_modifiers()
            self.running_event.set()
            self.status_lbl.config(text="Typing in progress...", fg="#a6e3a1")
            self.btn_pause.config(text="⏸ Pause", bg="#f9e2af")

    def _stop_autotyper(self):
        self.stop_event.set()
        self.running_event.clear()
        release_all_modifiers()
        self.status_lbl.config(text="⏹ Stopped.", fg="#f38ba8")
        self.btn_start.config(state="normal")
        self.btn_pause.config(state="disabled", text="⏸ Pause", bg="#f9e2af")
        self.btn_stop.config(state="disabled")
        self.prog_bar["value"] = 0

    def _run_typing_worker(self, text: str):
        countdown = self.var_countdown.get()
        wpm = max(10.0, self.var_wpm.get())
        word_pause = max(0.0, self.var_word_pause.get())
        auto_brace_fix = self.var_autobrace.get()
        is_mac = self.var_mac.get()
        indent_fix = self.var_indent_fix.get()
        normalize_tabs = self.var_normalize_tabs.get()
        tab_size = 4
        post_enter_wait = 0.14
        jitter = 0.06

        # Step 1: Countdown
        for sec in range(countdown, 0, -1):
            if self.stop_event.is_set():
                return
            self.after(0, lambda s=sec: self.status_lbl.config(
                text=f"⏳ SWITCH TO YOUR WINDOW! Starting in {s}s...", fg="#fab387"
            ))
            time.sleep(1)

        if self.stop_event.is_set():
            return

        # Prepare typing
        release_all_modifiers()
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.008

        cps = (wpm * 5.0) / 60.0
        base_interval = 1.0 / max(1e-6, cps)

        lines = split_lines_preserve(text)
        total_lines = len(lines)
        total_chars = sum(len(i) + len(c) + len(le) for i, c, le in lines)

        self.running_event.set()
        self.after(0, lambda: self.status_lbl.config(text="🚀 Typing started!", fg="#a6e3a1"))
        self.after(0, lambda: self.prog_bar.config(maximum=total_chars, value=0))

        chars_typed = 0

        def type_char(ch: str):
            nonlocal chars_typed
            if self.stop_event.is_set():
                return False

            while not self.running_event.is_set():
                if self.stop_event.is_set():
                    return False
                time.sleep(0.03)

            pyautogui.typewrite(ch, _pause=False)
            chars_typed += 1

            if ch == "{" and auto_brace_fix:
                time.sleep(0.04)
                pyautogui.press('delete')

            if ch == " " and word_pause > 0:
                time.sleep(word_pause)
            else:
                sigma = base_interval * jitter
                dt = max(0.0, random.gauss(base_interval, sigma))
                time.sleep(dt)

            return True

        for line_idx, (indent, content, ending) in enumerate(lines):
            if self.stop_event.is_set():
                break

            while not self.running_event.is_set():
                if self.stop_event.is_set():
                    break
                time.sleep(0.03)

            if line_idx % 5 == 0:
                release_all_modifiers()

            pct = int((chars_typed / max(1, total_chars)) * 100)
            self.after(0, lambda li=line_idx+1, tl=total_lines, p=pct, ct=chars_typed: [
                self.status_lbl.config(text=f"⌨️ Typing line {li}/{tl} ({p}%)", fg="#89b4fa"),
                self.prog_bar.config(value=ct)
            ])

            # Indent handling
            if indent_fix and not is_mac:
                pyautogui.press('home')
                time.sleep(0.01)

            indent_str = make_indent_string(indent, normalize_tabs, tab_size)
            for ch in indent_str:
                if not type_char(ch):
                    break

            for ch in content:
                if not type_char(ch):
                    break

            if ending:
                if not is_mac and not indent_fix:
                    pass  # keep cursor at end naturally
                pyautogui.press('enter')
                time.sleep(post_enter_wait)

        release_all_modifiers()

        if not self.stop_event.is_set():
            self.after(0, lambda: [
                self.status_lbl.config(text=f"🎉 Done! Completed {total_lines} lines ({total_chars} chars).", fg="#a6e3a1"),
                self.prog_bar.config(value=total_chars),
                self.btn_start.config(state="normal"),
                self.btn_pause.config(state="disabled", text="⏸ Pause", bg="#f9e2af"),
                self.btn_stop.config(state="disabled")
            ])

    def _on_close(self):
        self.stop_event.set()
        release_all_modifiers()
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
        self.destroy()

if __name__ == "__main__":
    app = AutoTyperApp()
    app.mainloop()
