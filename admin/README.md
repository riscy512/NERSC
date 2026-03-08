# eas/admin — Cluster inventory and control

This directory contains **omniactl** (the main CLI), the **omniaHosts** module and legacy script, and supporting modules for xName parsing, Redfish power, and Redfish boot. Cluster data is read from **ips.csv** (one row per node; columns = networks/interfaces).

---

## omniactl

**omniactl** is the primary entry point for cluster control (wwctl-style). It loads node data from ips.csv and provides subcommands for hosts output, genders output, node queries, and Redfish power/boot control.

### Quick start

```bash
# Show detailed capabilities and usage
omniactl help

# Emit /etc/hosts to stdout
omniactl hosts

# Emit hosts to a file
omniactl hosts -o /path/to/hosts

# Emit pdsh genders file
omniactl genders
omniactl genders -o /path/to/genders

# List node names (optional filter)
omniactl node list
omniactl node list vast

# Show one node (NodePurpose, xName, rack, uPos, networks)
omniactl node show cech-mgt2

# Power control (requires iDrac in ips.csv; REDFISH_USER / REDFISH_PASSWORD)
omniactl power status cech-mgt2
omniactl power on cech-mgt2
omniactl power off cech-mgt2 nid0001

# Boot config: show/set next boot, show permanent order
omniactl boot show-next cech-mgt2
omniactl boot set-next --target Pxe cech-mgt2
omniactl boot clear-next cech-mgt2
```

### Global options

| Option | Description |
|--------|-------------|
| `-c`, `--config PATH` | Path to ips.csv (default: script directory) |
| `-v`, `--verbose` | Verbose output |
| `-d`, `--debug` | Debug output |
| `--no-verify-ssl` | Disable SSL verification for Redfish (typical for iDRAC) |
| `-h`, `--help` | Show help at any level (e.g. `omniactl power -h`) |

### Subcommands

| Subcommand | Description |
|------------|-------------|
| **help** | Show detailed capabilities and usage (from omniactl_help module) |
| **hosts** | Emit /etc/hosts output. `-o PATH` to write to file. |
| **genders** | Emit pdsh genders file (node names only, no domain). `-o PATH` to write. |
| **node list [PATTERN]** | List node names; optional substring filter. |
| **node show NODE** | Show one node: NodePurpose, xName, rack, uPos, network table. |
| **power ACTION [NODE ...]** | Power on/off/status/reset/cycle via Redfish. Output is `nodeName: <result>` on stdout; pipe to **dshbak** so it can roll up by common state (e.g. one block for nodes On, another for Off). Actions: `on`, `off`, `status`, `reset`, `cycle`, `graceful_shutdown`, `graceful_restart`, `force_off`, `nmi`. |
| **boot show-next [NODE ...]** | Show next boot override per node. |
| **boot show-permanent [NODE ...]** | Show persistent boot order per node. |
| **boot set-next -t TARGET [NODE ...]** | Set next boot device (e.g. Pxe, Hdd, None). |
| **boot clear-next [NODE ...]** | Clear next boot override. |
| **boot show-options [NODE ...]** | Show BootOptions (vendor-specific). |

### Node name / xName alias

For **power**, **boot**, and **node show**, you can pass either a **nodeName** (e.g. `nid0001`, `cech-mgt2`) or an **xName** (e.g. `x7000c0s1b0n0`). xName is resolved to the canonical nodeName before the command runs, so both forms are equivalent.

### Configuration

- **Cluster data:** ips.csv (see CSV requirements below). Use `--config` to point to another path.
- **Redfish:** Set `REDFISH_USER` and `REDFISH_PASSWORD` in the environment. Power and boot subcommands apply only to nodes that have an **iDrac** network defined in ips.csv.

---

## omniaHosts (legacy)

The **omniaHosts** script and **omniaHosts** module provide hosts and genders output. The script is kept for backward compatibility.

### Legacy script usage

```bash
# Print /etc/hosts to stdout
python3 omniaHosts -H

# Write hosts to file (default: ./hosts)
python3 omniaHosts -H -o
python3 omniaHosts -H -o /path/to/hosts

# Write genders (default: ./genders)
python3 omniaHosts -g
python3 omniaHosts -g /path/to/genders
```

Prefer **omniactl hosts** and **omniactl genders** for new use.

### What the module does

- **Reads** ips.csv (one row per node; columns = networks/interfaces).
- **Maps** each IP to a network section and interface suffix (e.g. eth1, ib0, idrac).
- **Builds** per-interface hostnames: primary from first Cluster Admin column; others as `node-<suffix>`.
- **Outputs** /etc/hosts format: `IP<TAB>hostname [alias1 alias2 ...]`, grouped by network. Primary line order: nodeName.domain, xName.domain, nodeName, xName, Notes.

### Networks (sections)

| Section | Examples |
|--------|----------|
| Cluster Admin | Primary hostname; #2→eth1, #3→eth2, #4→eth3 |
| iDrac | idrac, idrac2 |
| InfiniBand Public | ibpub |
| InfiniBand Private | ib0, ib1, ib2, ib3 |
| Switch Management | swmgt, swmgt1 |
| PowerScale Admin | psadm … psadm4 |
| PowerScale Storage | psstg … psstg4 |
| Side Door | sdr |

### CSV requirements

- **NodeName** column is required.
- Optional: **xName**, **Notes** (aliases for primary hostname), **NodePurpose** (used in genders).
- Other columns are treated as IP columns unless listed in NON_IP_COLUMNS. Column headers should match NETWORKS for correct section mapping.

### Behavior

- **IPv4 only:** Only four-octet IPv4 values are used.
- **IP reuse check:** Same IP for different host/interface causes warnings and exit code 5.
- **First row wins:** First occurrence of an IP determines hostname and section.

---

## Help module

**omniactl_help** provides the detailed capability text used by `omniactl help`:

```bash
omniactl help
```

Or from Python:

```python
from omniactl_help import get_help, print_help
print(get_help())
print_help()
```

---

## Other modules

| Module | Purpose |
|--------|---------|
| **xname** | Parse/validate NERSC-10 xNames; uPos, rack_id, node_xname. See xname.md. |
| **redfish_power** | Redfish power on/off/status/reset/cycle via iDrac. See redfish_power.md. |
| **redfish_boot** | Redfish boot: show/set permanent and next boot order. See redfish_boot.md. |
