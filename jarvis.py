import os, io, re, time, math, queue, threading, datetime, webbrowser, winsound
import json, subprocess, difflib
import tkinter as tk
from urllib.parse import quote
import ollama, pyttsx3, pyautogui, sounddevice as sd, speech_recognition as sr

MIC_INDEX = 6          # ನಿನಗೆ work ಆದ number (6, 12, ಅಥವಾ 20)
SECONDS = 6
LANG = "en-IN"
WAKE_ENABLED = True    # False = hover ಮಾತ್ರ (mic ಯಾವಾಗಲೂ ಕೇಳುವುದಿಲ್ಲ)
WAKE_WORDS = ["jarvis", "jarves", "jarvas", "jarvish", "travis"]
MODEL = "qwen2.5:3b"
VISION_MODEL = "qwen2.5vl:3b"
GREETING = "Hello sir, what can I do for you?"
KEEP_MINUTES = 60      # ಇಷ್ಟು ನಿಮಿಷಕ್ಕಿಂತ ಹಳೆಯ screenshots delete ಆಗುತ್ತವೆ

SHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")

r = sr.Recognizer()
tts = None
history = [{"role": "system",
            "content": "You are Jarvis, a concise helpful assistant. Keep answers under 3 sentences."}]
events = queue.Queue()
S = {"state": "sleep", "text": ""}

APPS = {
    "chrome": "chrome", "calculator": "calc", "notepad": "notepad",
    "vs code": "code", "spotify": "spotify", "paint": "mspaint",
}

SCREEN_WORDS = ("my screen", "the screen", "on screen", "this screen", "what do you see",
                "look at this", "read this", "explain this", "what is this", "what's this",
                "what is on", "what's on")

SHORTCUTS = {
    "copy": ("ctrl", "c"), "paste": ("ctrl", "v"), "cut": ("ctrl", "x"),
    "select all": ("ctrl", "a"), "undo": ("ctrl", "z"), "redo": ("ctrl", "y"),
    "save": ("ctrl", "s"), "find": ("ctrl", "f"),
    "new tab": ("ctrl", "t"), "close tab": ("ctrl", "w"), "next tab": ("ctrl", "tab"),
    "refresh": ("f5",), "go back": ("alt", "left"),
    "switch window": ("alt", "tab"), "show desktop": ("win", "d"),
    "minimize": ("win", "down"), "maximize": ("win", "up"),
}

KEYMAP = {"control": "ctrl", "windows": "win", "escape": "esc", "return": "enter",
          "page up": "pageup", "page down": "pagedown"}


# ---------------- screenshot cleanup ----------------
def cleanup_screenshots():
    limit = time.time() - KEEP_MINUTES * 60
    try:
        if not os.path.isdir(SHOT_DIR):
            return
        for name in os.listdir(SHOT_DIR):
            if name.startswith("shot_") and name.endswith(".png"):
                path = os.path.join(SHOT_DIR, name)
                if os.path.getmtime(path) < limit:
                    os.remove(path)
    except Exception as e:
        print("Cleanup error:", e)


def cleanup_loop():
    while True:
        cleanup_screenshots()
        time.sleep(300)


# ---------------- installed apps ----------------
APP_INDEX = {}


def build_app_index():
    idx = {}
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json"],
            capture_output=True, text=True, timeout=60, creationflags=0x08000000).stdout
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        for a in data:
            idx[a["Name"].lower()] = a["AppID"]
    except Exception as e:
        print("App scan error:", e)
    return idx


def load_apps():
    APP_INDEX.update(build_app_index())
    print("Apps found:", len(APP_INDEX))


def find_app(name):
    n = name.replace(" ", "")
    keys = {k.replace(" ", ""): k for k in APP_INDEX}
    if not keys:
        return None
    if n in keys:
        return keys[n]
    cands = [k for kn, k in keys.items() if n in kn]
    if cands:
        return min(cands, key=len)
    m = difflib.get_close_matches(n, list(keys), n=1, cutoff=0.6)
    return keys[m[0]] if m else None


# ---------------- state ----------------
def set_state(s, text=""):
    S["state"] = s
    S["text"] = text


def set_sleep():
    if events.empty():
        set_state("sleep")


# ---------------- voice ----------------
def speak(t):
    print("Jarvis:", t)
    set_state("speaking", t)
    tts.say(t)
    tts.runAndWait()


