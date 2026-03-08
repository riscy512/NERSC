#!/usr/bin/env python3
"""
Generate an /etc/hosts-compliant file from eas/ips.csv.

Each row is a host; columns are interfaces/networks. Each IP gets a
per-interface hostname (e.g. node-eth1, node-ib0, node-idrac). The first
Cluster Admin column is the node's primary hostname (NodeName) with xName
and Notes as aliases. InfiniBand is split into Public and Private sections.
See NETWORKS for (section, header, interface_suffix) mapping.
"""

import csv
import re
import sys
from pathlib import Path

class autoDict(dict):
    """Hash-of-hashes helper (Perl nostalgia)."""

    def __missing__(self, key):
        value = self[key] = type(self)()
        return value
    
cluster=autoDict()

# IPv4 pattern (simple: four octets)
IPv4_RE = re.compile(r"^\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s*$")

# Columns we never treat as IPs
NON_IP_COLUMNS = {
    "NodeName",
    "NodePurpose",
    "Node Instance",
    "xName",
    "Rack Number",
    "uPos",
    "Notes",
}

# Network definitions: (section_label, [(CSV column header, interface_suffix), ...]).
# interface_suffix: None = node's primary hostname (Cluster Admin first only); else e.g. "eth1", "ib0".
# Per-IP hostname = node_name if suffix is None else f"{node_name}-{suffix}".
# Order of (header, suffix) defines section order and #1, #2, etc. within a network.
NETWORKS = [
    # Cluster Admin: first = node hostname; #2→eth1, #3→eth2, #4→eth3
    ("Cluster Admin", [
        ("Cluster Admin Network", None),
        ("Cluster Admin Network #2", "eth1"),
        ("Cluster Admin Network #3", "eth2"),
        ("Cluster Admin Network #4", "eth3"),
    ]),
    # iDrac: first = idrac
    ("iDrac", [
        ("iDrac Network (iDrac)", "idrac"),
        ("iDrac Network (Local)", "idrac2"),
    ]),
    # InfiniBand: Public and Private sections; Private #1→ib0, #2→ib1, #3→ib2, #4→ib3
    ("InfiniBand Public", [
        ("InfiniBand (Public)", "ibpub"),
    ]),
    ("InfiniBand Private", [
        ("InfiniBand ib0 (Private)", "ib0"),
        ("InfiniBand ib0 #2(Private)", "ib1"),
        ("InfiniBand ib1 (Private)", "ib2"),
        ("InfiniBand ib1 #2(Private)", "ib3"),
    ]),
    # Switch Management: first = swmgt, second = swmgt1
    ("Switch Management", [
        ("Switch Management Network", "swmgt"),
        ("Switch Management Network #2", "swmgt1"),
    ]),
    # PowerScale Admin: first = psadm, #2→psadm2, #3→psadm3, #4→psadm4
    ("PowerScale Admin", [
        ("PowerScale Admin Network #1", "psadm"),
        ("PowerScale Admin Network #2", "psadm2"),
        ("PowerScale Admin Network #3", "psadm3"),
        ("PowerScale Admin Network #4", "psadm4"),
    ]),
    # PowerScale Storage: first = psstg, #2→psstg2, #3→psstg3, #4→psstg4
    ("PowerScale Storage", [
        ("PowerScale Storage Network #1", "psstg"),
        ("PowerScale Storage Network #2", "psstg2"),
        ("PowerScale Storage Network #3", "psstg3"),
        ("PowerScale Storage Network #4", "psstg4"),
    ]),
    # Side Door: first = sdr
    ("Side Door", [
        ("Side Door Network", "sdr"),
    ]),
]


def _header_to_info_map():
    """Map CSV column header -> (section_label, interface_suffix). Unlisted columns -> ('Other', None)."""
    out = {}
    for label, pairs in NETWORKS:
        for h, suffix in pairs:
            out[h] = (label, suffix)
    return out


def is_valid_ip(val):
    if not val or not isinstance(val, str):
        return None
    val = val.strip()
    if not val:
        return None
    m = IPv4_RE.match(val)
    if not m:
        return None
    # basic octet check
    try:
        parts = [int(x) for x in m.group(1).split(".")]
        if all(0 <= p <= 255 for p in parts):
            return m.group(1).strip()
    except ValueError:
        pass
    return None


