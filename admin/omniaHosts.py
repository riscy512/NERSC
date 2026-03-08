"""
Cluster inventory module: load ips.csv into a cluster index and emit hosts/genders output.

Used by omniactl and optionally by a legacy omniaHosts script.
All keys and node_name/hostname values are WITHOUT domain; use nodeNameWithDomain for FQDN.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Optional

from xname import parse_xname


class IPReuseError(RuntimeError):
    """Raised by load_cluster when the same IP is used for different hosts/interfaces."""
    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__(f"IP address re-use: {len(errors)} conflict(s)")


class autoDict(dict):
    def __missing__(self, key):
        value = self[key] = type(self)()
        return value


# Domain for FQDN-style host entries
DOMAIN = "cech.nersc.gov"
IPv4_RE = re.compile(r"^\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s*$")

NON_IP_COLUMNS = {
    "NodeName", "NodePurpose", "Node Instance", "xName", "Rack Number", "uPos", "Notes",
}

NETWORKS = [
    ("Cluster Admin", [
        ("Cluster Admin Network", None),
        ("Cluster Admin Network #2", "eth1"),
        ("Cluster Admin Network #3", "eth2"),
        ("Cluster Admin Network #4", "eth3"),
    ]),
    ("iDrac", [
        ("iDrac Network (iDrac)", "idrac"),
        ("iDrac Network (Local)", "idrac2"),
    ]),
    ("InfiniBand Public", [("InfiniBand (Public)", "ibpub")]),
    ("InfiniBand Private", [
        ("InfiniBand ib0 (Private)", "ib0"),
        ("InfiniBand ib0 #2(Private)", "ib1"),
        ("InfiniBand ib1 (Private)", "ib2"),
        ("InfiniBand ib1 #2(Private)", "ib3"),
    ]),
    ("Switch Management", [
        ("Switch Management Network", "swmgt"),
        ("Switch Management Network #2", "swmgt1"),
    ]),
    ("PowerScale Admin", [
        ("PowerScale Admin Network #1", "psadm"),
        ("PowerScale Admin Network #2", "psadm2"),
        ("PowerScale Admin Network #3", "psadm3"),
        ("PowerScale Admin Network #4", "psadm4"),
    ]),
    ("PowerScale Storage", [
        ("PowerScale Storage Network #1", "psstg"),
        ("PowerScale Storage Network #2", "psstg2"),
        ("PowerScale Storage Network #3", "psstg3"),
        ("PowerScale Storage Network #4", "psstg4"),
    ]),
    ("Side Door", [("Side Door Network", "sdr")]),
]


def _header_to_info_map() -> dict[str, tuple[str, Optional[str]]]:
    out = {}
    for label, pairs in NETWORKS:
        for h, suffix in pairs:
            out[h] = (label, suffix)
    return out


def is_valid_ip(val: Any) -> Optional[str]:
    if not val or not isinstance(val, str):
        return None
    s = val.strip()
    if not s:
        return None
    m = IPv4_RE.match(s)
    if not m:
        return None
    try:
        parts = [int(x) for x in m.group(1).split(".")]
        if all(0 <= p <= 255 for p in parts):
            return m.group(1).strip()
    except ValueError:
        pass
    return None


def load_cluster(csv_path: Optional[Path] = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Load ips.csv and build the cluster index and ip_to_data map.
    Returns (cluster, ip_to_data). Raises IPReuseError on IP reuse; raises FileNotFoundError
    or exits logic on missing NodeName column (caller should check csv_path exists first).
    """
    if csv_path is None:
        csv_path = Path(__file__).resolve().parent / "ips.csv"
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"ips.csv not found: {csv_path}")

    cluster = autoDict()
    ip_to_data = {}
    header_to_info = _header_to_info_map()
    ip_reuse_errors: list[dict[str, Any]] = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        col_index = {h.strip(): i for i, h in enumerate(header)}
        for k in list(col_index):
            if k.endswith(","):
                col_index[k.rstrip(",")] = col_index.pop(k)

        idx_node = col_index.get("NodeName")
        idx_xname = col_index.get("xName")
        idx_notes = col_index.get("Notes")
        idx_node_purpose = col_index.get("NodePurpose")
        if idx_node is None:
            raise ValueError("NodeName column not found")

        ip_cols = []
        for i, h in enumerate(header):
            name = h.strip().rstrip(",")
            if name not in NON_IP_COLUMNS and i not in (idx_node, idx_xname, idx_notes):
                if idx_notes is not None and i == idx_notes:
                    continue
                ip_cols.append((i, name))

        for row in reader:
            if len(row) <= idx_node:
                continue
            node_name = (row[idx_node] or "").strip()
            if not node_name:
                continue

            names = [node_name]
            if idx_xname is not None and idx_xname < len(row):
                xname = (row[idx_xname] or "").strip()
                if xname and xname not in names:
                    names.append(xname)

            primary_xname = (row[idx_xname] or "").strip() if idx_xname is not None and idx_xname < len(row) else ""
            if not primary_xname:
                primary_xname = node_name
            node_purpose = ""
            if idx_node_purpose is not None and idx_node_purpose < len(row):
                node_purpose = (row[idx_node_purpose] or "").strip()
            cluster["hosts"]["byNode"][node_name]["NodePurpose"] = node_purpose or "unknown"
            cluster["hosts"]["byNode"][node_name]["nodeNameWithDomain"] = f"{node_name}.{DOMAIN}"

            xname_parsed = parse_xname(primary_xname)
            if xname_parsed:
                cluster["hosts"]["byNode"][node_name]["xname_parsed"] = xname_parsed
                node_xname = xname_parsed.get("node_xname")
                rack_id = xname_parsed.get("rack_id")
                if node_xname:
                    cluster["hosts"]["by_xname"][node_xname] = node_name
                if rack_id is not None:
                    cluster["racks"][rack_id][node_name] = True

            note = ""
            if idx_notes is not None and idx_notes < len(row):
                note = (row[idx_notes] or "").strip().rstrip(",")
            if not note and len(row) > 0:
                last = (row[-1] or "").strip().rstrip(",")
                if last and not is_valid_ip(last):
                    note = last
            if note and note not in names:
                names.append(note)

            for i, col_name in ip_cols:
                if i >= len(row):
                    continue
                ip = is_valid_ip(row[i])
                if not ip:
                    continue
                network, suffix = header_to_info.get(col_name, ("Other", None))
                if ip not in ip_to_data:
                    ip_to_data[ip] = {
                        "node_name": node_name,
                        "names": list(names),
                        "network": network,
                        "suffix": suffix,
                    }
                    hostname = node_name if (suffix is None or suffix == "") else f"{node_name}-{suffix}"
                    cluster["hosts"]["byNode"][node_name]["network"][network]["hostname"] = hostname
                    cluster["hosts"]["byNode"][node_name]["network"][network]["hostnameWithDomain"] = f"{hostname}.{DOMAIN}"
                    cluster["hosts"]["byNode"][node_name]["network"][network]["ip"] = ip
                    cluster["hosts"]["byNode"][node_name]["network"][network]["suffix"] = suffix
                    cluster["hosts"]["byNode"][node_name]["network"][network]["names"] = names
                    cluster["hosts"]["byHostname"][hostname]["node_name"] = node_name
                    cluster["hosts"]["byHostname"][hostname]["hostname"] = hostname
                    cluster["hosts"]["byHostname"][hostname]["hostnameWithDomain"] = f"{hostname}.{DOMAIN}"
                    cluster["hosts"]["byHostname"][hostname]["network"] = network
                    cluster["hosts"]["byHostname"][hostname]["ip"] = ip
                    cluster["hosts"]["byHostname"][hostname]["names"] = names
                    cluster["hosts"]["byIP"][ip]["node_name"] = node_name
                    cluster["hosts"]["byIP"][ip]["hostname"] = hostname
                    cluster["hosts"]["byIP"][ip]["network"] = network
                    cluster["hosts"]["byIP"][ip]["suffix"] = suffix
                    cluster["hosts"]["byIP"][ip]["names"] = names
                else:
                    existing = ip_to_data[ip]
                    if (existing["node_name"] != node_name or existing["network"] != network or existing["suffix"] != suffix):
                        host_cur = node_name if (suffix is None or suffix == "") else f"{node_name}-{suffix}"
                        host_ex = existing["node_name"] if (existing["suffix"] is None or existing["suffix"] == "") else f"{existing['node_name']}-{existing['suffix']}"
                        ip_reuse_errors.append({
                            "ip": ip, "first_host": host_ex, "first_names": existing["names"], "first_network": existing["network"],
                            "also_host": host_cur, "also_names": names, "also_network": network,
                        })

    if ip_reuse_errors:
        raise IPReuseError(ip_reuse_errors)

    return cluster, ip_to_data


