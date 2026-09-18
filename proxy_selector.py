from __future__ import annotations

import argparse
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

from src.utils import CONFIG_DIR, HELSINKI_TZ, PROJECT_ROOT

HAPP_EXE_DEFAULT = r"C:\Tools\happ-cli\happ-windows-amd64\happ-windows-amd64\happ.exe"
SOCKS_PORT_DEFAULT = 11808
HTTP_PORT_DEFAULT = 11809
STATE_PATH_DEFAULT = CONFIG_DIR / "happ_proxy_state.json"
LOG_PATH_DEFAULT = PROJECT_ROOT / "logs" / "happ_proxy.log"
HEALTH_URL_DEFAULT = "https://api.ipify.org"
TELEGRAM_WEB_URL_DEFAULT = "https://t.me/"
DEFAULT_COUNTRY_ALIASES = ("нидерланды", "netherlands")
PROTOCOL_PRIORITY = ("vless", "vmess", "trojan", "shadowsocks")

LIST_ROW_RE = re.compile(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S.*?)\s*$")
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

EXIT_OK = 0
EXIT_ENV_ERROR = 3
EXIT_ALREADY_RUNNING = 4
EXIT_NO_SERVER = 5
EXIT_STALE_PID = 6


class ProxySelectorError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServerInfo:
    server_id: str
    protocol: str
    address: str
    tag: str
    country: str


def parse_list_output(text: str) -> list[ServerInfo]:
    servers: list[ServerInfo] = []
    for line in strip_ansi(text).splitlines():
        match = LIST_ROW_RE.match(line)
        if not match:
            continue
        server_id, protocol, address, tag = match.groups()
        country = tag.rsplit(" - ", 1)[-1].strip() if " - " in tag else ""
        servers.append(
            ServerInfo(
                server_id=server_id,
                protocol=protocol.lower(),
                address=address.strip(),
                tag=tag.strip(),
                country=country,
            )
        )
    return servers


def select_servers(
    servers: list[ServerInfo],
    country_aliases: tuple[str, ...] = DEFAULT_COUNTRY_ALIASES,
) -> list[ServerInfo]:
    aliases = tuple(alias.lower() for alias in country_aliases if alias.strip())
    candidates = [
        (index, server)
        for index, server in enumerate(servers)
        if not aliases or any(alias in server.tag.lower() for alias in aliases)
    ]
    candidates.sort(
        key=lambda item: (
            PROTOCOL_PRIORITY.index(item[1].protocol)
            if item[1].protocol in PROTOCOL_PRIORITY
            else len(PROTOCOL_PRIORITY),
            item[0],
        )
    )
    return [server for _, server in candidates]


def socks_endpoint(host: str, port: int) -> str:
    return f"socks5h://{host}:{port}"


