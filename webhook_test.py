"""
Remote Notify — WebSocket Edition
===================================
Real-time message pop-ups across devices using WebSockets.

Install deps:
  pip install websockets
"""

import asyncio
import threading
import socket
import tkinter as tk
from tkinter import ttk, scrolledtext

# ── Colours ────────────────────────────────────────────
BG      = "#1e1e2e"
SURFACE = "#313244"
ACCENT  = "#cba6f7"
FG      = "#cdd6f4"
GREEN   = "#a6e3a1"
YELLOW  = "#f9e2af"

# ── Globals ────────────────────────────────────────────
connected_clients = set()
_gui_log_cb = None
_ws_loop    = None   # the asyncio event loop running in the WS thread


def _log(msg: str):
    if _gui_log_cb:
        _gui_log_cb(msg)
    print(msg)


# ══════════════════════════════════════════════════════
#  POP-UP
# ══════════════════════════════════════════════════════

def show_popup(message: str):
    popup = tk.Tk()
    popup.title("📢 Remote Message")
    popup.geometry("440x220")
    popup.configure(bg=BG)
    popup.attributes("-topmost", True)
    popup.resizable(False, False)

    tk.Label(popup, text="📢  Incoming Message", font=("Helvetica", 13, "bold"),
             bg=BG, fg=ACCENT).pack(pady=(22, 6))
    tk.Label(popup, text=message, font=("Helvetica", 14),
             bg=BG, fg=FG, wraplength=400).pack(pady=6)
    tk.Button(popup, text="Dismiss", command=popup.destroy,
              bg=ACCENT, fg=BG, font=("Helvetica", 11, "bold"),
              relief="flat", padx=24, pady=6).pack(pady=16)
    popup.mainloop()


# ══════════════════════════════════════════════════════
#  WEBSOCKET SERVER
# ══════════════════════════════════════════════════════

async def _ws_handler(websocket):
    connected_clients.add(websocket)
    _log(f"[WS] ✅ Client connected: {websocket.remote_address}  ({len(connected_clients)} total)")
    try:
        async for msg in websocket:
            _log(f"[WS] 📨 Received: {msg}")
            # Broadcast to all OTHER clients
            for client in list(connected_clients - {websocket}):
                try:
                    await client.send(msg)
                except Exception:
                    pass
            # Show popup on this machine too
            threading.Thread(target=show_popup, args=(msg,), daemon=True).start()
    except Exception:
        pass
    finally:
        connected_clients.discard(websocket)
        _log(f"[WS] ❌ Client disconnected  ({len(connected_clients)} remaining)")


def start_ws_server(port: int):
    global _ws_loop
    import websockets

    def _run():
        global _ws_loop
        _ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_ws_loop)

        async def _main():
            async with websockets.serve(_ws_handler, "0.0.0.0", port):
                _log(f"[WS] 🚀 Server started on ws://0.0.0.0:{port}")
                await asyncio.Future()

        _ws_loop.run_until_complete(_main())

    threading.Thread(target=_run, daemon=True).start()


# ══════════════════════════════════════════════════════
#  WEBSOCKET SENDER
# ══════════════════════════════════════════════════════

def send_ws(target_ip: str, port: int, message: str):
    import websockets

    async def _send():
        uri = f"ws://{target_ip}:{port}"
        async with websockets.connect(uri) as ws:
            await ws.send(message)
            _log(f"[WS] ✅ Sent to {uri}: {message}")

    def _run():
        try:
            asyncio.run(_send())
        except Exception as e:
            _log(f"[WS] ❌ Send failed: {e}")

    threading.Thread(target=_run, daemon=True).start()


