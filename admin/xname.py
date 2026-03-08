"""
Parse and validate NERSC-10 xNames (Cray CSM–style naming for Dell hardware).

Component types and patterns (see naming standard doc):
  - rack:        x<rack_id>
  - node:        x<rack>c<chassis>s<slot>b<blade>n<node>  (slot = uPosition in rack, exposed as uPos)
  - dc_power:    x<rack>c<chassis>t<shelf_id>
  - pdu:         x<rack>m<pdu_id>
  - eth_switch:  x<rack>c<chassis>w<switch_id>
  - ib_leaf:     x<rack>c<chassis>t<leaf_id>   (same pattern as dc_power; context distinguishes)
  - ib_spine:    x<rack>c<chassis>s<spine_id>  (no b/n; spine has 3 segments after x)
  - gpu:         <node_xName>a<accel_id>
  - cpu:         <node_xName>p<proc_id>
  - dimm:        <node_xName>d<dimm_id>
  - eth_interface: <node_xName>i<iface_id>
  - ib_interface:  <node_xName>h<iface_id>
"""

import re
from typing import Any

# Component type constants for indexing and lookups
COMPONENT_RACK = "rack"
COMPONENT_NODE = "node"
COMPONENT_DC_POWER = "dc_power"
COMPONENT_PDU = "pdu"
COMPONENT_ETH_SWITCH = "eth_switch"
COMPONENT_IB_LEAF = "ib_leaf"
COMPONENT_IB_SPINE = "ib_spine"
COMPONENT_GPU = "gpu"
COMPONENT_CPU = "cpu"
COMPONENT_DIMM = "dimm"
COMPONENT_ETH_INTERFACE = "eth_interface"
COMPONENT_IB_INTERFACE = "ib_interface"
# t_component: pattern xRcCtT matches both dc_power and ib_leaf; we don't distinguish from string alone
COMPONENT_T = "t_component"

# Subcomponent suffix -> component type (for node subcomponents)
SUB_SUFFIX_TO_TYPE = {
    "a": COMPONENT_GPU,
    "p": COMPONENT_CPU,
    "d": COMPONENT_DIMM,
    "i": COMPONENT_ETH_INTERFACE,
    "h": COMPONENT_IB_INTERFACE,
}

# Patterns (most specific first so node+sub beats node-only, node beats spine)
_NODE_FULL = re.compile(
    r"^x(\d+)c(\d+)s(\d+)b(\d+)n(\d+)(a|p|d|i|h)(\d+)$", re.IGNORECASE
)
_NODE_ONLY = re.compile(r"^x(\d+)c(\d+)s(\d+)b(\d+)n(\d+)$", re.IGNORECASE)
_PDU = re.compile(r"^x(\d+)m(\d+)$", re.IGNORECASE)
_ETH_SWITCH = re.compile(r"^x(\d+)c(\d+)w(\d+)$", re.IGNORECASE)
_T_COMPONENT = re.compile(r"^x(\d+)c(\d+)t(\d+)$", re.IGNORECASE)  # dc_power or ib_leaf
_IB_SPINE = re.compile(r"^x(\d+)c(\d+)s(\d+)$", re.IGNORECASE)  # no b,n
_RACK = re.compile(r"^x(\d+)$", re.IGNORECASE)


