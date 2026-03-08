# omniaHosts

Generates an **`/etc/hosts`-compliant** file from a CSV inventory of node IPs. Each row is a host; columns are interfaces/networks. The script enumerates the different networks each node has and emits one line per IP with the correct hostname (and aliases where applicable).

## What it does

- **Reads** `ips.csv` from the script directory (one row per node, columns = networks/interfaces).
- **Maps** each IP to a network section and an interface suffix (e.g. `eth1`, `ib0`, `idrac`).
- **Builds** per-interface hostnames: primary hostname from the first Cluster Admin column; others as `node-<suffix>` (e.g. `node-eth1`, `node-ib0`, `node-idrac`).
- **Outputs** lines in standard `/etc/hosts` format: `IP<TAB>hostname [alias1 alias2 ...]`, grouped by network with comment headers.

## Networks (sections)

The script recognizes these networks (defined in `NETWORKS`):

| Section | Examples |
|--------|----------|
| Cluster Admin | Primary hostname; #2→`eth1`, #3→`eth2`, #4→`eth3` |
| iDracrac`, `idrac2` |
| InfiniBand Public | `ibpub` |
| InfiniBand Private | `ib0`, `ib1`, `ib2`, `ib3` |
| Switch Management | `swmgt`, `swmgt1` |
| PowerScale Admin | `psadm`, `psadm2`, … `psadm4` |
| PowerScale Storage | `psstg`, `psstg2`, … `psstg4` |
| Side Door | `sdr` |

The **primary** hostname (from the first Cluster Admin column) also gets **xName** and **Notes** as aliases on that line so the node name and alternate names resolve to the same IP.

## CSV requirements

- **NodeName** column is required.
- Optional: **xName**, **Notes** (used as aliases for the primary hostname).
- Other columns are treated as IP columns unless listed in `NON_IP_COLUMNS` (e.g. NodePurpose, Rack Number, uPos). Column headers must match the names in `NETWORKS` for correct section/suffix mapping.

## Usage

```bash
# Print /etc/hosts output to stdout
python3 omniaHosts.py

# Write to a file (default: hosts in script directory)
python3 omniaHosts.py -o

# Write to a specific path
python3 omniaHosts.py -o /path/to/h
```

## Behavior

- **IPv4 only**: Only values matching a simple four-octet IPv4 pattern are used; others are skipped.
- **IP reuse check**: If the same IP appears for a different host or interface, the script prints warnings and exits with code 5.
- **First row wins**: If an IP appears multiple times (e.g. same IP in different columns), the first occurrence determines the hostname and section.

## Output format

- Comment lines describe the file and each section (e.g. `# --- InfiniBand Private ---`).
- Each data line: `IP<TAB>hostname` or `IP<TAB>hostname<TAB>alias1<TAB>alias2` for the primary hostname.
- Lines are sorted by IP within each section.

The result can be appended or merged into `/etc/hosts` (or used as a standalone hosts file) for name resolution of cluster nodes on all enumerated networks.