def record(seconds, interruptible=False):
    info = sd.query_devices(MIC_INDEX, "input")
    rate = int(info["default_samplerate"])
    rec = sd.rec(int(seconds * rate), samplerate=rate, channels=1,
                 dtype="int16", device=MIC_INDEX)
    end = time.time() + seconds
    while time.time() < end:
        if interruptible and not events.empty():
            sd.stop()
            return None
        time.sleep(0.05)
    sd.wait()
    return sr.AudioData(rec.tobytes(), rate, 2)


def get_text(interruptible=False):
    audio = record(SECONDS, interruptible)
    if audio is None:
        return None
    try:
        return r.recognize_google(audio, language=LANG).lower()
    except sr.UnknownValueError:
        return ""
    except Exception as e:
        print("Error:", e)
        return ""


def strip_wake(t):
    for w in WAKE_WORDS:
        if t.startswith(w):
            return t[len(w):].strip(" ,.")
    return t.strip(" ,.")


def confirm(prompt):
    speak(prompt + " Say yes to confirm.")
    set_state("listening", "Say yes to confirm")
    winsound.Beep(900, 120)
    ans = get_text() or ""
    return "yes" in ans


# ---------------- screen vision ----------------
def grab_screen_png():
    img = pyautogui.screenshot()
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def screen_question(q):
    speak("Looking at your screen. Please wait, this can take a minute.")
    set_state("thinking", "Looking at your screen...")
    try:
        png = grab_screen_png()
        resp = ollama.chat(model=VISION_MODEL, messages=[{
            "role": "user",
            "content": q + "\nAnswer briefly in 2 or 3 sentences.",
            "images": [png],
        }])
        speak(resp["message"]["content"])
    except Exception as e:
        print("Vision error:", e)
        speak("Vision failed. Make sure you ran: ollama pull qwen2.5vl:3b")


# ---------------- keyboard / mouse / windows ----------------
def press_keys(spec):
    spec = spec.replace(" plus ", " ")
    for k, v in (("page up", "pageup"), ("page down", "pagedown")):
        spec = spec.replace(k, v)
    keys = [KEYMAP.get(t, t) for t in spec.split()]
    if not keys or any(k not in pyautogui.KEYBOARD_KEYS for k in keys):
        return False
    if len(keys) == 1:
        pyautogui.press(keys[0])
    else:
        pyautogui.hotkey(*keys)
    return True


def click_by_name(name, mode="click"):
    import win32gui
    from pywinauto import Desktop
    hwnd = win32gui.GetForegroundWindow()
    win = Desktop(backend="uia").window(handle=hwnd)
    best = None
    for el in win.descendants():
        try:
            t = (el.window_text() or "").lower()
            if t and name in t and el.is_visible():
                if best is None or len(t) < len(best[0]):
                    best = (t, el)
        except Exception:
            pass
    if not best:
        return None
    el = best[1]
    if mode == "double":
        el.double_click_input()
    elif mode == "right":
        el.right_click_input()
    else:
        el.click_input()
    return best[0]


def focus_window(name):
    import win32gui, win32con
    found = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            t = win32gui.GetWindowText(h).lower()
            if t and name in t:
                found.append(h)

    win32gui.EnumWindows(cb, None)
    if not found:
        return None
    h = found[0]
    if win32gui.IsIconic(h):
        win32gui.ShowWindow(h, win32con.SW_RESTORE)
    try:
        pyautogui.press("alt")
        win32gui.SetForegroundWindow(h)
    except Exception as e:
        print("Focus error:", e)
    return win32gui.GetWindowText(h)


def do_click(c, prefix, mode):
    name = c[len(prefix):].strip()
    if not name:
        speak("Click what?")
        return True
    try:
        hit = click_by_name(name, mode)
    except Exception as e:
        print("Click error:", e)
        speak("I could not click that.")
        return True
    speak(f"Clicked {hit}" if hit else f"I could not find {name} on this window")
    return True


# ---------------- commands ----------------
def timer_done(msg):
    print("\n*** TIMER DONE:", msg, "***")
    for _ in range(3):
        winsound.Beep(1000, 600)


