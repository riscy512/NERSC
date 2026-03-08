"""
Redfish boot configuration: show/set permanent boot order and next boot (one-time override).

Uses the same cluster/iDrac pattern as redfish_power: resolve node name to iDrac IP
via cluster["hosts"]["byNode"][node_name]["network"]["iDrac"]["ip"], or pass idrac_ip directly.

Credentials: REDFISH_USER, REDFISH_PASSWORD env or user/password kwargs.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any, Optional

# BootSourceOverrideTarget common values (DMTF Redfish)
BOOT_TARGET_NONE = "None"
BOOT_TARGET_PXE = "Pxe"
BOOT_TARGET_CD = "Cd"
BOOT_TARGET_HDD = "Hdd"
BOOT_TARGET_USB = "Usb"
BOOT_TARGET_FLOPPY = "Floppy"
BOOT_TARGET_BIOS_SETUP = "BiosSetup"
BOOT_TARGET_UTILITIES = "Utilities"
BOOT_TARGET_UEFI_TARGET = "UefiTarget"
BOOT_TARGET_SDCARD = "SDCard"
BOOT_TARGET_UEFI_HTTP = "UefiHttp"

# BootSourceOverrideEnabled
BOOT_OVERRIDE_DISABLED = "Disabled"
BOOT_OVERRIDE_ONCE = "Once"
BOOT_OVERRIDE_CONTINUOUS = "Continuous"

# BootSourceOverrideMode
BOOT_MODE_UEFI = "Uefi"
BOOT_MODE_LEGACY = "Legacy"

DEFAULT_SYSTEM_ID = "System.Embedded.1"


def _request(
    method: str,
    url: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    body: Optional[dict[str, Any]] = None,
    verify_ssl: bool = False,
    timeout: int = 30,
) -> tuple[int, dict[str, Any] | None]:
    """HTTP request to Redfish. Returns (status_code, json_body or None)."""
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
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") if e.fp else ""
        return e.code, (json.loads(raw) if raw.strip() else None)
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return -1, None


def _get_system_id(
    idrac_ip: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> str:
    """Resolve system ID (e.g. System.Embedded.1)."""
    base = f"https://{idrac_ip}"
    url = f"{base}/redfish/v1/Systems"
    code, data = _request("GET", url, user=user, password=password, verify_ssl=verify_ssl)
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


def get_boot_config(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """
    GET full Boot object from ComputerSystem.
    Returns (boot_dict, error_message). boot_dict has BootOrder, BootSourceOverrideTarget,
    BootSourceOverrideEnabled, BootSourceOverrideMode, etc.
    """
    system_id = system_id or _get_system_id(idrac_ip, user=user, password=password, verify_ssl=verify_ssl)
    base = f"https://{idrac_ip}"
    url = f"{base}/redfish/v1/Systems/{system_id}"
    code, data = _request("GET", url, user=user, password=password, verify_ssl=verify_ssl)
    if code != 200 or not data:
        err = data.get("error", {}).get("message", str(data)) if isinstance(data, dict) else f"HTTP {code}"
        return None, err
    boot = data.get("Boot")
    if boot is None:
        return None, "Boot property not in response"
    return boot, None


def get_permanent_boot_order(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[Optional[list[str]], Optional[str]]:
    """
    Return the persistent (BIOS) boot order as a list of boot source IDs.
    Returns (order_list, error_message). order_list is e.g. ["NIC.Slot.5-1-1", "HardDisk.List.1-1"].
    """
    boot, err = get_boot_config(
        idrac_ip, system_id=system_id, user=user, password=password, verify_ssl=verify_ssl
    )
    if err or not boot:
        return None, (err or "no Boot config")
    order = boot.get("BootOrder")
    if order is None:
        return None, "BootOrder not in response (may be read-only or vendor-specific)"
    return list(order), None


def set_permanent_boot_order(
    idrac_ip: str,
    order: list[str],
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """
    PATCH the persistent boot order. order is a list of boot source IDs (e.g. from get_permanent_boot_order).
    Some BMCs require PATCH to .../Settings instead; this tries the main Systems resource.
    Returns (success, error_message).
    """
    system_id = system_id or _get_system_id(idrac_ip, user=user, password=password, verify_ssl=verify_ssl)
    base = f"https://{idrac_ip}"
    url = f"{base}/redfish/v1/Systems/{system_id}"
    body = {"Boot": {"BootOrder": order}}
    code, data = _request("PATCH", url, body=body, user=user, password=password, verify_ssl=verify_ssl)
    if code in (200, 204):
        return True, None
    msg = data.get("error", {}).get("message", str(data)) if isinstance(data, dict) else f"HTTP {code}"
    return False, msg


def get_next_boot(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """
    Return the current next-boot (override) settings.
    Returns (dict with BootSourceOverrideTarget, BootSourceOverrideEnabled, BootSourceOverrideMode; None values if not set, error_message).
    """
    boot, err = get_boot_config(
        idrac_ip, system_id=system_id, user=user, password=password, verify_ssl=verify_ssl
    )
    if err or not boot:
        return None, (err or "no Boot config")
    out = {
        "BootSourceOverrideTarget": boot.get("BootSourceOverrideTarget"),
        "BootSourceOverrideEnabled": boot.get("BootSourceOverrideEnabled"),
        "BootSourceOverrideMode": boot.get("BootSourceOverrideMode"),
        "UefiTargetBootSourceOverride": boot.get("UefiTargetBootSourceOverride"),
    }
    return out, None


def set_next_boot(
    idrac_ip: str,
    target: str,
    *,
    enabled: str = BOOT_OVERRIDE_ONCE,
    mode: Optional[str] = None,
    uefi_target: Optional[str] = None,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """
    Set next boot (one-time or continuous override).
    target: BootSourceOverrideTarget (e.g. BOOT_TARGET_PXE, BOOT_TARGET_HDD, BOOT_TARGET_NONE).
    enabled: BOOT_OVERRIDE_ONCE, BOOT_OVERRIDE_CONTINUOUS, or BOOT_OVERRIDE_DISABLED.
    mode: BOOT_MODE_UEFI or BOOT_MODE_LEGACY (optional).
    uefi_target: UEFI device path when target is UefiTarget (optional).
    Returns (success, error_message).
    """
    system_id = system_id or _get_system_id(idrac_ip, user=user, password=password, verify_ssl=verify_ssl)
    base = f"https://{idrac_ip}"
    url = f"{base}/redfish/v1/Systems/{system_id}"
    body = {
        "Boot": {
            "BootSourceOverrideTarget": target,
            "BootSourceOverrideEnabled": enabled,
        }
    }
    if mode is not None:
        body["Boot"]["BootSourceOverrideMode"] = mode
    if uefi_target is not None:
        body["Boot"]["UefiTargetBootSourceOverride"] = uefi_target
    code, data = _request("PATCH", url, body=body, user=user, password=password, verify_ssl=verify_ssl)
    if code in (200, 204):
        return True, None
    msg = data.get("error", {}).get("message", str(data)) if isinstance(data, dict) else f"HTTP {code}"
    return False, msg


def clear_next_boot(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """Clear next-boot override (use normal boot order). Returns (success, error_message)."""
    return set_next_boot(
        idrac_ip, BOOT_TARGET_NONE, enabled=BOOT_OVERRIDE_DISABLED,
        system_id=system_id, user=user, password=password, verify_ssl=verify_ssl,
    )


def get_boot_options(
    idrac_ip: str,
    *,
    system_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[Optional[list[dict[str, Any]]], Optional[str]]:
    """
    GET BootOptions collection (all boot sources the BIOS knows about).
    Returns (list of boot option dicts, error_message). Vendor-specific; may not be supported.
    """
    system_id = system_id or _get_system_id(idrac_ip, user=user, password=password, verify_ssl=verify_ssl)
    base = f"https://{idrac_ip}"
    url = f"{base}/redfish/v1/Systems/{system_id}/BootOptions"
    code, data = _request("GET", url, user=user, password=password, verify_ssl=verify_ssl)
    if code != 200 or not data:
        err = data.get("error", {}).get("message", str(data)) if isinstance(data, dict) else f"HTTP {code}"
        return None, err
    members = data.get("Members", [])
    out = []
    for m in members:
        odata_id = m.get("@odata.id", "")
        if odata_id.startswith("/"):
            odata_id = base.replace(f"https://{idrac_ip}", "") + odata_id
        else:
            odata_id = f"{base}/redfish/v1/Systems/{system_id}/BootOptions" + odata_id
        out.append({"Id": m.get("Id"), "Description": m.get("Description"), "@odata.id": odata_id})
    return out, None


# --- Cluster/node name helpers (optional dependency on redfish_power for get_idrac_ip_for_node)
def _get_idrac_ip(cluster: Optional[dict], node_name: Optional[str], idrac_ip: Optional[str]) -> Optional[str]:
    if idrac_ip:
        return idrac_ip
    if cluster and node_name:
        try:
            from redfish_power import get_idrac_ip_for_node
            return get_idrac_ip_for_node(cluster, node_name)
        except ImportError:
            pass
    return None


def run_for_node(
    cluster: dict[str, Any],
    node_name: str,
    action: str,
    *,
    order: Optional[list[str]] = None,
    target: Optional[str] = None,
    enabled: str = BOOT_OVERRIDE_ONCE,
    mode: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str], Any]:
    """
    Run a boot action for a node by name (resolves iDrac IP from cluster).
    action: 'show_permanent' | 'set_permanent' | 'show_next' | 'set_next' | 'clear_next' | 'show_options'.
    For set_permanent pass order=[...]. For set_next pass target=..., optional enabled=, mode=.
    Returns (success, error_message, result). result: for show_* is the dict/list; for set_* is None.
    """
    ip = _get_idrac_ip(cluster, node_name, None)
    if not ip:
        return False, "no iDrac IP for node", None
    action = action.lower().strip()
    if action == "show_permanent":
        order_list, err = get_permanent_boot_order(ip, user=user, password=password, verify_ssl=verify_ssl)
        return (err is None), err, order_list
    if action == "set_permanent":
        if not order:
            return False, "set_permanent requires order= [...]", None
        ok, err = set_permanent_boot_order(ip, order, user=user, password=password, verify_ssl=verify_ssl)
        return ok, err, None
    if action == "show_next":
        next_d, err = get_next_boot(ip, user=user, password=password, verify_ssl=verify_ssl)
        return (err is None), err, next_d
    if action == "set_next":
        if target is None:
            return False, "set_next requires target= ...", None
        ok, err = set_next_boot(
            ip, target, enabled=enabled, mode=mode,
            user=user, password=password, verify_ssl=verify_ssl,
        )
        return ok, err, None
    if action == "clear_next":
        ok, err = clear_next_boot(ip, user=user, password=password, verify_ssl=verify_ssl)
        return ok, err, None
    if action == "show_options":
        opts, err = get_boot_options(ip, user=user, password=password, verify_ssl=verify_ssl)
        return (err is None), err, opts
    return False, f"unknown action: {action}", None
