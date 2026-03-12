"""
Redfish chassis identify/beacon light using LocationIndicatorActive.

Modeled after:

  curl -k -u root:password -X PATCH -H "Content-Type: application/json" \
    https://idrac-ip/redfish/v1/Chassis/System.Embedded.1 -d '{"LocationIndicatorActive":true}'

Uses cluster iDrac IP from omniaHosts; credentials from env or -U/-P.
"""

from __future__ import annotations

from typing import Optional

CHASSIS_ID = "System.Embedded.1"


def _redfish_request(
    method: str,
    url: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    body: Optional[dict[str, object]] = None,
    verify_ssl: bool = False,
    timeout: int = 30,
) -> tuple[int, Optional[dict[str, object]]]:
    from redfish_power import _redfish_request as _req
    return _req(method, url, user=user, password=password, body=body, verify_ssl=verify_ssl, timeout=timeout)


def location_indicator_set(
    idrac_ip: str,
    active: bool,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """
    PATCH /redfish/v1/Chassis/System.Embedded.1 with {"LocationIndicatorActive": true|false}.
    active=True turns the identify light on (blink or lit, per BMC); active=False turns it off.
    """
    url = f"https://{idrac_ip}/redfish/v1/Chassis/{CHASSIS_ID}"
    code, data = _redfish_request(
        "PATCH",
        url,
        body={"LocationIndicatorActive": active},
        user=user,
        password=password,
        verify_ssl=verify_ssl,
    )
    if code in (200, 204):
        return True, None
    msg = str(code)
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        ext = err.get("@Message.ExtendedInfo") or err.get("ExtendedInfo")
        if isinstance(ext, list) and ext and isinstance(ext[0], dict):
            msg = ext[0].get("Message") or ext[0].get("MessageId") or msg
        msg = err.get("message") or msg
    if code in (401, 403) or "credential" in msg.lower():
        msg = f"{msg} Set OMNIA_REDFISH_USER/OMNIA_REDFISH_PASSWORD or REDFISH_USER/REDFISH_PASSWORD or -U/-P."
    return False, msg


def location_indicator_status(
    idrac_ip: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[Optional[str], Optional[dict[str, object]]]:
    """GET /redfish/v1/Chassis/System.Embedded.1, return LocationIndicatorActive as 'on'/'off'/None."""
    url = f"https://{idrac_ip}/redfish/v1/Chassis/{CHASSIS_ID}"
    code, data = _redfish_request("GET", url, user=user, password=password, verify_ssl=verify_ssl)
    if code != 200 or not isinstance(data, dict):
        return None, None
    val = data.get("LocationIndicatorActive")
    if val is True:
        return "on", data
    if val is False:
        return "off", data
    return None, data


def run_for_node(
    cluster: dict[str, object],
    node_name: str,
    action: str,
    *,
    user: Optional[str] = None,
    password: Optional[str] = None,
    verify_ssl: bool = False,
) -> tuple[bool, Optional[str]]:
    """Resolve node to iDrac IP, then set or get LocationIndicatorActive. on/blink->true, off->false."""
    from redfish_power import get_idrac_ip_for_node

    ip = get_idrac_ip_for_node(cluster, node_name)
    if not ip:
        return False, "no iDrac IP for node"
    action = action.lower().strip()
    if action in ("blink", "blinking", "on"):
        return location_indicator_set(ip, True, user=user, password=password, verify_ssl=verify_ssl)
    if action == "off":
        return location_indicator_set(ip, False, user=user, password=password, verify_ssl=verify_ssl)
    if action == "status":
        state, _ = location_indicator_status(ip, user=user, password=password, verify_ssl=verify_ssl)
        return state is not None, (state or "unknown")
    return False, f"unknown action: {action}"