def handle(c):
    """True = command handled. False = send to AI."""
    if c in ("exit", "quit", "stop", "bye", "goodbye"):
        speak("Goodbye")
        os._exit(0)

    # --- screenshot file ---
    if "screenshot" in c:
        os.makedirs(SHOT_DIR, exist_ok=True)
        fn = os.path.join(SHOT_DIR,
                          datetime.datetime.now().strftime("shot_%Y%m%d_%H%M%S.png"))
        pyautogui.screenshot().save(fn)
        cleanup_screenshots()
        speak("Screenshot saved")
        return True

    # --- questions about the screen ---
    if any(k in c for k in SCREEN_WORDS):
        screen_question(c)
        return True

    # --- keyboard ---
    if c.startswith("type "):
        pyautogui.write(c[5:], interval=0.02)
        speak("Typed")
        return True

    if c.startswith("press "):
        if press_keys(c[6:].strip()):
            speak("Done")
        else:
            speak("I do not know that key")
        return True

    # --- shortcuts (copy, paste, new tab, ...) ---
    sc = next((k for k in SHORTCUTS if c == k or (" " in k and k in c)), None)
    if sc:
        m = re.search(r" (?:in|on) ([a-z0-9 ]+)$", c)
        if m:
            focus_window(m.group(1).strip())
            time.sleep(0.5)
        keys = ("ctrl", "n") if sc == "new tab" and "notepad" in c else SHORTCUTS[sc]
        pyautogui.hotkey(*keys)
        speak("Done")
        return True

    if c == "close window":
        if confirm("Close the current window?"):
            pyautogui.hotkey("alt", "f4")
            speak("Closed")
        else:
            speak("Cancelled")
        return True

    # --- mouse ---
    if c.startswith("double click "):
        return do_click(c, "double click ", "double")
    if c.startswith("right click "):
        return do_click(c, "right click ", "right")
    if c.startswith("click "):
        return do_click(c, "click ", "click")

    if c.startswith("scroll"):
        pyautogui.moveTo(sw // 2, sh // 2)
        pyautogui.scroll(-600 if "down" in c else 600)
        speak("Done")
        return True

    # --- windows ---
    if c.startswith("switch to "):
        name = c[10:].strip()
        got = focus_window(name)
        speak(f"Switched to {got}" if got else f"I could not find a window named {name}")
        return True

    # --- apps ---
    if c.startswith("open "):
        name = c[5:].strip()
        if name == "youtube":
            webbrowser.open("https://youtube.com")
            speak("Opening YouTube")
            return True
        if name == "google":
            webbrowser.open("https://google.com")
            speak("Opening Google")
            return True
        if name in APPS:
            os.system(f"start {APPS[name]}")
            speak(f"Opening {name}")
            return True
        app = find_app(name)
        if app:
            subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + APP_INDEX[app]])
            speak(f"Opening {app}")
            return True
        speak(f"I could not find {name}")
        return True

    if c.startswith("search "):
        q = c[7:]
        webbrowser.open("https://www.google.com/search?q=" + quote(q))
        speak(f"Searching {q}")
        return True

    if c.startswith("play "):
        q = c[5:]
        webbrowser.open("https://www.youtube.com/results?search_query=" + quote(q))
        speak(f"Playing {q} on YouTube")
        return True

    if "weather" in c:
        webbrowser.open("https://www.google.com/search?q=weather")
        speak("Showing weather")
        return True

    if "what time" in c or c == "time" or "the time" in c:
        speak(datetime.datetime.now().strftime("It is %I:%M %p"))
        return True

    if "what date" in c or "today's date" in c or "the date" in c:
        speak(datetime.datetime.now().strftime("Today is %d %B %Y"))
        return True

    if "volume up" in c:
        for _ in range(5):
            pyautogui.press("volumeup")
        speak("Volume up")
        return True
    if "volume down" in c:
        for _ in range(5):
            pyautogui.press("volumedown")
        speak("Volume down")
        return True
    if c == "mute" or "mute the" in c:
        pyautogui.press("volumemute")
        speak("Done")
        return True

    if c.startswith("note "):
        with open("notes.txt", "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M} - {c[5:]}\n")
        speak("Note saved")
        return True

    m = re.search(r"(?:timer|remind me).*?(\d+)\s*(second|minute|hour)", c)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        secs = n * {"second": 1, "minute": 60, "hour": 3600}[unit]
        threading.Timer(secs, timer_done, args=(c,)).start()
        speak(f"Timer set for {n} {unit}s")
        return True

    return False


