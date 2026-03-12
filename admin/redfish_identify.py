"""
Redfish chassis identify/beacon LED (IndicatorLED).

Uses the same cluster/iDrac pattern as redfish_power: resolve node name to iDrac IP
via cluster["hosts"]["byNode"][node_name]["network"]["iDrac"]["ip"].

DMTF Redfish Chassis IndicatorLED: "Lit" | "Blinking" | "Off".
Dell iDRAC typically supports Lit and Off; Blinking may be supported on newer firmware.
"""

from __future__ import annotations

from typing import Any, Optional

# IndicatorLED values (DMTF Redfish Chassis)
INDICATOR_LIT = "Lit"
INDICATOR_BLINKING = "Blinking"
INDICATOR_OFF = "Off"

DEFAULT_CHASSIS_ID = "System.Embedded.1"


def _redfish_request(
    method: str,
    url: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    body: Optional[dict[str, Any]] = None,
    verify_ssl: bool = False,
    timeout: int = 30,
):
    """Use redfish_power's request helper for consistency."""
    from redfish_power import _redfish_request as _req
    return _req(method, url, user=user, password=password, body=body, verify_ssl=verify_ssl, timeout=timeout)


def _redfish_error_message(data: Any, status_code: int) -> str:
    """Extract a readable error from Redfish error response, including ExtendedInfo."""
    if not isinstance(data, dict):
        return str(status_code)
    err = data.get("error", data)
    if not isinstance(err, dict):
        return str(data) if data else str(status_code)
    # Prefer @Message.ExtendedInfo[0].Message (or .MessageId) over generic message
    ext = err.get("@Message.ExtendedInfo") or err.get("ExtendedInfo")
    if isinstance(ext, list) and ext:
        first = ext[0]
        if isinstance(first, dict):
            msg = first.get("Message") or first.get("MessageId")
            if msg:
                return msg
    return err.get("message") or str(status_code)


def get_chassis_id(
    idrac_ip: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> str:
    """
    Discover the Redfish Chassis ID (e.g. System.Embedded.1) from the BMC.
    Returns the first chassis member ID or DEFAULT_CHASSIS_ID if discovery fails.
    """
    base = f"https://{idrac_ip}"
    url = f"{base}/redfish/v1/Chassis"
    code, data = _redfish_request("GET", url, user=user, password=password, verify_ssl=verify_ssl)
    if code != 200 or not data:
        return DEFAULT_CHASSIS_ID
    members = data.get("Members", [])
    if not members:
        return DEFAULT_CHASSIS_ID
    first = members[0]
    ref = first.get("@odata.id", "")
    if ref.startswith("/"):
        ref = ref.split("/")[-1]
    else:
        ref = ref.split("/")[-1] if "/" in ref else first.get("Id", DEFAULT_CHASSIS_ID)
    return ref or DEFAULT_CHASSIS_ID


def indicator_led_set(
    idrac_ip: str,
    state: str,
    *,
    chassis_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """
    Set chassis identify/beacon LED. state: "Lit" | "Blinking" | "Off".
    Tries IndicatorLED first; if the BMC reports it not found, falls back to
    LocationIndicatorActive (boolean), which many iDRACs use instead.
    Returns (success, error_message or None).
    """
    chassis_id = chassis_id or get_chassis_id(idrac_ip, user=user, password=password, verify_ssl=verify_ssl)
    base = f"https://{idrac_ip}"
    url = f"{base}/redfish/v1/Chassis/{chassis_id}"
    code, data = _redfish_request("PATCH", url, body={"IndicatorLED": state}, user=user, password=password, verify_ssl=verify_ssl)
    if code in (200, 204):
        return True, None
    msg = _redfish_error_message(data, code)
    # Fallback: many BMCs (e.g. newer iDRAC) use LocationIndicatorActive (boolean) instead of IndicatorLED
    if code in (400, 404) or (msg and "IndicatorLED" in msg and ("not found" in msg.lower() or "invalid" in msg.lower())):
        active = state != INDICATOR_OFF
        code2, data2 = _redfish_request("PATCH", url, body={"LocationIndicatorActive": active}, user=user, password=password, verify_ssl=verify_ssl)
        if code2 in (200, 204):
            return True, None
        msg = _redfish_error_message(data2, code2)
    if code in (401, 403) or (msg and "credential" in msg.lower() and ("missing" in msg.lower() or "invalid" in msg.lower())):
        msg = f"{msg}. Set REDFISH_USER and REDFISH_PASSWORD (env) or use -U / -P with omniactl."
    return False, msg


def indicator_led_status(
    idrac_ip: str,
    *,
    chassis_id: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    """
    Get current IndicatorLED state. Returns (IndicatorLED value, full chassis json or None).
    """
    chassis_id = chassis_id or get_chassis_id(idrac_ip, user=user, password=password, verify_ssl=verify_ssl)
    base = f"https://{idrac_ip}"
    url = f"{base}/redfish/v1/Chassis/{chassis_id}"
    code, data = _redfish_request("GET", url, user=user, password=password, verify_ssl=verify_ssl)
    if code != 200 or not data:
        return None, None
    led = data.get("IndicatorLED")
    if led is not None:
        return led, data
    # Fallback: read LocationIndicatorActive (boolean) when IndicatorLED not present
    active = data.get("LocationIndicatorActive")
    if active is True:
        return "Lit", data
    if active is False:
        return "Off", data
    return None, data


def run_for_node(
    cluster: dict[str, Any],
    node_name: str,
    action: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """
    Run an identify/beacon action for a node by name using the cluster's iDrac IP.
    action: "on" | "off" | "blink" | "status".
    Returns (success, message). For "status", message is the IndicatorLED value; else error or None.
    """
    from redfish_power import get_idrac_ip_for_node
    ip = get_idrac_ip_for_node(cluster, node_name)
    if not ip:
        return False, "no iDrac IP for node"
    action = action.lower().strip()
    if action == "on":
        return indicator_led_set(ip, INDICATOR_LIT, user=user, password=password, verify_ssl=verify_ssl)
    if action == "off":
        return indicator_led_set(ip, INDICATOR_OFF, user=user, password=password, verify_ssl=verify_ssl)
    if action == "blink" or action == "blinking":
        ok, msg = indicator_led_set(ip, INDICATOR_BLINKING, user=user, password=password, verify_ssl=verify_ssl)
        if not ok and msg:
            return False, f"{msg} (try 'identify on' if this BMC only supports Lit/Off)"
        return ok, msg
    if action == "status":
        state, _ = indicator_led_status(ip, user=user, password=password, verify_ssl=verify_ssl)
        return state is not None, (state or "unknown")
    return False, f"unknown action: {action}"
