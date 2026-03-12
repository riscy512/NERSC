"""
Redfish chassis identify/beacon LED. Modeled after:

  curl -k -u root:password -X PATCH -H "Content-Type: application/json" \\
    https://idrac-ip/redfish/v1/Chassis/System.Embedded.1 -d '{"IndicatorLED":"Blinking"}'

Uses cluster iDrac IP from omniaHosts; credentials from env or -U/-P.
"""

from __future__ import annotations

from typing import Any, Optional

CHASSIS_ID = "System.Embedded.1"


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
    from redfish_power import _redfish_request as _req
    return _req(method, url, user=user, password=password, body=body, verify_ssl=verify_ssl, timeout=timeout)


def indicator_led_set(
    idrac_ip: str,
    state: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """PATCH /redfish/v1/Chassis/System.Embedded.1 with {"IndicatorLED": state}. state is "Blinking" or "Off"."""
    url = f"https://{idrac_ip}/redfish/v1/Chassis/{CHASSIS_ID}"
    code, data = _redfish_request("PATCH", url, body={"IndicatorLED": state}, user=user, password=password, verify_ssl=verify_ssl)
    if code in (200, 204):
        return True, None
    msg = None
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        ext = err.get("@Message.ExtendedInfo") or err.get("ExtendedInfo")
        if isinstance(ext, list) and ext and isinstance(ext[0], dict):
            msg = ext[0].get("Message") or ext[0].get("MessageId")
        msg = msg or err.get("message")
    msg = msg or str(code)
    if code in (401, 403) or "credential" in msg.lower():
        msg = f"{msg} Set OMNIA_REDFISH_USER/OMNIA_REDFISH_PASSWORD or REDFISH_USER/REDFISH_PASSWORD or -U/-P."
    return False, msg


def indicator_led_status(
    idrac_ip: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    """GET /redfish/v1/Chassis/System.Embedded.1, return IndicatorLED value."""
    url = f"https://{idrac_ip}/redfish/v1/Chassis/{CHASSIS_ID}"
    code, data = _redfish_request("GET", url, user=user, password=password, verify_ssl=verify_ssl)
    if code != 200 or not data:
        return None, None
    return data.get("IndicatorLED"), data


def run_for_node(
    cluster: dict[str, Any],
    node_name: str,
    action: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """Resolve node to iDrac IP, then set or get IndicatorLED. on/blink -> Blinking, off -> Off."""
    from redfish_power import get_idrac_ip_for_node
    ip = get_idrac_ip_for_node(cluster, node_name)
    if not ip:
        return False, "no iDrac IP for node"
    action = action.lower().strip()
    if action in ("on", "blink", "blinking"):
        return indicator_led_set(ip, "Blinking", user=user, password=password, verify_ssl=verify_ssl)
    if action == "off":
        return indicator_led_set(ip, "Off", user=user, password=password, verify_ssl=verify_ssl)
    if action == "status":
        state, _ = indicator_led_status(ip, user=user, password=password, verify_ssl=verify_ssl)
        return state is not None, (state or "unknown")
    return False, f"unknown action: {action}"
