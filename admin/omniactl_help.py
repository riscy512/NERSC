"""
Help text and capability descriptions for omniactl.

Use: omniactl help  or  from omniactl_help import get_help; print(get_help())
"""

from __future__ import annotations

CAPABILITIES = """
omniactl — Cluster control CLI (wwctl-style)

omniactl is the main entry point for cluster inventory and control. It loads node
data from ips.csv (see --config) and provides subcommands for generating host files,
genders files, querying nodes, and controlling power, identify (beacon) LED, and boot via Redfish (iDrac).

All node names and cluster lookups use short names only (no domain). Nodes must
have the iDrac network defined in ips.csv for power and boot subcommands to work.

Node name / xName alias: you can pass either nodeName (e.g. nid0001) or xName
(e.g. x7000c0s1b0n0) for power, boot, and node show; xName is resolved to the
canonical nodeName before the command runs.

GLOBAL OPTIONS
  -c, --config PATH    Path to ips.csv (default: script_dir/ips.csv)
  -v, --verbose        Verbose output
  -d, --debug          Debug output
  --no-verify-ssl      Disable SSL verification for Redfish (typical for iDRAC)
  -U, --redfish-user   Redfish/BMC user (overrides OMNIA_REDFISH_USER and REDFISH_USER env)
  -P, --redfish-password  Redfish/BMC password (overrides OMNIA_REDFISH_PASSWORD and REDFISH_PASSWORD env)
  -h, --help           Show help (any level: omniactl -h, omniactl power -h)

Redfish credentials (power/boot): precedence is -U/-P, then omniactl OMNIA_REDFISH_USER/OMNIA_REDFISH_PASSWORD
(for testing until e.g. Vault), then REDFISH_USER/REDFISH_PASSWORD env. Each node is acted on via its
iDrac IP from the cluster (byNode[node]["network"]["iDrac"]["ip"]).

SUBCOMMANDS

  hosts
    Emit /etc/hosts-compliant output. Each line: IP, nodeName.domain, xName.domain,
    nodeName, xName, Notes (primary) or hostname.domain, hostname (per-interface).
    -o, --output PATH  Write to file (default: stdout)

  genders
    Emit pdsh genders file. One line per node: nodeName NodePurpose x{rack_id}.
    Node names and attributes are without domain.
    -o, --output PATH  Write to file (default: stdout)

  node list [PATTERN]
    List all node names from the cluster. Optional PATTERN filters by substring.
  node show NODE
    Show one node (NODE may be nodeName or xName). NodeName, NodePurpose, xName,
    rack, uPos, and network table (hostname -> IP per network).

  power ACTION [NODE ...]
    Power control via Redfish (iDrac). NODE(s) may be nodeName or xName. Requires at least one.
    Output is one line per node in the form "nodeName: <status or result>" on
    stdout. Pipe to dshbak (e.g. omniactl power status n1 n2 ... | dshbak);
    dshbak reads stdin and rolls up nodes by common output (e.g. one block for
    nodes "On", another for nodes "Off").
    ACTION: on, off, status, reset, cycle, graceful_shutdown, graceful_restart,
            force_off, nmi

  identify ACTION [NODE ...]
    Chassis identify/beacon LED (Redfish Chassis IndicatorLED). NODE(s) may be nodeName or xName.
    ACTION: on (Lit), off (Off), blink (Blinking), status. Requires at least one node.

  boot show-next [NODE ...]
    Show next boot override (BootSourceOverrideTarget, Enabled, Mode) per node.
    NODE(s) may be nodeName or xName.
  boot show-permanent [NODE ...]
    Show persistent (BIOS) boot order per node.
  boot set-next --target TARGET [NODE ...]
    Set next boot device. TARGET: e.g. Pxe, Hdd, None, Cd, UefiTarget.
  boot clear-next [NODE ...]
    Clear next boot override (use normal boot order).
  boot show-options [NODE ...]
    Show BootOptions collection (vendor-specific; may not be supported).
    Default NODE list: all nodes in cluster.

CONFIGURATION
  Cluster data is read from ips.csv. Required columns: NodeName. Optional: xName,
  Notes, NodePurpose. Other columns are treated as IP columns; headers should
  match NETWORKS in omniaHosts for correct section mapping. Redfish credentials:
  set REDFISH_USER and REDFISH_PASSWORD in the environment.

BACKWARD COMPATIBILITY
  The legacy script omniaHosts still accepts -H (hosts), -o (hosts path), -g (genders)
  and calls the omniaHosts module. Prefer: omniactl hosts, omniactl genders.
"""


def get_help() -> str:
    """Return the full capability/help string for omniactl."""
    return CAPABILITIES.strip()


def print_help() -> None:
    """Print the capability/help string to stdout."""
    print(get_help())
