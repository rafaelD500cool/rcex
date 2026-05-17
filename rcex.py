"""
Browser Launcher Service -- PoC
================================
Runs in the background. On startup, reports all its network interfaces
to a webhook URL you control so you always know where to reach it.

Install deps:
  pip install flask requests pyngrok

Usage:
  python browser_service.py --report-to https://your-webhook.site/xyz
  python browser_service.py --report-to https://your-webhook.site/xyz --no-tunnel
"""

import threading
import webbrowser
import socket
import sys
import argparse
import logging
import requests
from datetime import datetime

try:
    from flask import Flask, jsonify, request as flask_request
except ImportError:
    print("Missing dep -- run:  pip install flask requests")
    sys.exit(1)

try:
    from pyngrok import ngrok
    NGROK_AVAILABLE = True
except ImportError:
    NGROK_AVAILABLE = False


# ==============================================================================
#  CONFIG
# ==============================================================================

DEFAULT_PORT = 8000
DEFAULT_URL  = "https://google.com"
LOG_FILE     = "browser_service.log"


# ==============================================================================
#  LOGGING
#  Force UTF-8 on both handlers so Windows cp1252 terminals never choke.
#  We build the handlers manually instead of using basicConfig so we can
#  set the encoding explicitly on the stream handler.
# ==============================================================================

# File handler -- UTF-8 so the log file always stores correctly
_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")

# Stream handler -- reopen stdout in UTF-8 mode so cp1252 terminals don't error
# sys.stdout.fileno() gives us the underlying OS file descriptor,
# then we wrap it in a new TextIOWrapper with utf-8 encoding.
_utf8_stdout   = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1, closefd=False)
_stream_handler = logging.StreamHandler(_utf8_stdout)

_formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
_file_handler.setFormatter(_formatter)
_stream_handler.setFormatter(_formatter)

logging.root.setLevel(logging.INFO)
logging.root.addHandler(_file_handler)
logging.root.addHandler(_stream_handler)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

log = logging.getLogger(__name__)


# ==============================================================================
#  NETWORK INTERFACE DISCOVERY
#  Two methods combined to catch every IP on the machine:
#
#  Method 1 -- socket.getaddrinfo(hostname, None)
#    Asks the OS "what IPs does this hostname resolve to locally?"
#    Catches every NIC, VPN adapter, virtual interface, etc.
#
#  Method 2 -- UDP socket trick
#    Open a UDP socket aimed at 8.8.8.8 (no data sent).
#    The OS picks the right outbound interface and we read which
#    local IP it chose. Reliable for the "primary" IP.
#
#  Both sets are merged and deduplicated via a set().
# ==============================================================================

def get_all_interfaces():
    ips = set()

    # Method 1
    try:
        hostname = socket.gethostname()
        results  = socket.getaddrinfo(hostname, None)
        for result in results:
            ip = result[4][0]
            if ":" not in ip and ip != "127.0.0.1":
                ips.add(ip)
    except Exception:
        pass

    # Method 2
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass

    ips.add("127.0.0.1")
    return sorted(ips)


def build_host_report(port: int, ngrok_url: str = None) -> dict:
    """Assemble the full report dict sent to the webhook and logged locally."""
    all_ips = get_all_interfaces()
    try:
        primary_ip = [ip for ip in all_ips if ip != "127.0.0.1"][0]
    except IndexError:
        primary_ip = "127.0.0.1"

    report = {
        "hostname":      socket.gethostname(),
        "primary_ip":    primary_ip,
        "all_ips":       all_ips,
        "port":          port,
        "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "curl_commands": [f"curl http://{ip}:{port}/open" for ip in all_ips],
    }

    if ngrok_url:
        report["ngrok_url"]  = ngrok_url
        report["ngrok_curl"] = f"curl {ngrok_url}/open"
        report["ngrok_irm"]  = f"irm  {ngrok_url}/open"

    return report


# ==============================================================================
#  PHONE HOME
#  POSTs the host report as JSON to whatever URL you pass via --report-to.
#  Runs in a daemon thread so it never delays Flask starting.
#
#  Works with any webhook receiver:
#    - https://webhook.site   (free, shows payloads in browser -- great for testing)
#    - https://requestbin.com (free)
#    - Your own Flask /register endpoint on a controller machine
# ==============================================================================

def phone_home(report_url: str, report: dict):
    try:
        log.info(f"[Report] Sending host info to {report_url} ...")
        resp = requests.post(report_url, json=report, timeout=10)
        log.info(f"[Report] Delivered -- HTTP {resp.status_code}")
    except requests.exceptions.ConnectionError:
        log.warning(f"[Report] Could not reach {report_url} -- check the URL")
    except requests.exceptions.Timeout:
        log.warning(f"[Report] Timed out sending to {report_url}")
    except Exception as e:
        log.error(f"[Report] Failed: {e}")


