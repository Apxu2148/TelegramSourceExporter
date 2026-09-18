import json
from pathlib import Path

import pytest

import proxy_selector
from proxy_selector import ServerInfo, parse_list_output, select_servers

SAMPLE_LIST = """
#   PROTOCOL     ADDRESS               TAG
1   vless        84.32.61.112:8444     🇺🇸 VLESS³ - США
6   vless        84.32.187.124:8444    🇳 VLESS³ - Нидерланды
7   vless        84.32.187.124:2053    🇳 VLESS² - Нидерланды
8   vmess        84.32.187.124:8081    🇳🇱 VMess² - Нидерланды
9   trojan       84.32.187.124:2058     TROJAN - Нидерланды
10  shadowsocks  84.32.187.124:2060    🇱 SHADOWSOCKS - Нидерланды
11  vless        88.216.130.86:8444    🇸🇪 VLESS³ - Швеция
16  vless        84.32.100.250:8444    🇩🇪 VLESS³ - Германия
21  vless        188.214.135.206:8444  🇱🇹 VLESS³ - Литва
"""

HAPP_EXE = "C:\\Tools\\happ.exe"

REAL_LIST_FRAGMENT = """#   PROTOCOL     ADDRESS               TAG
1   vless        84.32.61.112:8444     🇺🇸 VLESS³ - США
2   vless        84.32.61.112:2053     🇺🇸 VLESS² - США
3   vmess        84.32.61.112:8081     🇺🇸 VMess² - США
4   trojan       84.32.61.112:2058     🇺🇸 TROJAN - США
5   shadowsocks  84.32.61.112:2060     🇺🇸 SHADOWSOCKS - США
6   vless        84.32.187.124:8444    🇳🇱 VLESS³ - Нидерланды
7   vless        84.32.187.124:2053    🇳🇱 VLESS² - Нидерланды
8   vmess        84.32.187.124:8081    🇳🇱 VMess² - Нидерланды
9   trojan       84.32.187.124:2058    🇱 TROJAN - Нидерланды
10  shadowsocks  84.32.187.124:2060    🇳🇱 SHADOWSOCKS - Нидерланды
...
"""


class _Completed:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeProc:
    def __init__(self, pid):
        self.pid = pid

    def wait(self, timeout=None):
        return 0


def _proc_info(exe=HAPP_EXE, server_id="6", created="/Date(100)/", name="happ.exe", command_line=None):
    return {
        "ProcessId": "1",
        "Name": name,
        "ExecutablePath": exe,
        "CommandLine": command_line or f"{exe} connect {server_id} --mode proxy --socks 11808 --http 11809",
        "CreationDate": created,
    }


def _write_state(path: Path, pid: int = 111, **overrides) -> None:
    data = {
        "server_id": "6",
        "country": "Нидерланды",
        "protocol": "vless",
        "pid": pid,
        "socks_port": 11808,
        "socks_endpoint": "socks5h://127.0.0.1:11808",
        "happ_exe": HAPP_EXE,
        "exe_path": HAPP_EXE,
        "command_line": f"{HAPP_EXE} connect 6 --mode proxy --socks 11808 --http 11809",
        "process_created_at": "/Date(100)/",
        "started_at": "2026-09-19T01:00:00+03:00",
    }
    data.update(overrides)
    proxy_selector.save_state(path, data)


def _prepare(
    tmp_path,
    monkeypatch,
    *,
    port_open=False,
    exit_ip=None,
    telegram=None,
    proc_info=None,
    list_text=SAMPLE_LIST,
):
    happ = tmp_path / "happ.exe"
    happ.write_bytes(b"stub")
    state = tmp_path / "state.json"

    monkeypatch.setattr(proxy_selector, "run_happ_list", lambda exe, timeout=60.0: list_text)
    monkeypatch.setattr(proxy_selector, "is_port_open", lambda host, port, timeout=0.5: port_open)
    monkeypatch.setattr(proxy_selector, "wait_for_port", lambda host, port, timeout, interval=0.25: True)
    monkeypatch.setattr(proxy_selector, "wait_for_port_closed", lambda host, port, timeout, interval=0.25: True)
    monkeypatch.setattr(
        proxy_selector,
        "get_process_info",
        lambda pid: _proc_info() if proc_info is None else proc_info,
    )
    monkeypatch.setattr(
        proxy_selector,
        "check_exit_ip",
        exit_ip or (lambda endpoint, timeout=10.0, url="https://api.ipify.org": "203.0.113.7"),
    )
    monkeypatch.setattr(
        proxy_selector,
        "check_telegram_web",
        telegram or (lambda endpoint, timeout=15.0, url="https://t.me/": 200),
    )
    return happ, state


