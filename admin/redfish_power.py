"""
Redfish-based power management for nodes with an iDrac (BMC) network.

Designed for use with the cluster index from omniaHosts: nodes that have the
iDrac network defined can be powered on/off, reset, or queried for status
via the Redfish API (Dell iDRAC, or other Redfish-compliant BMCs).

Requires: cluster["hosts"]["byNode"][node_name]["network"]["iDrac"]["ip"]
Optional: REDFISH_USER, REDFISH_PASSWORD env vars for BMC credentials.
"""

from __future__ import annotations

import base64
import contextvars
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import Any, Iterator, Optional

# Per-thread HTTP timeout for urllib (used by run_for_node and parallel fanout).
_http_timeout_ctx: contextvars.ContextVar[int] = contextvars.ContextVar("_http_timeout_ctx", default=30)


@contextmanager
def redfish_http_timeout_scope(seconds: int) -> Iterator[None]:
    """Set urllib read timeout for Redfish calls in this thread (nested scopes restore correctly)."""
    tok = _http_timeout_ctx.set(max(1, int(seconds)))
    try:
        yield
    finally:
        _http_timeout_ctx.reset(tok)

# Default Redfish system ID for Dell iDRAC (can be overridden after discovery)
DEFAULT_SYSTEM_ID = "System.Embedded.1"

# ResetType values per DMTF Redfish (ComputerSystem.Reset)
RESET_ON = "On"
RESET_OFF = "Off"
RESET_FORCE_OFF = "ForceOff"
RESET_GRACEFUL_SHUTDOWN = "GracefulShutdown"
RESET_GRACEFUL_RESTART = "GracefulRestart"
RESET_FORCE_RESTART = "ForceRestart"
RESET_POWER_CYCLE = "PowerCycle"
RESET_NMI = "Nmi"
RESET_FORCE_ON = "ForceOn"
RESET_PUSH_POWER_BUTTON = "PushPowerButton"
RESET_SUSPEND = "Suspend"
RESET_PAUSE = "Pause"
RESET_RESUME = "Resume"