# ==============================================================================
#  FLASK ROUTES
#  Three endpoints -- all plain HTTP GET so curl/irm work with no flags.
#
#  GET /open           -- open DEFAULT_URL in browser
#  GET /open?url=...   -- open a specific URL
#  GET /status         -- return full host report as JSON
#  GET /shutdown       -- stop the service (responds first, then exits)
# ==============================================================================

app = Flask(__name__)

@app.route("/open")
def route_open():
    url = flask_request.args.get("url", DEFAULT_URL).strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    log.info(f"[/open] Opening browser -> {url}")
    threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    return jsonify({"status": "ok", "action": "open", "url": url})

@app.route("/status")
def route_status():
    log.info("[/status] Status requested")
    return jsonify(build_host_report(DEFAULT_PORT))

@app.route("/shutdown")
def route_shutdown():
    log.info("[/shutdown] Shutting down...")
    def _stop():
        import time, os
        time.sleep(0.5)   # let Flask finish sending the response first
        os._exit(0)
    threading.Thread(target=_stop, daemon=True).start()
    return jsonify({"status": "ok", "action": "shutdown"})


# ==============================================================================
#  NGROK TUNNEL
#  Opens an HTTP tunnel so the service is reachable from any network.
#  Free tier works fine; tunnels last ~2h without an auth token.
#  Set a token with:  ngrok config add-authtoken <token>  (free at ngrok.com)
# ==============================================================================

def start_ngrok_tunnel(port: int):
    if not NGROK_AVAILABLE:
        log.warning("[ngrok] pyngrok not installed -- LAN only. Run: pip install pyngrok")
        return None
    try:
        tunnel     = ngrok.connect(port, "http")
        public_url = tunnel.public_url.rstrip("/")
        log.info(f"[ngrok] OK - Tunnel active: {public_url}")
        return public_url
    except Exception as e:
        log.error(f"[ngrok] Failed: {e}")
        return None


# ==============================================================================
#  ENTRY POINT
# ==============================================================================

def main():
    global DEFAULT_PORT  # must be first line -- before any use of DEFAULT_PORT

    parser = argparse.ArgumentParser(description="Browser Launcher Service")
    parser.add_argument("--port",      type=int, default=DEFAULT_PORT,
                        help=f"Port to listen on (default: {DEFAULT_PORT})")
    parser.add_argument("--no-tunnel", action="store_true",
                        help="Skip ngrok -- LAN only")
    parser.add_argument("--report-to", type=str, default=None,
                        help="Webhook URL to POST host info to on startup")
    args = parser.parse_args()

    DEFAULT_PORT = args.port

    log.info("=" * 52)
    log.info("  Browser Launcher Service starting")
    log.info("=" * 52)

    # 1. Start ngrok first so the public URL is included in the report
    ngrok_url = None
    if not args.no_tunnel:
        ngrok_url = start_ngrok_tunnel(args.port)

    # 2. Build the host report
    report = build_host_report(args.port, ngrok_url)

    # 3. Print report to terminal
    log.info("[Report] --- Host info -----------------------------------")
    log.info(f"[Report] Hostname   : {report['hostname']}")
    log.info(f"[Report] Primary IP : {report['primary_ip']}")
    log.info(f"[Report] All IPs    : {', '.join(report['all_ips'])}")
    if ngrok_url:
        log.info(f"[Report] ngrok URL  : {ngrok_url}")
    log.info("[Report] --- curl commands ------------------------------")
    for cmd in report["curl_commands"]:
        log.info(f"[Report]   {cmd}")
    if ngrok_url:
        log.info(f"[Report]   {report['ngrok_curl']}")
        log.info(f"[Report]   {report['ngrok_irm']}  (PowerShell)")
    log.info("[Report] ------------------------------------------------")

    # 4. Phone home if --report-to was given
    if args.report_to:
        threading.Thread(
            target=phone_home,
            args=(args.report_to, report),
            daemon=True
        ).start()
    else:
        log.info("[Report] No --report-to set -- pass --report-to <url> to enable.")

    # 5. Start Flask
    try:
        app.run(host="0.0.0.0", port=args.port, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        log.info("Interrupted.")
    finally:
        if ngrok_url:
            ngrok.disconnect(ngrok_url)
            log.info("[ngrok] Tunnel closed.")
        log.info("Service stopped.")


if __name__ == "__main__":
    main()