def test_parse_list_output_extracts_rows():
    servers = parse_list_output(SAMPLE_LIST)

    assert len(servers) == 9
    first = servers[0]
    assert first.server_id == "1"
    assert first.protocol == "vless"
    assert first.address == "84.32.61.112:8444"
    assert first.country == "США"
    assert servers[1].country == "Нидерланды"
    assert servers[1].server_id == "6"


def test_select_servers_prefers_country_then_protocol_priority():
    selected = select_servers(parse_list_output(SAMPLE_LIST))

    assert [server.server_id for server in selected] == ["6", "7", "8", "9", "10"]
    assert [server.protocol for server in selected] == ["vless", "vless", "vmess", "trojan", "shadowsocks"]


def test_socks_endpoint_uses_socks5h():
    assert proxy_selector.socks_endpoint("127.0.0.1", 11808) == "socks5h://127.0.0.1:11808"


def test_build_connect_argv_shape():
    assert proxy_selector.build_connect_argv(HAPP_EXE, "6", 11808, 11809) == [
        HAPP_EXE,
        "connect",
        "6",
        "--mode",
        "proxy",
        "--socks",
        "11808",
        "--http",
        "11809",
    ]


def test_process_matches_state_accepts_our_process():
    state = {
        "server_id": "6",
        "exe_path": HAPP_EXE,
        "process_created_at": "/Date(100)/",
    }

    assert proxy_selector.process_matches_state(_proc_info(), state) is True


def test_process_matches_state_rejects_pid_reuse():
    state = {
        "server_id": "6",
        "exe_path": HAPP_EXE,
        "process_created_at": "/Date(100)/",
    }

    assert proxy_selector.process_matches_state(_proc_info(exe="C:\\Other\\happ.exe"), state) is False
    assert proxy_selector.process_matches_state(_proc_info(created="/Date(999)/"), state) is False
    assert proxy_selector.process_matches_state(_proc_info(name="chrome.exe"), state) is False
    assert proxy_selector.process_matches_state(None, state) is False


