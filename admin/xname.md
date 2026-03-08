# xname.py

Parse and validate **NERSC-10 xNames**: the Cray CSM–style hierarchical naming used for Dell hardware in the NERSC-10 environment. The module turns xName strings into structured data for indexing, lookups, and integration with tools like omniaHosts.

---

## Purpose

- **Parse** an xName string (e.g. `x1102c0s27b0n0`, `x1102c0s27b0n0a0`) into a dictionary with component type, numeric IDs, and optional parent node xName.
- **Validate** that a string matches a known xName pattern.
- **Resolve** the canonical node xName for a given string (e.g. from a GPU xName get the parent node xName).

All logic is based on the documented naming standard (rack, node, DC power shelf, PDU, Ethernet/IB switches, GPU/CPU/DIMM, and node interfaces).

---

## Supported component types and patterns

| Component            | Pattern                         | Example              |
|---------------------|----------------------------------|----------------------|
| Rack                | `x<rack_id>`                     | `x1000`              |
| Node                | `x<rack>c<chassis>s<slot>b<blade>n<node>` (slot = uPos) | `x1102c0s27b0n0`     |
| DC power shelf      | `x<rack>c<chassis>t<shelf_id>`   | `x1103c0t1`          |
| Rack PDU            | `x<rack>m<pdu_id>`               | `x1306m0`            |
| Ethernet switch     | `x<rack>c<chassis>w<switch_id>`  | `x1423c0w24`         |
| InfiniBand leaf     | `x<rack>c<chassis>t<leaf_id>`    | `x1423c0t0`          |
| InfiniBand spine    | `x<rack>c<chassis>s<spine_id>`    | `x1423c0s0`          |
| GPU                 | `<node_xName>a<accel_id>`        | `x1102c0s27b0n0a0`   |
| CPU                 | `<node_xName>p<proc_id>`         | `x1102c0s27b0n0p1`   |
| DIMM                | `<node_xName>d<dimm_id>`         | `x1102c0s27b0n0d0`   |
| Ethernet interface  | `<node_xName>i<iface_id>`        | `x1102c0s27b0n0i0`   |
| InfiniBand interface| `<node_xName>h<iface_id>`        | `x1102c0s27b0n0h0`   |

**Note:** The pattern `x<rack>c<chassis>t<id>` is used for both DC power shelf and InfiniBand leaf; the parser returns a single type (`t_component`) because the string alone does not distinguish them.

---

## API

### `parse_xname(xname: str) -> dict | None`

Parses an xName string into a structured dict. Returns `None` if the string does not match any known pattern.

**Returned dict keys:**

| Key             | Description |
|-----------------|-------------|
| `component_type`| One of the `COMPONENT_*` constants (see below). |
| `rack_id`       | Rack number, or `None` if not applicable. |
| `chassis_id`    | Chassis number, or `None`. |
| `slot_id`       | Slot number (or spine id for IB spine), or `None`. |
| `uPos`          | **uPosition** — slot = vertical position of the node in the rack (nodes and node subcomponents only); `None` for rack/PDU/switch/etc. |
| `blade_id`      | Blade number (nodes only), or `None`. |
| `node_id`       | Node number (nodes only), or `None`. |
| `sub_type`      | For node subcomponents: `'a'`, `'p'`, `'d'`, `'i'`, or `'h'`; else `None`. |
| `sub_id`        | Subcomponent index (e.g. GPU 0, PDU id), or `None`. |
| `node_xname`    | For nodes: the full node xName. For node subcomponents: the parent node xName. Else `None`. |
| `raw`           | Original input string (stripped). |

Parsing order is “most specific first”: e.g. node+subcomponent is matched before node-only, and node (full `xRcCsSbBnN`) before IB spine (`xRcCsS`).

### `validate_xname(xname: str) -> bool`

Returns `True` if the string is a valid xName (i.e. `parse_xname(xname)` is not `None`).

### `get_node_xname(xname: str) -> str | None`

Returns the canonical node xName (`x<rack>c<chassis>s<slot>b<blade>n<node>`) when the input is a node or a node subcomponent (GPU, CPU, DIMM, eth/IB interface). For a node xName, returns that same string. For racks, PDUs, switches, etc., returns `None`.

### `get_uPos(xname: str) -> int | None`

Returns the **uPosition** (slot in rack) for the given xName. For nodes and node subcomponents, returns the slot value as an int. For rack/PDU/switch/etc., or invalid xNames, returns `None`. All parsed dicts from `parse_xname()` include an `uPos` key so callers can always request uPos via `parsed["uPos"]` or `get_uPos(xname)`.

---

## Component type constants

Use these for indexing or filtering by component type:

- `COMPONENT_RACK`
- `COMPONENT_NODE`
- `COMPONENT_DC_POWER`
- `COMPONENT_PDU`
- `COMPONENT_ETH_SWITCH`
- `COMPONENT_IB_LEAF`
- `COMPONENT_IB_SPINE`
- `COMPONENT_GPU`
- `COMPONENT_CPU`
- `COMPONENT_DIMM`
- `COMPONENT_ETH_INTERFACE`
- `COMPONENT_IB_INTERFACE`
- `COMPONENT_T` — used for the shared `xRcCtT` pattern (dc_power / ib_leaf)

---

## Usage example

```python
from xname import parse_xname, validate_xname, get_node_xname, get_uPos, COMPONENT_NODE

# Parse a node
p = parse_xname("x1102c0s27b0n0")
# p["component_type"] == "node", p["rack_id"] == 1102, p["uPos"] == 27, p["node_xname"] == "x1102c0s27b0n0"

# Parse a GPU on that node (uPos inherited from slot)
p = parse_xname("x1102c0s27b0n0a0")
# p["component_type"] == "gpu", p["uPos"] == 27, p["node_xname"] == "x1102c0s27b0n0"

# Request uPos via API (nodes and node subcomponents only)
get_uPos("x1102c0s27b0n0")    # -> 27
get_uPos("x1102c0s27b0n0a0") # -> 27
get_uPos("x1306m0")           # -> None (PDU)

# Get parent node from any node or node-subcomponent xName
get_node_xname("x1102c0s27b0n0a0")  # -> "x1102c0s27b0n0"
get_node_xname("x1306m0")           # -> None (PDU)

# Validate
validate_xname("x7000c0s1b0n0")    # -> True
validate_xname("nid0001")          # -> False
```

---

## Integration

**omniaHosts** uses `parse_xname` and `get_node_xname` when loading `ips.csv`: it stores `xname_parsed` per node and builds indexes by `node_xname` and `rack_id` so you can look up by node or rack. All dictionary keys and stored node/host names in that script use short names only (no domain); xname.py does not deal with domains.