def main():
    script_dir = Path(__file__).resolve().parent
    csv_path = script_dir / "ips.csv"
    if not csv_path.exists():
        print("ips.csv not found", file=sys.stderr)
        sys.exit(1)

    # IP -> {node_name, names, network, suffix}; one host per IP (first row wins)
    ip_to_data = {}
    header_to_info = _header_to_info_map()
    ip_reuse_errors = []  # same IP seen for different host/interface

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        # map header name -> index (handle duplicates by taking first)
        col_index = {h.strip(): i for i, h in enumerate(header)}
        # strip trailing comma from last header if present
        for k in list(col_index):
            if k.endswith(","):
                col_index[k.rstrip(",")] = col_index.pop(k)

        idx_node = col_index.get("NodeName")
        idx_xname = col_index.get("xName")
        idx_notes = col_index.get("Notes")
        if idx_node is None:
            print("NodeName column not found", file=sys.stderr)
            sys.exit(1)

        # IP columns: (index, header_name) for network lookup
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
            # Notes: header may be "Notes" with data in same or next (trailing-comma) column
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
                    cluster["hosts"]["byNode"][node_name]["network"][network]["ip"]=ip
                    cluster["hosts"]["byNode"][node_name]["network"][network]["suffix"]=suffix
                    cluster["hosts"]["byNode"][node_name]["network"][network]["names"]=names
                    cluster["hosts"]["byHostname"][hostname]["node_name"]=node_name
                    cluster["hosts"]["byHostname"][hostname]["network"]=network
                    cluster["hosts"]["byHostname"][hostname]["ip"]=ip
                    cluster["hosts"]["byHostname"][hostname]["names"]=names
                    cluster["hosts"]["byIP"][ip]["node_name"]=node_name
                    cluster["hosts"]["byIP"][ip]["hostname"]=hostname
                    cluster["hosts"]["byIP"][ip]["network"]=network
                    cluster["hosts"]["byIP"][ip]["suffix"]=suffix
                    cluster["hosts"]["byIP"][ip]["names"]=names
#                    print ("A", cluster["hosts"]["byNode"][node_name])
#                    print ("B", cluster["hosts"]["byHostname"][hostname])
                else:
                    # Check for IP reuse: same IP assigned to a different host or interface
                    existing = ip_to_data[ip]
                    if (existing["node_name"] != node_name or
                            existing["network"] != network or
                            existing["suffix"] != suffix):
                        host_cur = node_name if (suffix is None or suffix == "") else f"{node_name}-{suffix}"
                        host_ex = existing["node_name"] if (existing["suffix"] is None or existing["suffix"] == "") else f"{existing['node_name']}-{existing['suffix']}"
                        ip_reuse_errors.append({
                            "ip": ip,
                            "first_host": host_ex,
                            "first_names": existing["names"],
                            "first_network": existing["network"],
                            "also_host": host_cur,
                            "also_names": names,
                            "also_network": network,
                        })

    if ip_reuse_errors:
        print("WARNING: IP address re-use detected (same IP, different host/interface).", file=sys.stderr)
        for err in ip_reuse_errors:
            print(f"  Conflicting IP: {err['ip']}", file=sys.stderr)
            print(f"    first: {err['first_host']} ({err['first_network']})  names: {', '.join(err['first_names'])}", file=sys.stderr)
            print(f"    also:  {err['also_host']} ({err['also_network']})  names: {', '.join(err['also_names'])}", file=sys.stderr)
        print(f"Total: {len(ip_reuse_errors)} re-use(s).", file=sys.stderr)
        sys.exit(5)

    # Emit /etc/hosts format: sections by network; each IP gets interface-specific hostname
    network_order = [label for label, _ in NETWORKS] + ["Other"]
    ip_sort_key = lambda x: tuple(map(int, x.split(".")))

    lines = [
        "# Generated from ips.csv - per-interface hostnames",
        "# Primary (Cluster Admin first) = node hostname + xName/Notes aliases; others = node-interface (e.g. node-eth1, node-ib0).",
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
                # Primary IP: add xName and Notes as aliases so node name and xname resolve here
                aliases = [n for n in names[1:] if n]
                parts = [ip, hostname] + aliases
            else:
                hostname = f"{node_name}-{suffix}"
                parts = [ip, hostname]
            lines.append("\t".join(parts))
        lines.append("")

    out = "\n".join(lines).rstrip() + "\n"

    if len(sys.argv) > 1 and sys.argv[1] == "-o":
        out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else script_dir / "hosts"
        out_path.write_text(out, encoding="utf-8")
        print(f"Wrote {len(ip_to_data)} entries to {out_path}", file=sys.stderr)
    else:
        print(out, end="")


if __name__ == "__main__":
    main()