def test_up_starts_first_working_server_and_writes_state(tmp_path, monkeypatch, capsys):
    happ, state = _prepare(tmp_path, monkeypatch)
    started = []

    def fake_start(exe, server_id, socks_port, http_port, log_path):
        started.append((str(exe), server_id, socks_port, http_port))
        return FakeProc(4242)

    monkeypatch.setattr(proxy_selector, "start_happ", fake_start)
    killed = []
    monkeypatch.setattr(proxy_selector, "stop_process", lambda proc: killed.append(proc.pid))

    code = proxy_selector.main(["up", "--happ-exe", str(happ), "--state-file", str(state)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload == {
        "server_id": "6",
        "country": "Нидерланды",
        "protocol": "vless",
        "pid": 4242,
        "socks_endpoint": "socks5h://127.0.0.1:11808",
        "exit_ip": "203.0.113.7",
        "telegram_web": 200,
    }
    assert started[0][1] == "6"
    assert killed == []
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["pid"] == 4242
    assert saved["exe_path"] == HAPP_EXE
    assert saved["process_created_at"] == "/Date(100)/"
    assert "connect 6" in saved["command_line"]


def test_up_fails_over_when_exit_ip_check_fails(tmp_path, monkeypatch, capsys):
    calls = {"n": 0}

    def exit_ip(endpoint, timeout=10.0, url=""):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("socks handshake failed")
        return "198.51.100.9"

    happ, state = _prepare(tmp_path, monkeypatch, exit_ip=exit_ip)
    pids = iter([1001, 1002])

    monkeypatch.setattr(
        proxy_selector,
        "start_happ",
        lambda exe, server_id, socks_port, http_port, log_path: FakeProc(next(pids)),
    )
    killed = []
    monkeypatch.setattr(proxy_selector, "stop_process", lambda proc: killed.append(proc.pid))

    code = proxy_selector.main(["up", "--happ-exe", str(happ), "--state-file", str(state)])

    assert code == 0
    assert killed == [1001]
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["server_id"] == "7"
    assert payload["exit_ip"] == "198.51.100.9"


def test_up_fails_over_when_telegram_web_check_fails(tmp_path, monkeypatch, capsys):
    calls = {"n": 0}

    def telegram(endpoint, timeout=15.0, url=""):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("t.me not reachable via proxy")
        return 200

    happ, state = _prepare(tmp_path, monkeypatch, telegram=telegram)
    pids = iter([2001, 2002])
    monkeypatch.setattr(
        proxy_selector,
        "start_happ",
        lambda exe, server_id, socks_port, http_port, log_path: FakeProc(next(pids)),
    )
    killed = []
    monkeypatch.setattr(proxy_selector, "stop_process", lambda proc: killed.append(proc.pid))

    code = proxy_selector.main(["up", "--happ-exe", str(happ), "--state-file", str(state)])

    assert code == 0
    assert killed == [2001]
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["server_id"] == "7"
    assert payload["telegram_web"] == 200


def test_up_refuses_when_port_used_by_unknown_process(tmp_path, monkeypatch):
    happ, state = _prepare(tmp_path, monkeypatch, port_open=True)
    monkeypatch.setattr(proxy_selector, "start_happ", lambda *a, **k: FakeProc(1))
    killed = []
    monkeypatch.setattr(proxy_selector, "stop_process", lambda proc: killed.append(proc.pid))
    monkeypatch.setattr(proxy_selector, "terminate_pid", lambda pid: killed.append(pid))

    code = proxy_selector.main(["up", "--happ-exe", str(happ), "--state-file", str(state)])

    assert code == proxy_selector.EXIT_ENV_ERROR
    assert killed == []
    assert not state.exists()


def test_up_reports_already_running_own_proxy(tmp_path, monkeypatch):
    happ, state = _prepare(tmp_path, monkeypatch, port_open=True)
    _write_state(state, pid=555)
    monkeypatch.setattr(proxy_selector, "is_pid_alive", lambda pid: True)

    code = proxy_selector.main(["up", "--happ-exe", str(happ), "--state-file", str(state)])

    assert code == proxy_selector.EXIT_ALREADY_RUNNING


def test_up_returns_no_server_when_all_candidates_fail(tmp_path, monkeypatch):
    def exit_ip(endpoint, timeout=10.0, url=""):
        raise RuntimeError("blocked")

    happ, state = _prepare(tmp_path, monkeypatch, exit_ip=exit_ip)
    monkeypatch.setattr(proxy_selector, "start_happ", lambda *a, **k: FakeProc(1))
    monkeypatch.setattr(proxy_selector, "stop_process", lambda proc: None)

    code = proxy_selector.main(["up", "--happ-exe", str(happ), "--state-file", str(state)])

    assert code == proxy_selector.EXIT_NO_SERVER


def test_up_errors_when_happ_exe_missing(tmp_path, monkeypatch):
    state = tmp_path / "state.json"

    code = proxy_selector.main(["up", "--happ-exe", str(tmp_path / "missing.exe"), "--state-file", str(state)])

    assert code == proxy_selector.EXIT_ENV_ERROR


def test_down_stops_our_process_and_removes_state(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    _write_state(state, pid=777)
    monkeypatch.setattr(proxy_selector, "get_process_info", lambda pid: _proc_info())
    killed = []
    monkeypatch.setattr(proxy_selector, "terminate_pid", lambda pid: killed.append(pid))

    code = proxy_selector.main(["down", "--state-file", str(state)])

    assert code == 0
    assert killed == [777]
    assert not state.exists()


def test_down_refuses_on_pid_reuse_and_marks_stale(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    _write_state(state, pid=777)
    monkeypatch.setattr(
        proxy_selector,
        "get_process_info",
        lambda pid: _proc_info(exe="C:\\Other\\happ.exe", created="/Date(999)/"),
    )
    killed = []
    monkeypatch.setattr(proxy_selector, "terminate_pid", lambda pid: killed.append(pid))

    code = proxy_selector.main(["down", "--state-file", str(state)])

    assert code == proxy_selector.EXIT_STALE_PID
    assert killed == []
    assert state.exists()
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["stale"] is True
    assert "stale_reason" in saved


def test_down_clears_state_when_process_is_gone(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    _write_state(state, pid=777)
    monkeypatch.setattr(proxy_selector, "get_process_info", lambda pid: None)
    killed = []
    monkeypatch.setattr(proxy_selector, "terminate_pid", lambda pid: killed.append(pid))

    code = proxy_selector.main(["down", "--state-file", str(state)])

    assert code == 0
    assert killed == []
    assert not state.exists()


def test_down_is_noop_without_state(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    killed = []
    monkeypatch.setattr(proxy_selector, "terminate_pid", lambda pid: killed.append(pid))

    code = proxy_selector.main(["down", "--state-file", str(state)])

    assert code == 0
    assert killed == []


def test_check_reports_exit_ip_and_telegram(tmp_path, monkeypatch, capsys):
    happ, _ = _prepare(tmp_path, monkeypatch)

    code = proxy_selector.main(["check", "--socks-port", "11808"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload == {
        "socks_endpoint": "socks5h://127.0.0.1:11808",
        "exit_ip": "203.0.113.7",
        "telegram_web": 200,
    }


def test_check_reports_error_when_unreachable(tmp_path, monkeypatch, capsys):
    def boom(endpoint, timeout=10.0, url=""):
        raise RuntimeError("connection refused")

    happ, _ = _prepare(tmp_path, monkeypatch, exit_ip=boom)

    code = proxy_selector.main(["check"])

    assert code == proxy_selector.EXIT_ENV_ERROR
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["exit_ip"] is None
    assert payload["telegram_web"] is None
    assert "connection refused" in payload["error"]


def test_status_reports_state(tmp_path, monkeypatch, capsys):
    state = tmp_path / "state.json"
    _write_state(state, pid=888)
    monkeypatch.setattr(proxy_selector, "is_pid_alive", lambda pid: True)
    monkeypatch.setattr(proxy_selector, "is_port_open", lambda host, port, timeout=0.5: True)

    code = proxy_selector.main(["status", "--state-file", str(state)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["running"] is True
    assert payload["pid"] == 888
    assert payload["port_open"] is True


def test_parse_list_output_real_happ_fragment():
    servers = parse_list_output(REAL_LIST_FRAGMENT)

    assert len(servers) == 10
    assert [server.server_id for server in servers] == [str(index) for index in range(1, 11)]
    assert servers[5].country == "Нидерланды"
    assert servers[4].protocol == "shadowsocks"
    assert [server.server_id for server in select_servers(servers)] == ["6", "7", "8", "9", "10"]


def test_parse_list_output_strips_ansi_escapes():
    text = "\x1b[32m1   vless   84.32.61.112:8444   \x1b[0m🇸 VLESS³ - США\n"

    servers = parse_list_output(text)

    assert len(servers) == 1
    assert servers[0].protocol == "vless"
    assert servers[0].address == "84.32.61.112:8444"
    assert servers[0].country == "США"


def test_run_happ_list_decodes_utf8_and_keeps_cyrillic(monkeypatch):
    monkeypatch.setattr(
        proxy_selector.subprocess,
        "run",
        lambda *a, **k: _Completed(stdout=REAL_LIST_FRAGMENT.encode("utf-8")),
    )

    servers = parse_list_output(proxy_selector.run_happ_list("happ.exe"))

    assert any(server.country == "Нидерланды" for server in servers)
    assert len(select_servers(servers)) == 5


def test_run_happ_list_merges_stderr_when_table_is_there(monkeypatch):
    monkeypatch.setattr(
        proxy_selector.subprocess,
        "run",
        lambda *a, **k: _Completed(stderr=REAL_LIST_FRAGMENT.encode("utf-8")),
    )

    servers = parse_list_output(proxy_selector.run_happ_list("happ.exe"))

    assert len(select_servers(servers)) == 5


def test_run_happ_list_raises_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        proxy_selector.subprocess,
        "run",
        lambda *a, **k: _Completed(stderr=b"boom", returncode=1),
    )

    with pytest.raises(proxy_selector.ProxySelectorError):
        proxy_selector.run_happ_list("happ.exe")


def test_run_happ_list_raises_when_no_output(monkeypatch):
    monkeypatch.setattr(proxy_selector.subprocess, "run", lambda *a, **k: _Completed())

    with pytest.raises(proxy_selector.ProxySelectorError):
        proxy_selector.run_happ_list("happ.exe")


def test_list_command_prints_all_servers(tmp_path, monkeypatch, capsys):
    happ, _ = _prepare(tmp_path, monkeypatch)

    code = proxy_selector.main(["list", "--happ-exe", str(happ), "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert [server["server_id"] for server in payload["servers"]] == [
        "1",
        "6",
        "7",
        "8",
        "9",
        "10",
        "11",
        "16",
        "21",
    ]
    assert [server["server_id"] for server in payload["servers"] if server["country"] == "Нидерланды"] == [
        "6",
        "7",
        "8",
        "9",
        "10",
    ]


def test_select_servers_returns_empty_for_unknown_country():
    servers = parse_list_output(SAMPLE_LIST)

    assert select_servers(servers, ("нет-такой-страны",)) == []


def test_parse_list_output_ignores_header_and_noise():
    servers = parse_list_output("not a row\n" + SAMPLE_LIST + "\n\nrandom trailing text\n")

    assert len(servers) == 9
    assert isinstance(servers[0], ServerInfo)