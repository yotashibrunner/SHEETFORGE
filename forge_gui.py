"""
forge_gui.py — a small windowed front-end for SheetForge.

Packaged to SheetForge.exe with PyInstaller (see build_exe.ps1). The .exe is a
launcher: it drives the project's venv Python to run forge_trends.py, streaming
output into a log pane. It does NOT run the pipeline in-process, because the forge
spawns its own `sys.executable` subprocesses (forge_batch -> recalc) that must be a
real Python interpreter, not the frozen exe.

Requirements at runtime: keep SheetForge.exe in the project folder (next to
forge_trends.py and .venv), and have LibreOffice installed. See README.
"""
import os
import sys
import threading
import queue
import subprocess

# --- environment discovery ----------------------------------------------------
def project_dir():
    # When frozen by PyInstaller, sys.executable is the .exe; use its folder so the
    # app finds forge_trends.py / .venv sitting alongside it. Otherwise use this file.
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


PROJ = project_dir()


def find_python():
    venv = os.path.join(PROJ, ".venv", "Scripts", "python.exe")
    return venv if os.path.exists(venv) else "python"


def find_libreoffice():
    for p in (r"C:\Program Files\LibreOffice\program",
              r"C:\Program Files (x86)\LibreOffice\program"):
        if os.path.exists(os.path.join(p, "soffice.exe")):
            return p
    return None


def child_env(api_key):
    env = dict(os.environ)
    lo = find_libreoffice()
    if lo:
        env["PATH"] = lo + os.pathsep + env.get("PATH", "")
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    env["PYTHONUTF8"] = "1"          # status glyphs print on any console code page
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def preflight():
    """Human-readable environment report (used by --check and the GUI status line)."""
    py = find_python()
    return {
        "project": PROJ,
        "python": py,
        "python_ok": (py != "python") and os.path.exists(py),
        "forge_trends": os.path.exists(os.path.join(PROJ, "forge_trends.py")),
        "libreoffice": find_libreoffice(),
        "api_key_env": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


# --- headless self-check (no GUI) ---------------------------------------------
if "--check" in sys.argv:
    info = preflight()
    for k, v in info.items():
        print(f"{k:14}: {v}")
    sys.exit(0 if info["forge_trends"] else 1)


# --- GUI ----------------------------------------------------------------------
import tkinter as tk
from tkinter import ttk, scrolledtext


class ForgeApp:
    def __init__(self, root):
        self.root = root
        self.proc = None
        self.q = queue.Queue()
        root.title("SheetForge")
        root.geometry("760x560")
        root.minsize(640, 480)

        pad = {"padx": 8, "pady": 4}
        top = ttk.Frame(root)
        top.pack(fill="x", **pad)

        ttk.Label(top, text="Anthropic API key:").grid(row=0, column=0, sticky="w")
        self.key_var = tk.StringVar(value=os.environ.get("ANTHROPIC_API_KEY", ""))
        self.key_entry = ttk.Entry(top, textvariable=self.key_var, show="•", width=48)
        self.key_entry.grid(row=0, column=1, columnspan=3, sticky="we", padx=4)
        ttk.Label(top, text="(only needed for builds; set ANTHROPIC_API_KEY to skip)",
                  foreground="#666").grid(row=1, column=1, columnspan=3, sticky="w")

        ttk.Label(top, text="Products (--top):").grid(row=2, column=0, sticky="w")
        self.top_var = tk.IntVar(value=2)
        ttk.Spinbox(top, from_=1, to=50, textvariable=self.top_var, width=6).grid(
            row=2, column=1, sticky="w", padx=4)
        top.columnconfigure(1, weight=1)

        btns = ttk.Frame(root)
        btns.pack(fill="x", **pad)
        self.run_buttons = [
            ttk.Button(btns, text="Offline test", command=self.offline_test),
            ttk.Button(btns, text="Build (offline)", command=self.build_offline),
            ttk.Button(btns, text="Build (live)", command=self.build_live),
        ]
        for b in self.run_buttons:
            b.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(btns, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        ttk.Button(btns, text="Open output folder", command=self.open_catalog).pack(
            side="right", padx=4)

        self.log = scrolledtext.ScrolledText(root, wrap="word", height=20,
                                             font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=8, pady=4)
        self.log.configure(state="disabled")

        self.status = tk.StringVar()
        ttk.Label(root, textvariable=self.status, anchor="w",
                  relief="sunken").pack(fill="x", side="bottom")

        self._report_env()
        self.root.after(100, self._drain)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- env / logging --------------------------------------------------------
    def _report_env(self):
        info = preflight()
        if not info["forge_trends"]:
            self._write(f"!! forge_trends.py not found in {PROJ}\n"
                        f"   Keep SheetForge.exe inside the project folder.\n")
        if not info["libreoffice"]:
            self._write("!! LibreOffice not found — the QA gate will reject every build "
                        "(total_errors: -1). Install it; see README.\n")
        py = "venv python" if info["python_ok"] else "system python (no .venv)"
        lo = "LibreOffice ✓" if info["libreoffice"] else "LibreOffice ✗"
        self.status.set(f"{lo}   |   {py}   |   {PROJ}")

    def _write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain(self):
        try:
            while True:
                self._write(self.q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    # --- run actions ----------------------------------------------------------
    def offline_test(self):
        self._launch(["--offline"])

    def build_offline(self):
        self._launch(["--offline", "--build", "--top", str(self.top_var.get())])

    def build_live(self):
        self._launch(["--build", "--top", str(self.top_var.get())])

    def _launch(self, forge_args):
        if self.proc is not None:
            return
        if "--build" in forge_args and not (self.key_var.get().strip()
                                            or os.environ.get("ANTHROPIC_API_KEY")):
            self._write("!! A build needs an Anthropic API key — paste it in the field above.\n")
            return
        cmd = [find_python(), "forge_trends.py"] + forge_args
        self._set_running(True)
        self._write(f"\n$ forge_trends.py {' '.join(forge_args)}\n")
        env = child_env(self.key_var.get().strip())
        threading.Thread(target=self._worker, args=(cmd, env), daemon=True).start()

    def _worker(self, cmd, env):
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=PROJ, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in self.proc.stdout:
                self.q.put(line)
            self.proc.wait()
            self.q.put(f"\n[exit code {self.proc.returncode}]\n")
        except Exception as e:
            self.q.put(f"\n!! failed to launch: {e}\n")
        finally:
            self.proc = None
            self.root.after(0, lambda: self._set_running(False))

    def _set_running(self, running):
        for b in self.run_buttons:
            b.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def stop(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.q.put("\n[stopped]\n")
            except Exception:
                pass

    def open_catalog(self):
        out = os.path.join(PROJ, "catalog")
        os.makedirs(out, exist_ok=True)
        os.startfile(out)  # noqa: Windows-only, intentional

    def _on_close(self):
        self.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    ForgeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