def parse_xname(xname: str) -> dict[str, Any] | None:
    """
    Parse an xName string into a structured dict for indexing and lookups.

    Returns a dict with:
      - component_type: one of the COMPONENT_* constants
      - rack_id, chassis_id, slot_id, blade_id, node_id: int | None (as applicable)
      - uPos: int | None — slot position = uPosition of the node in the rack (nodes and node
        subcomponents only; None for rack/PDU/switch/etc.)
      - sub_type: for node subcomponents, one of 'a'|'p'|'d'|'i'|'h'
      - sub_id: int | None for subcomponent index
      - node_xname: for subcomponents, the parent node xName (e.g. x1102c0s27b0n0)
      - raw: original string

    Returns None if the string does not match any known xName pattern.
    """
    if not xname or not isinstance(xname, str):
        return None
    s = xname.strip()
    if not s:
        return None

    # Node + subcomponent (a,p,d,i,h)
    m = _NODE_FULL.match(s)
    if m:
        r, c, slot, b, n, sub_letter, sub_id = m.groups()
        slot_int = int(slot)
        node_xname = f"x{r}c{c}s{slot}b{b}n{n}"
        return {
            "component_type": SUB_SUFFIX_TO_TYPE.get(sub_letter.lower(), "subcomponent"),
            "rack_id": int(r),
            "chassis_id": int(c),
            "slot_id": slot_int,
            "blade_id": int(b),
            "node_id": int(n),
            "uPos": slot_int,
            "sub_type": sub_letter.lower(),
            "sub_id": int(sub_id),
            "node_xname": node_xname,
            "raw": s,
        }

    # Node only
    m = _NODE_ONLY.match(s)
    if m:
        r, c, slot, b, n = m.groups()
        slot_int = int(slot)
        return {
            "component_type": COMPONENT_NODE,
            "rack_id": int(r),
            "chassis_id": int(c),
            "slot_id": slot_int,
            "blade_id": int(b),
            "node_id": int(n),
            "uPos": slot_int,
            "sub_type": None,
            "sub_id": None,
            "node_xname": s,
            "raw": s,
        }

    # PDU
    m = _PDU.match(s)
    if m:
        r, pdu_id = m.groups()
        return {
            "component_type": COMPONENT_PDU,
            "rack_id": int(r),
            "chassis_id": None,
            "slot_id": None,
            "blade_id": None,
            "node_id": None,
            "uPos": None,
            "sub_type": None,
            "sub_id": int(pdu_id),
            "node_xname": None,
            "raw": s,
        }

    # Ethernet switch
    m = _ETH_SWITCH.match(s)
    if m:
        r, c, w = m.groups()
        return {
            "component_type": COMPONENT_ETH_SWITCH,
            "rack_id": int(r),
            "chassis_id": int(c),
            "slot_id": None,
            "blade_id": None,
            "node_id": None,
            "uPos": None,
            "sub_type": "w",
            "sub_id": int(w),
            "node_xname": None,
            "raw": s,
        }

    # t_component (dc_power or ib_leaf; indistinguishable from string)
    m = _T_COMPONENT.match(s)
    if m:
        r, c, t_id = m.groups()
        return {
            "component_type": COMPONENT_T,
            "rack_id": int(r),
            "chassis_id": int(c),
            "slot_id": None,
            "blade_id": None,
            "node_id": None,
            "uPos": None,
            "sub_type": "t",
            "sub_id": int(t_id),
            "node_xname": None,
            "raw": s,
        }

    # IB spine (x R c C s S with nothing after)
    m = _IB_SPINE.match(s)
    if m:
        r, c, spine_id = m.groups()
        return {
            "component_type": COMPONENT_IB_SPINE,
            "rack_id": int(r),
            "chassis_id": int(c),
            "slot_id": int(spine_id),
            "blade_id": None,
            "node_id": None,
            "uPos": None,
            "sub_type": "s",
            "sub_id": int(spine_id),
            "node_xname": None,
            "raw": s,
        }

    # Rack only
    m = _RACK.match(s)
    if m:
        r = m.group(1)
        return {
            "component_type": COMPONENT_RACK,
            "rack_id": int(r),
            "chassis_id": None,
            "slot_id": None,
            "blade_id": None,
            "node_id": None,
            "uPos": None,
            "sub_type": None,
            "sub_id": None,
            "node_xname": None,
            "raw": s,
        }

    return None


def validate_xname(xname: str) -> bool:
    """Return True if the string is a valid xName matching a known pattern."""
    return parse_xname(xname) is not None


def get_node_xname(xname: str) -> str | None:
    """
    For any xName, return the canonical node xName (xRcCsSbBnN) if applicable.
    For a node xName, returns itself. For a node subcomponent (a,p,d,i,h), returns the parent node.
    For rack/PDU/switch/etc., returns None.
    """
    parsed = parse_xname(xname)
    if not parsed:
        return None
    return parsed.get("node_xname")


def get_uPos(xname: str) -> int | None:
    """
    Return the uPosition (slot in rack) for the given xName.
    For nodes and node subcomponents, returns the slot value (int).
    For rack/PDU/switch/etc., returns None. Invalid xNames also return None.
    """
    parsed = parse_xname(xname)
    if not parsed:
        return None
    return parsed.get("uPos")