def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_port(host: str, port: int, timeout: float, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_port_open(host, port):
            return True
        time.sleep(interval)
    return is_port_open(host, port)


def wait_for_port_closed(host: str, port: int, timeout: float, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_port_open(host, port):
            return True
        time.sleep(interval)
    return not is_port_open(host, port)


def run_happ_list(exe: str, timeout: float = 60.0) -> str:
    completed = subprocess.run([exe, "list"], capture_output=True, check=False, timeout=timeout)
    stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise ProxySelectorError(
            f"happ.exe list failed with code {completed.returncode}: {stderr.strip()}"
        )
    combined = "\n".join(part for part in (stdout, stderr) if part)
    if not combined.strip():
        raise ProxySelectorError("happ.exe list produced no output on stdout or stderr")
    return combined


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def build_connect_argv(exe: str, server_id: str, socks_port: int, http_port: int) -> list[str]:
    return [
        str(exe),
        "connect",
        str(server_id),
        "--mode",
        "proxy",
        "--socks",
        str(socks_port),
        "--http",
        str(http_port),
    ]


def start_happ(exe: str, server_id: str, socks_port: int, http_port: int, log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "ab")
    return subprocess.Popen(
        build_connect_argv(exe, server_id, socks_port, http_port),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )


def check_exit_ip(endpoint: str, timeout: float = 10.0, url: str = HEALTH_URL_DEFAULT) -> str:
    response = requests.get(url, proxies={"http": endpoint, "https": endpoint}, timeout=timeout)
    response.raise_for_status()
    return response.text.strip()


def check_telegram_web(endpoint: str, timeout: float = 15.0, url: str = TELEGRAM_WEB_URL_DEFAULT) -> int:
    response = requests.get(url, proxies={"http": endpoint, "https": endpoint}, timeout=timeout)
    response.raise_for_status()
    return response.status_code


def get_process_info(pid: int) -> dict[str, str] | None:
    """Return identifying info for a live PID, or None if the process is gone."""
    if pid <= 0:
        return None
    command = (
        f'Get-CimInstance Win32_Process -Filter "ProcessId={pid}" '
        "| Select-Object ProcessId,Name,ExecutablePath,CommandLine,CreationDate "
        "| ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (completed.stdout or "").strip()
    if not output or output.lower() == "null":
        return None
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        return None
    return {str(key): "" if value is None else str(value) for key, value in data.items()}


def _norm_path(value: object) -> str:
    if not value:
        return ""
    return os.path.normcase(os.path.abspath(str(value)))


def process_matches_state(info: dict[str, str] | None, state: dict[str, object]) -> bool:
    """True only when the live process is the happ.exe we started (guards PID reuse)."""
    if not info:
        return False
    if "happ" not in str(info.get("Name", "")).lower():
        return False

    expected_exe = _norm_path(state.get("exe_path") or state.get("happ_exe"))
    actual_exe = _norm_path(info.get("ExecutablePath"))
    if expected_exe and actual_exe and expected_exe != actual_exe:
        return False

    expected_created = str(state.get("process_created_at") or "")
    actual_created = str(info.get("CreationDate") or "")
    if expected_created and actual_created and expected_created != actual_created:
        return False

    tokens = str(info.get("CommandLine") or "").lower().split()
    if "connect" not in tokens:
        return False
    server_id = str(state.get("server_id") or "")
    if server_id and server_id not in tokens:
        return False
    return True


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    output = (completed.stdout or "").strip()
    if not output or "INFO:" in output or "No tasks" in output:
        return False
    return str(pid) in output


def terminate_pid(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        check=False,
    )


def stop_process(proc) -> None:
    try:
        terminate_pid(proc.pid)
    finally:
        try:
            proc.wait(timeout=5)
        except Exception:
            pass


def load_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def remove_state(path: Path) -> None:
    path.unlink(missing_ok=True)


def _parse_country_aliases(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _add_global_options(parser: argparse.ArgumentParser, suppress_defaults: bool = False) -> None:
    def _default(value):
        return argparse.SUPPRESS if suppress_defaults else value

    parser.add_argument(
        "--happ-exe",
        default=_default(HAPP_EXE_DEFAULT),
        help=f"Path to happ.exe (default: {HAPP_EXE_DEFAULT})",
    )
    parser.add_argument(
        "--socks-port",
        type=int,
        default=_default(SOCKS_PORT_DEFAULT),
        help="SOCKS5 port (default: 11808)",
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=_default(HTTP_PORT_DEFAULT),
        help="HTTP proxy port (default: 11809)",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=_default(STATE_PATH_DEFAULT),
        help="Where to store the started proxy state",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=_default(LOG_PATH_DEFAULT),
        help="Where to write happ.exe output",
    )
    parser.add_argument(
        "--country",
        default=_default(",".join(DEFAULT_COUNTRY_ALIASES)),
        help="Comma-separated country aliases to prefer",
    )
    parser.add_argument(
        "--telegram-timeout",
        type=float,
        default=_default(15.0),
        help="Seconds for the https://t.me/ reachability check",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proxy_selector.py",
        description="Select and manage a happ-cli SOCKS5 proxy for headless exports.",
    )
    _add_global_options(parser)

    common = argparse.ArgumentParser(add_help=False)
    _add_global_options(common, suppress_defaults=True)

    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("up", parents=[common], help="Find and start a working proxy")
    up.add_argument("--wait-timeout", type=float, default=20.0, help="Seconds to wait for the SOCKS port")
    up.add_argument("--health-timeout", type=float, default=15.0, help="Seconds for the health-check request")

    sub.add_parser("down", parents=[common], help="Stop the proxy started by proxy_selector.py")
    sub.add_parser("status", parents=[common], help="Show the recorded proxy state")
    sub.add_parser("check", parents=[common], help="Run the health-check against the current SOCKS endpoint")

    list_cmd = sub.add_parser("list", parents=[common], help="Show available happ servers")
    list_cmd.add_argument("--json", action="store_true", help="Print servers as JSON")

    return parser


def _configure_logging() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def cmd_list(args) -> int:
    try:
        raw = run_happ_list(args.happ_exe)
    except Exception as exc:
        logging.error("failed to run happ.exe list: %s", exc)
        return EXIT_ENV_ERROR
    servers = parse_list_output(raw)
    if args.json:
        _emit({"servers": [server.__dict__ for server in servers]})
    else:
        for server in servers:
            print(f"{server.server_id}\t{server.protocol}\t{server.address}\t{server.tag}")
    return EXIT_OK


def cmd_up(args) -> int:
    exe = Path(args.happ_exe)
    if not exe.exists():
        logging.error("happ.exe not found at %s", exe)
        return EXIT_ENV_ERROR

    state = load_state(args.state_file)
    if is_port_open("127.0.0.1", args.socks_port):
        if state and is_pid_alive(int(state.get("pid", 0))):
            logging.error(
                "SOCKS port %s is already used by proxy_selector.py (pid %s); run 'down' first",
                args.socks_port,
                state.get("pid"),
            )
            return EXIT_ALREADY_RUNNING
        logging.error(
            "SOCKS port %s is already in use by an unknown process; refusing to kill anything",
            args.socks_port,
        )
        return EXIT_ENV_ERROR

    try:
        raw = run_happ_list(args.happ_exe)
    except Exception as exc:
        logging.error("failed to run happ.exe list: %s", exc)
        return EXIT_ENV_ERROR

    servers = select_servers(parse_list_output(raw), _parse_country_aliases(args.country))
    if not servers:
        logging.error("no servers matched country %s", args.country)
        return EXIT_NO_SERVER

    endpoint = socks_endpoint("127.0.0.1", args.socks_port)
    last_error = ""
    for server in servers:
        logging.info("trying server %s (%s, %s)", server.server_id, server.protocol, server.country)
        proc = start_happ(args.happ_exe, server.server_id, args.socks_port, args.http_port, args.log_file)
        keep = False
        try:
            if not wait_for_port("127.0.0.1", args.socks_port, args.wait_timeout):
                last_error = f"server {server.server_id}: SOCKS port did not open"
                logging.warning("%s", last_error)
                continue
            try:
                exit_ip = check_exit_ip(endpoint, timeout=args.health_timeout)
            except Exception as exc:
                last_error = f"server {server.server_id}: exit_ip check failed: {exc}"
                logging.warning("%s", last_error)
                continue
            try:
                telegram_status = check_telegram_web(endpoint, timeout=args.telegram_timeout)
            except Exception as exc:
                last_error = f"server {server.server_id}: telegram web check failed: {exc}"
                logging.warning("%s", last_error)
                continue

            info = get_process_info(proc.pid) or {}
            save_state(
                args.state_file,
                {
                    "server_id": server.server_id,
                    "country": server.country,
                    "protocol": server.protocol,
                    "pid": proc.pid,
                    "socks_endpoint": endpoint,
                    "http_endpoint": f"http://127.0.0.1:{args.http_port}",
                    "address": server.address,
                    "happ_exe": args.happ_exe,
                    "exe_path": str(info.get("ExecutablePath") or args.happ_exe),
                    "command_line": str(
                        info.get("CommandLine")
                        or " ".join(
                            build_connect_argv(args.happ_exe, server.server_id, args.socks_port, args.http_port)
                        )
                    ),
                    "process_created_at": str(info.get("CreationDate") or ""),
                    "started_at": datetime.now(HELSINKI_TZ).isoformat(),
                },
            )
            keep = True
            _emit(
                {
                    "server_id": server.server_id,
                    "country": server.country,
                    "protocol": server.protocol,
                    "pid": proc.pid,
                    "socks_endpoint": endpoint,
                    "exit_ip": exit_ip,
                    "telegram_web": telegram_status,
                }
            )
            return EXIT_OK
        finally:
            if not keep:
                stop_process(proc)
                wait_for_port_closed("127.0.0.1", args.socks_port, timeout=10.0)

    logging.error("no working server found; last error: %s", last_error or "unknown")
    return EXIT_NO_SERVER


def cmd_down(args) -> int:
    state = load_state(args.state_file)
    if not state:
        logging.info("no proxy_selector state file at %s; nothing to stop", args.state_file)
        return EXIT_OK

    pid = int(state.get("pid", 0))
    info = get_process_info(pid) if pid else None

    if info is None:
        logging.info("recorded happ pid %s is not running; clearing state", pid)
        remove_state(args.state_file)
        return EXIT_OK

    if not process_matches_state(info, state):
        stale = dict(state)
        stale["stale"] = True
        stale["stale_reason"] = "pid no longer belongs to the happ.exe started by proxy_selector.py"
        save_state(args.state_file, stale)
        logging.error(
            "PID %s is alive but is not our happ.exe (possible PID reuse); refusing to kill it",
            pid,
        )
        return EXIT_STALE_PID

    terminate_pid(pid)
    socks_port = int(state.get("socks_port", 0)) or args.socks_port
    wait_for_port_closed("127.0.0.1", socks_port, timeout=10.0)
    logging.info("stopped happ process pid %s", pid)
    remove_state(args.state_file)
    return EXIT_OK


def cmd_status(args) -> int:
    state = load_state(args.state_file)
    if not state:
        _emit({"running": False, "state_file": str(args.state_file)})
        return EXIT_OK
    pid = int(state.get("pid", 0))
    _emit(
        {
            "running": bool(pid and is_pid_alive(pid)),
            "pid": pid,
            "server_id": state.get("server_id"),
            "country": state.get("country"),
            "protocol": state.get("protocol"),
            "socks_endpoint": state.get("socks_endpoint"),
            "port_open": is_port_open("127.0.0.1", args.socks_port),
            "started_at": state.get("started_at"),
        }
    )
    return EXIT_OK


def cmd_check(args) -> int:
    endpoint = socks_endpoint("127.0.0.1", args.socks_port)
    try:
        exit_ip = check_exit_ip(endpoint)
        telegram_status = check_telegram_web(endpoint, timeout=args.telegram_timeout)
    except Exception as exc:
        _emit({"socks_endpoint": endpoint, "exit_ip": None, "telegram_web": None, "error": str(exc)})
        return EXIT_ENV_ERROR
    _emit({"socks_endpoint": endpoint, "exit_ip": exit_ip, "telegram_web": telegram_status})
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging()

    handlers = {
        "up": cmd_up,
        "down": cmd_down,
        "status": cmd_status,
        "check": cmd_check,
        "list": cmd_list,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())