def ask_ai(q):
    history.append({"role": "user", "content": q})
    try:
        a = ollama.chat(model=MODEL, messages=history)["message"]["content"]
    except Exception as e:
        print("Ollama error:", e)
        history.pop()
        speak("I cannot reach Ollama. Please start it.")
        return
    history.append({"role": "assistant", "content": a})
    speak(a)


def run_command(cmd):
    set_state("thinking", cmd + " ...")
    if not handle(cmd):
        ask_ai(cmd)


# ---------------- brain thread ----------------
def interact():
    """Cursor hover: greet, then listen for one command."""
    set_state("awake")
    speak(GREETING)
    set_state("listening", "Listening...")
    winsound.Beep(900, 120)
    text = get_text()
    cmd = strip_wake(text or "")
    if cmd:
        run_command(cmd)
    else:
        speak("I did not hear anything.")
    time.sleep(3)
    set_sleep()


def loop_once():
    if not events.empty():
        while not events.empty():
            events.get()
        interact()
        return

    if not WAKE_ENABLED:
        time.sleep(0.1)
        return

    set_sleep()
    text = get_text(interruptible=True)
    if not text:
        return
    print("Heard:", text)
    wake = next((w for w in WAKE_WORDS if w in text), None)
    if not wake:
        return

    cmd = text.split(wake, 1)[1].strip(" ,.")
    set_state("awake")
    if not cmd:
        speak("Yes?")
        set_state("listening", "Listening...")
        winsound.Beep(900, 120)
        cmd = (get_text() or "").strip(" ,.")
        if not cmd:
            set_sleep()
            return
    run_command(cmd)
    time.sleep(3)
    set_sleep()


def brain():
    global tts
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass
    tts = pyttsx3.init()
    while True:
        try:
            loop_once()
        except Exception as e:
            print("Error:", e)
            set_state("sleep")
            time.sleep(1)


# ---------------- robot pet (UI) ----------------
W, H = 280, 170
CX = 215
BG = "#010101"
T0 = time.time()

root = tk.Tk()
root.overrideredirect(True)
root.attributes("-topmost", True)
root.config(bg=BG)
root.attributes("-transparentcolor", BG)
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
root.geometry(f"{W}x{H}+{sw - W - 40}+{sh - H - 120}")
cv = tk.Canvas(root, width=W, height=H, bg=BG, highlightthickness=0)
cv.pack()

GLOW = {"sleep": "#2a6f86", "awake": "#00eaff", "listening": "#00ff88",
        "thinking": "#ffcc00", "speaking": "#00eaff"}


