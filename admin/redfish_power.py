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
) -> tuple[int, dict[str, Any] | None]:
    """
    Perform an HTTP request to a Redfish endpoint. Returns (status_code, json_body or None).
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
    try:
        with urllib.request.urlopen(req, timeout=t, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") if e.fp else ""
        return e.code, (json.loads(raw) if raw.strip() else None)
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return -1, None


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
    code, data = _redfish_request("GET", url, user=user, password=password, verify_ssl=verify_ssl)
    if code != 200 or not data:
        return DEFAULT_SYSTEM_ID
    members = data.get("Members", [])
    if not members:
        return DEFAULT_SYSTEM_ID
    first = members[0]
    ref = first.get("@odata.id", "")
    if ref.startswith("/"):
        ref = ref.split("/")[-1]
    else:
        ref = ref.split("/")[-1] if "/" in ref else first.get("Id", DEFAULT_SYSTEM_ID)
    return ref or DEFAULT_SYSTEM_ID


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
    code, data = _redfish_request("GET", url, user=user, password=password, verify_ssl=verify_ssl)
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
    code, data = _redfish_request(
        "POST", url, body={"ResetType": reset_type},
        user=user, password=password, verify_ssl=verify_ssl,
    )
    if code in (200, 204):
        return True, None
    msg = data.get("error", {}).get("message", str(data)) if isinstance(data, dict) else str(code)
    return False, msg


def power_on(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """Power on the system. Returns (success, error_message or None)."""
    return reset(idrac_ip, RESET_ON, system_id=system_id, user=user, password=password, verify_ssl=verify_ssl)


def power_off(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """Power off the system (soft). Returns (success, error_message or None)."""
    return reset(idrac_ip, RESET_OFF, system_id=system_id, user=user, password=password, verify_ssl=verify_ssl)


def power_force_off(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """Force power off without graceful shutdown. Returns (success, error_message or None)."""
    return reset(idrac_ip, RESET_FORCE_OFF, system_id=system_id, user=user, password=password, verify_ssl=verify_ssl)


def power_graceful_shutdown(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """Request graceful OS shutdown. Returns (success, error_message or None)."""
    return reset(
        idrac_ip, RESET_GRACEFUL_SHUTDOWN,
        system_id=system_id, user=user, password=password, verify_ssl=verify_ssl,
    )


def power_reset(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """Force restart (reset) the system. Returns (success, error_message or None)."""
    return reset(
        idrac_ip, RESET_FORCE_RESTART,
        system_id=system_id, user=user, password=password, verify_ssl=verify_ssl,
    )


def power_cycle(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """Power cycle (off then on). Returns (success, error_message or None)."""
    return reset(
        idrac_ip, RESET_POWER_CYCLE,
        system_id=system_id, user=user, password=password, verify_ssl=verify_ssl,
    )


def power_graceful_restart(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """Graceful restart. Returns (success, error_message or None)."""
    return reset(
        idrac_ip, RESET_GRACEFUL_RESTART,
        system_id=system_id, user=user, password=password, verify_ssl=verify_ssl,
    )


def power_nmi(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """Send NMI (Non-Maskable Interrupt). Returns (success, error_message or None)."""
    return reset(idrac_ip, RESET_NMI, system_id=system_id, user=user, password=password, verify_ssl=verify_ssl)


def run_for_node(
    cluster: dict[str, Any],
    node_name: str,
    action: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
    timeout: int = 30,
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
        if action == "on":
            return power_on(ip, user=user, password=password, verify_ssl=verify_ssl)
        if action == "off":
            return power_off(ip, user=user, password=password, verify_ssl=verify_ssl)
        if action == "force_off":
            return power_force_off(ip, user=user, password=password, verify_ssl=verify_ssl)
        if action == "reset":
            return power_reset(ip, user=user, password=password, verify_ssl=verify_ssl)
        if action == "cycle":
            return power_cycle(ip, user=user, password=password, verify_ssl=verify_ssl)
        if action == "graceful_shutdown":
            return power_graceful_shutdown(ip, user=user, password=password, verify_ssl=verify_ssl)
        if action == "graceful_restart":
            return power_graceful_restart(ip, user=user, password=password, verify_ssl=verify_ssl)
        if action == "nmi":
            return power_nmi(ip, user=user, password=password, verify_ssl=verify_ssl)
        if action == "status":
            state, _ = power_status(ip, user=user, password=password, verify_ssl=verify_ssl)
            return state is not None, (state or "unknown")
        return False, f"unknown action: {action}"