# ══════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ══════════════════════════════════════════════════════
#  GUI
# ══════════════════════════════════════════════════════

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Remote Notify — WebSocket")
        self.geometry("560x540")
        self.resizable(False, False)
        self.configure(bg=BG)

        global _gui_log_cb
        _gui_log_cb = self._append_log

        self._server_running = False
        self._build_header()
        self._build_server_card()
        self._build_send_card()
        self._build_test_card()
        self._build_log()

    # ── Header ──────────────────────────────────────────

    def _build_header(self):
        frm = tk.Frame(self, bg=BG)
        frm.pack(fill="x", padx=20, pady=(16, 4))
        tk.Label(frm, text="⚡  Remote Notify", font=("Helvetica", 18, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")
        tk.Label(frm, text=f"Your IP:  {get_local_ip()}",
                 font=("Helvetica", 10), bg=BG, fg=YELLOW).pack(side="right")

    # ── Shared widget helpers ────────────────────────────

    def _card(self, title: str):
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="x", padx=20, pady=6)
        tk.Label(outer, text=title, bg=BG, fg=ACCENT,
                 font=("Helvetica", 10, "bold")).pack(anchor="w", pady=(0, 4))
        inner = tk.Frame(outer, bg=SURFACE, padx=16, pady=12)
        inner.pack(fill="x")
        return inner

    def _row(self, card, label, default):
        frm = tk.Frame(card, bg=SURFACE)
        frm.pack(fill="x", pady=3)
        tk.Label(frm, text=label, width=12, anchor="w",
                 bg=SURFACE, fg=FG, font=("Helvetica", 10)).pack(side="left")
        e = tk.Entry(frm, bg=BG, fg=FG, insertbackground=FG,
                     font=("Helvetica", 11), relief="flat",
                     highlightthickness=1, highlightbackground=ACCENT)
        e.insert(0, default)
        e.pack(side="left", fill="x", expand=True, padx=(8, 0))
        return e

    def _btn(self, parent, text, cmd, color=ACCENT, full=False):
        b = tk.Button(parent, text=text, command=cmd,
                      bg=color, fg=BG, font=("Helvetica", 10, "bold"),
                      relief="flat", padx=14, pady=6, cursor="hand2")
        if full:
            b.pack(fill="x", pady=(10, 0))
        else:
            b.pack(side="left", padx=(8, 0))
        return b

    # ── Server card ──────────────────────────────────────

    def _build_server_card(self):
        card = self._card("🖥️  Server  —  run this on the receiving device")
        self.srv_port = self._row(card, "Port:", "6789")

        frm = tk.Frame(card, bg=SURFACE)
        frm.pack(fill="x", pady=(10, 0))
        self.srv_status = tk.Label(frm, text="● Stopped", bg=SURFACE,
                                   fg=YELLOW, font=("Helvetica", 10, "bold"))
        self.srv_status.pack(side="left")
        self._btn(frm, "▶  Start Server", self._start_server, color=GREEN)

    def _start_server(self):
        if self._server_running:
            _log("[WS] Server already running.")
            return
        port = int(self.srv_port.get() or 6789)
        start_ws_server(port)
        self._server_running = True
        self.srv_status.config(text="● Running", fg=GREEN)

    # ── Send card ────────────────────────────────────────

    def _build_send_card(self):
        card = self._card("📤  Send  —  push a message to another device")
        self.send_ip   = self._row(card, "Target IP:", "192.168.1.x")
        self.send_port = self._row(card, "Port:",      "6789")
        self.send_msg  = self._row(card, "Message:",   "THE COUNCIL")
        self._btn(card, "📤  Send Message", self._do_send, full=True)

    def _do_send(self):
        ip   = self.send_ip.get().strip()
        port = int(self.send_port.get() or 6789)
        msg  = self.send_msg.get().strip() or "THE COUNCIL"
        send_ws(ip, port, msg)

    # ── Test card ────────────────────────────────────────

    def _build_test_card(self):
        card = self._card("🧪  Test  —  preview the pop-up locally")
        self.test_msg = self._row(card, "Message:", "THE COUNCIL")
        self._btn(card, "🧪  Show Popup", self._do_test, color=YELLOW, full=True)

    def _do_test(self):
        msg = self.test_msg.get().strip() or "THE COUNCIL"
        threading.Thread(target=show_popup, args=(msg,), daemon=True).start()

    # ── Log ──────────────────────────────────────────────

    def _build_log(self):
        frm = tk.Frame(self, bg=BG)
        frm.pack(fill="both", expand=True, padx=20, pady=(6, 16))

        hdr = tk.Frame(frm, bg=BG)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Activity Log", bg=BG, fg=ACCENT,
                 font=("Helvetica", 10, "bold")).pack(side="left")
        tk.Button(hdr, text="Clear", command=self._clear_log,
                  bg=SURFACE, fg=FG, font=("Helvetica", 9),
                  relief="flat", padx=10, pady=2).pack(side="right")

        self.log = scrolledtext.ScrolledText(
            frm, height=8, bg=SURFACE, fg=FG, font=("Courier", 9),
            relief="flat", state="disabled",
            highlightthickness=1, highlightbackground=ACCENT)
        self.log.pack(fill="both", expand=True, pady=(4, 0))

    def _append_log(self, msg: str):
        def _do():
            self.log.configure(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.after(0, _do)

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")


# ══════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    App().mainloop()