def write_hosts(
    cluster: dict[str, Any],
    ip_to_data: dict[str, Any],
    path: Optional[Path] = None,
) -> str:
    """
    Build /etc/hosts-style output and return it. If path is set, also write to file.
    """
    network_order = [label for label, _ in NETWORKS] + ["Other"]
    ip_sort_key = lambda x: tuple(map(int, x.split(".")))

    lines = [
        "# Generated from ips.csv - per-interface hostnames",
        f"# Domain: {DOMAIN}",
        "# Primary line order: nodeName.domain, xName.domain, nodeName, xName, Notes.",
        "# Other lines: hostname.domain, hostname (e.g. node-eth1, node-ib0).",
        "#",
    ]
    for net_label in network_order:
        ips_in_net = [ip for ip, data in ip_to_data.items() if data["network"] == net_label]
        if not ips_in_net:
            continue
        lines.append(f"# --- {net_label} ---")
        lines.append("")
        for ip in sorted(ips_in_net, key=ip_sort_key):
            data = ip_to_data[ip]
            node_name = data["node_name"]
            names = data["names"]
            suffix = data["suffix"]
            if suffix is None or suffix == "":
                hostname = node_name
                node_xname = None
                node_data = cluster.get("hosts", {}).get("byNode", {}).get(node_name, {})
                xp = node_data.get("xname_parsed")
                if xp:
                    node_xname = xp.get("node_xname")
                parts = [ip, f"{hostname}.{DOMAIN}"]
                if node_xname:
                    parts.append(f"{node_xname}.{DOMAIN}")
                parts.append(hostname)
                if node_xname:
                    parts.append(node_xname)
                for n in names:
                    if n and n != node_name and n != (node_xname or ""):
                        parts.append(n)
                parts = [str(p) for p in parts]
            else:
                hostname = f"{node_name}-{suffix}"
                parts = [ip, f"{hostname}.{DOMAIN}", hostname]
            lines.append("\t".join(parts))
        lines.append("")

    out = "\n".join(lines).rstrip() + "\n"
    if path is not None:
        Path(path).write_text(out, encoding="utf-8")
    return out


def write_genders(cluster: dict[str, Any], filepath: Optional[Path] = None) -> str:
    """
    Build pdsh genders output (node names only, no domain). If filepath is set, write to file.
    """
    lines = []
    for node_name in sorted(cluster.get("hosts", {}).get("byNode", {})):
        node_data = cluster["hosts"]["byNode"][node_name]
        purpose = node_data.get("NodePurpose") or "unknown"
        attrs = [purpose]
        xname_parsed = node_data.get("xname_parsed")
        if xname_parsed and xname_parsed.get("rack_id") is not None:
            attrs.append(f"x{xname_parsed['rack_id']}")
        lines.append(f"{node_name} {' '.join(attrs)}\n")
    out = "".join(lines)
    if filepath is not None:
        Path(filepath).write_text(out, encoding="utf-8")
    return out