def _redfish_request(
    method: str,
    url: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    body: Optional[dict[str, Any]] = None,
    verify_ssl: bool = True,
    timeout: Optional[int] = None,
) -> tuple[int, dict[str, Any] | None, dict[str, str]]:
    """
    Perform an HTTP request to a Redfish endpoint.
    Returns (status_code, json_body or None, response_headers lower-cased keys).
    If timeout is None, uses the current thread's redfish_http_timeout_scope (default 30s).
    """
    t = timeout if timeout is not None else _http_timeout_ctx.get()
    user = user or os.environ.get("REDFISH_USER", "")
    password = password or os.environ.get("REDFISH_PASSWORD", "")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    if user or password:
        creds = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    ctx = ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    empty_hdrs: dict[str, str] = {}
    try:
        with urllib.request.urlopen(req, timeout=t, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
            rh = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, json.loads(raw) if raw else None, rh
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") if e.fp else ""
        rh = {k.lower(): v for k, v in e.headers.items()} if e.headers else empty_hdrs
        return e.code, (json.loads(raw) if raw.strip() else None), rh
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        return -1, {"error": {"message": f"transport error ({method} {url}): {reason}"}}, empty_hdrs
    except json.JSONDecodeError as e:
        return -1, {"error": {"message": f"invalid JSON response ({method} {url}): {e}"}}, empty_hdrs
    except OSError as e:
        return -1, {"error": {"message": f"os error ({method} {url}): {e}"}}, empty_hdrs


def _redfish_error_message(data: Any, status_code: int) -> str:
    """Extract best-effort error detail from Redfish response payload."""
    if not isinstance(data, dict):
        return str(status_code)
    err = data.get("error", data)
    if not isinstance(err, dict):
        return str(data) if data else str(status_code)
    ext = err.get("@Message.ExtendedInfo") or err.get("ExtendedInfo")
    if isinstance(ext, list) and ext:
        first = ext[0]
        if isinstance(first, dict):
            msg = first.get("Message") or first.get("MessageId")
            if msg:
                return msg
    return err.get("message") or str(status_code)


def _reset_body_indicates_failure(data: Any) -> Optional[str]:
    """
    Some BMCs return HTTP 200/202 with a Redfish error object or Critical ExtendedInfo.
    Treat those as failure even when the status code is success.
    """
    if not isinstance(data, dict) or not data:
        return None
    if "error" in data:
        return _redfish_error_message(data, 200)
    ext = data.get("@Message.ExtendedInfo")
    if not isinstance(ext, list):
        return None
    msgs: list[str] = []
    for item in ext:
        if not isinstance(item, dict):
            continue
        sev = (item.get("Severity") or "").strip().lower()
        if sev in ("critical", "error"):
            m = item.get("Message") or item.get("MessageId") or sev
            msgs.append(str(m))
    if msgs:
        return "; ".join(msgs)
    return None


def get_idrac_ip_for_node(cluster: dict[str, Any], node_name: str) -> Optional[str]:
    """
    Return the iDrac (BMC) IP for a node from the cluster index, or None if not defined.
    """
    try:
        node = cluster.get("hosts", {}).get("byNode", {}).get(node_name, {})
        net = node.get("network", {}).get("iDrac", {})
        return net.get("ip")
    except (AttributeError, TypeError):
        return None


def get_system_id(
    idrac_ip: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> Optional[str]:
    """
    Discover the Redfish ComputerSystem ID (e.g. System.Embedded.1) from the BMC.
    Uses DEFAULT_SYSTEM_ID if discovery fails or only one system is present.
    """
    base = f"https://{idrac_ip}"
    url = f"{base}/redfish/v1/Systems"
    code, data, _ = _redfish_request("GET", url, user=user, password=password, verify_ssl=verify_ssl)
    if code != 200 or not data:
        return DEFAULT_SYSTEM_ID
    members = data.get("Members", [])
    if not members:
        return DEFAULT_SYSTEM_ID
    ids: list[str] = []
    for m in members:
        if not isinstance(m, dict):
            continue
        ref = m.get("@odata.id", "")
        if ref.startswith("/"):
            sid = ref.split("/")[-1]
        else:
            sid = ref.split("/")[-1] if "/" in ref else str(m.get("Id", ""))
        if sid:
            ids.append(sid)
    if not ids:
        return DEFAULT_SYSTEM_ID
    if DEFAULT_SYSTEM_ID in ids:
        return DEFAULT_SYSTEM_ID
    return ids[0]


def power_status(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    """
    Get current power state. Returns (PowerState, full_system_json or None).
    PowerState is typically 'On', 'Off', 'PoweringOn', 'PoweringOff'.
    """
    system_id = system_id or get_system_id(idrac_ip, user=user, password=password, verify_ssl=verify_ssl)
    base = f"https://{idrac_ip}"
    url = f"{base}/redfish/v1/Systems/{system_id}"
    code, data, _ = _redfish_request("GET", url, user=user, password=password, verify_ssl=verify_ssl)
    if code != 200 or not data:
        return None, None
    return data.get("PowerState"), data


def reset(
    idrac_ip: str,
    reset_type: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
    debug_sink: Optional[list[str]] = None,
) -> tuple[bool, Optional[str]]:
    """
    Execute a Redfish ComputerSystem.Reset action.
    reset_type: one of RESET_* constants (On, Off, ForceOff, GracefulShutdown,
                ForceRestart, PowerCycle, GracefulRestart, Nmi, etc.).
    Returns (success, error_message or None).
    """
    system_id = system_id or get_system_id(idrac_ip, user=user, password=password, verify_ssl=verify_ssl)
    base = f"https://{idrac_ip}"
    url = f"{base}/redfish/v1/Systems/{system_id}/Actions/ComputerSystem.Reset"
    code, data, headers = _redfish_request(
        "POST", url, body={"ResetType": reset_type},
        user=user, password=password, verify_ssl=verify_ssl,
    )

    def _dbg(line: str) -> None:
        if debug_sink is not None:
            debug_sink.append(line)

    _dbg(f"POST {url} ResetType={reset_type} system_id={system_id} -> HTTP {code}")
    if data is not None:
        try:
            snippet = json.dumps(data, separators=(",", ":"))
            if len(snippet) > 480:
                snippet = snippet[:480] + "…"
            _dbg(f"response JSON: {snippet}")
        except (TypeError, ValueError):
            _dbg("response JSON: <unserializable>")
    loc = headers.get("location")
    if loc:
        _dbg(f"Location: {loc}")

    if code not in (200, 202, 204):
        msg = _redfish_error_message(data, code)
        return False, msg
    body_err = _reset_body_indicates_failure(data)
    if body_err:
        return False, body_err
    return True, None


def power_on(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
    debug_sink: Optional[list[str]] = None,
) -> tuple[bool, Optional[str]]:
    """Power on the system. Returns (success, error_message or None)."""
    return reset(
        idrac_ip, RESET_ON,
        system_id=system_id, user=user, password=password, verify_ssl=verify_ssl, debug_sink=debug_sink,
    )


def power_off(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
    debug_sink: Optional[list[str]] = None,
) -> tuple[bool, Optional[str]]:
    """Power off via ForceOff (matches typical iDRAC behavior; Off is often ineffective)."""
    return reset(
        idrac_ip, RESET_FORCE_OFF,
        system_id=system_id, user=user, password=password, verify_ssl=verify_ssl, debug_sink=debug_sink,
    )


def power_force_off(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
    debug_sink: Optional[list[str]] = None,
) -> tuple[bool, Optional[str]]:
    """Force power off without graceful shutdown. Returns (success, error_message or None)."""
    return reset(
        idrac_ip, RESET_FORCE_OFF,
        system_id=system_id, user=user, password=password, verify_ssl=verify_ssl, debug_sink=debug_sink,
    )


def power_graceful_shutdown(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
    debug_sink: Optional[list[str]] = None,
) -> tuple[bool, Optional[str]]:
    """Request graceful OS shutdown. Returns (success, error_message or None)."""
    return reset(
        idrac_ip, RESET_GRACEFUL_SHUTDOWN,
        system_id=system_id, user=user, password=password, verify_ssl=verify_ssl, debug_sink=debug_sink,
    )


def power_reset(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
    debug_sink: Optional[list[str]] = None,
) -> tuple[bool, Optional[str]]:
    """Force restart (reset) the system. Returns (success, error_message or None)."""
    return reset(
        idrac_ip, RESET_FORCE_RESTART,
        system_id=system_id, user=user, password=password, verify_ssl=verify_ssl, debug_sink=debug_sink,
    )


def power_cycle(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
    debug_sink: Optional[list[str]] = None,
) -> tuple[bool, Optional[str]]:
    """Power cycle (off then on). Returns (success, error_message or None)."""
    return reset(
        idrac_ip, RESET_POWER_CYCLE,
        system_id=system_id, user=user, password=password, verify_ssl=verify_ssl, debug_sink=debug_sink,
    )


def power_graceful_restart(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
    debug_sink: Optional[list[str]] = None,
) -> tuple[bool, Optional[str]]:
    """Graceful restart. Returns (success, error_message or None)."""
    return reset(
        idrac_ip, RESET_GRACEFUL_RESTART,
        system_id=system_id, user=user, password=password, verify_ssl=verify_ssl, debug_sink=debug_sink,
    )


def power_nmi(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
    debug_sink: Optional[list[str]] = None,
) -> tuple[bool, Optional[str]]:
    """Send NMI (Non-Maskable Interrupt). Returns (success, error_message or None)."""
    return reset(
        idrac_ip, RESET_NMI,
        system_id=system_id, user=user, password=password, verify_ssl=verify_ssl, debug_sink=debug_sink,
    )


def run_for_node(
    cluster: dict[str, Any],
    node_name: str,
    action: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
    timeout: int = 30,
    debug: bool = False,
) -> tuple[bool, Optional[str]]:
    """
    Run a power action for a node by name using the cluster's iDrac IP.
    action: one of 'on', 'off', 'force_off', 'status', 'reset', 'cycle', 'graceful_shutdown', 'graceful_restart', 'nmi'.
    Returns (success, error_message or None). For 'status', success is True if we got a state; error_message holds the state string.
    timeout: per-HTTP-request read timeout in seconds (urllib); use with omniactl --redfish-timeout / fanout.
    """
    with redfish_http_timeout_scope(timeout):
        ip = get_idrac_ip_for_node(cluster, node_name)
        if not ip:
            return False, "no iDrac IP for node"
        action = action.lower().strip()
        sink: Optional[list[str]] = [] if debug and action != "status" else None
        if sink is not None and action in ("reset", "cycle", "graceful_restart"):
            st0, _ = power_status(ip, user=user, password=password, verify_ssl=verify_ssl)
            sink.append(f"PowerState before: {st0}")

        def _with_ctx(res: tuple[bool, Optional[str]]) -> tuple[bool, Optional[str]]:
            ok, msg = res
            if not debug or ok:
                return res
            return False, f"{msg or 'unknown'} [node={node_name} ip={ip} action={action} timeout={timeout}s]"

        def _finish(res: tuple[bool, Optional[str]]) -> tuple[bool, Optional[str]]:
            if sink is not None and action in ("reset", "cycle", "graceful_restart") and res[0]:
                time.sleep(2)
                st1, _ = power_status(ip, user=user, password=password, verify_ssl=verify_ssl)
                sink.append(f"PowerState after ~2s: {st1}")
            if sink is not None:
                for line in sink:
                    print(f"# {node_name}: {line}", file=sys.stderr)
            return _with_ctx(res)

        if action == "on":
            return _finish(power_on(ip, user=user, password=password, verify_ssl=verify_ssl, debug_sink=sink))
        if action == "off":
            return _finish(power_off(ip, user=user, password=password, verify_ssl=verify_ssl, debug_sink=sink))
        if action == "force_off":
            return _finish(power_force_off(ip, user=user, password=password, verify_ssl=verify_ssl, debug_sink=sink))
        if action == "reset":
            return _finish(power_reset(ip, user=user, password=password, verify_ssl=verify_ssl, debug_sink=sink))
        if action == "cycle":
            return _finish(power_cycle(ip, user=user, password=password, verify_ssl=verify_ssl, debug_sink=sink))
        if action == "graceful_shutdown":
            return _finish(power_graceful_shutdown(ip, user=user, password=password, verify_ssl=verify_ssl, debug_sink=sink))
        if action == "graceful_restart":
            return _finish(power_graceful_restart(ip, user=user, password=password, verify_ssl=verify_ssl, debug_sink=sink))
        if action == "nmi":
            return _finish(power_nmi(ip, user=user, password=password, verify_ssl=verify_ssl, debug_sink=sink))
        if action == "status":
            state, _ = power_status(ip, user=user, password=password, verify_ssl=verify_ssl)
            if state is not None:
                return True, state
            if debug:
                return False, f"status unavailable [node={node_name} ip={ip} action={action} timeout={timeout}s]"
            return False, "unknown"
        return False, f"unknown action: {action}"