def rrect(x1, y1, x2, y2, rad=10, **kw):
    pts = [x1 + rad, y1, x2 - rad, y1, x2, y1, x2, y1 + rad,
           x2, y2 - rad, x2, y2, x2 - rad, y2, x1 + rad, y2,
           x1, y2, x1, y2 - rad, x1, y1 + rad, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


frame = {"n": 0}


def draw():
    t = time.time() - T0
    st = S["state"]
    txt = S["text"]
    awake = st != "sleep"
    glow = GLOW.get(st, "#00eaff")
    cv.delete("all")

    bob = math.sin(t * (4 if awake else 1.6)) * (3 if awake else 2)
    hop = 0
    ph = t % 9
    if not awake and ph < 0.6:
        hop = -abs(math.sin(ph / 0.6 * math.pi)) * 14
    y = bob + hop
    pulse = (math.sin(t * 6) + 1) / 2

    # shadow
    sw_ = 30 + hop * 0.4
    cv.create_oval(CX - sw_, 154, CX + sw_, 162, fill="#0c0c0c", outline="")

    # antenna
    sway = math.sin(t * (6 if awake else 2)) * 5
    cv.create_line(CX, 32 + y, CX + sway, 16 + y, fill="#7a8aa8", width=3)
    if awake:
        bulb = glow
    else:
        bulb = "#ff4d4d" if math.sin(t * 2) > 0 else "#662222"
    cv.create_oval(CX - 5 + sway, 10 + y, CX + 5 + sway, 20 + y, fill=bulb, outline="")

    # arms
    arm_c = "#7a8aa8"
    lax, lay = CX - 42, 118 + y + math.sin(t * 1.5) * 3
    cv.create_line(CX - 27, 96 + y, lax, lay, fill=arm_c, width=6, capstyle="round")
    cv.create_oval(lax - 4, lay - 4, lax + 4, lay + 4, fill=arm_c, outline="")
    if st in ("awake", "speaking"):
        rax, ray = CX + 44, 76 + y + math.sin(t * 9) * 7      # waving
    else:
        rax, ray = CX + 42, 118 + y - math.sin(t * 1.5) * 3
    cv.create_line(CX + 27, 96 + y, rax, ray, fill=arm_c, width=6, capstyle="round")
    cv.create_oval(rax - 4, ray - 4, rax + 4, ray + 4, fill=arm_c, outline="")

    # body
    rrect(CX - 27, 88 + y, CX + 27, 132 + y, 10, fill="#2b3a55", outline=glow, width=2)
    chest = 5 + (pulse * 2 if awake else 0)
    cv.create_oval(CX - chest, 108 + y - chest, CX + chest, 108 + y + chest,
                   fill=glow, outline="")

    # feet
    rrect(CX - 20, 134 + y, CX - 4, 146 + y, 4, fill=arm_c, outline="")
    rrect(CX + 4, 134 + y, CX + 20, 146 + y, 4, fill=arm_c, outline="")

    # head
    rrect(CX - 35, 30 + y, CX + 35, 82 + y, 14, fill="#34476b", outline=glow, width=2)

    # eyes
    if awake:
        blink = (t % 4.5) < 0.15
        look = math.sin(t * 1.3) * 3 if st == "awake" else 0
        eh = 2 if blink else 14
        for ex in (CX - 24, CX + 10):
            cy = 55 + y
            cv.create_oval(ex + look, cy - eh / 2, ex + 14 + look, cy + eh / 2,
                           fill=glow, outline="")
    else:
        for ex in (CX - 24, CX + 10):
            cv.create_line(ex, 56 + y, ex + 14, 56 + y, fill=glow, width=3, capstyle="round")

    # mouth
    if st == "speaking":
        mh = 3 + abs(math.sin(t * 14)) * 7
        cv.create_oval(CX - 8, 66 + y, CX + 8, 66 + y + mh, fill=glow, outline="")
    elif st in ("awake", "listening"):
        cv.create_arc(CX - 9, 62 + y, CX + 9, 76 + y, start=200, extent=140,
                      style="arc", outline=glow, width=2)
    else:
        cv.create_line(CX - 7, 71 + y, CX + 7, 71 + y, fill=glow, width=2)

    # Zzz
    if not awake:
        for i in range(3):
            p = (t * 0.5 + i / 3) % 1
            cv.create_text(CX + 40 + p * 14, 30 + y - p * 26, text="z", fill="#8fd3ff",
                           font=("Segoe UI", int(8 + p * 8), "bold"))

    # speech bubble
    if txt:
        shown = txt if len(txt) < 110 else txt[:107] + "..."
        rrect(6, 14, 150, 114, 12, fill="#0f1c2e", outline=glow, width=2)
        cv.create_text(78, 64, text=shown, fill="white", width=128, font=("Segoe UI", 9))

    frame["n"] += 1
    if frame["n"] % 50 == 0:
        root.attributes("-topmost", True)
        root.lift()
    root.after(40, draw)


def on_enter(e):
    if S["state"] == "sleep":
        S["state"] = "awake"
        S["text"] = ""
        events.put("hover")


drag = {}


def on_press(e):
    drag["x"], drag["y"] = e.x, e.y


def on_motion(e):
    nx = root.winfo_x() + e.x - drag["x"]
    ny = root.winfo_y() + e.y - drag["y"]
    root.geometry(f"+{nx}+{ny}")


menu = tk.Menu(root, tearoff=0)
menu.add_command(label="Quit Jarvis", command=lambda: os._exit(0))

cv.bind("<Enter>", on_enter)
cv.bind("<ButtonPress-1>", on_press)
cv.bind("<B1-Motion>", on_motion)
cv.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

threading.Thread(target=cleanup_loop, daemon=True).start()
threading.Thread(target=load_apps, daemon=True).start()
threading.Thread(target=brain, daemon=True).start()
draw()
root.mainloop()