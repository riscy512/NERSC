# redfish_power.py

Redfish-based power management for nodes that have an **iDrac network** defined in the cluster (e.g. from omniaHosts / ips.csv). Uses the DMTF Redfish API to power on/off, reset, or query status via the BMC (Dell iDRAC or other Redfish-compliant controllers).

---

## Requirements

- **iDrac IP per node**: The cluster must have `cluster["hosts"]["byNode"][node_name]["network"]["iDrac"]["ip"]` set (nodes without iDrac in ips.csv are not supported).
- **Credentials**: Redfish user/password via arguments or environment:
  - `REDFISH_USER`
  - `REDFISH_PASSWORD`
- **HTTPS**: Redfish uses HTTPS; iDRAC often uses self-signed certs, so `verify_ssl=False` is typical.

---

## API overview

### Resolving iDrac IP from cluster

- **`get_idrac_ip_for_node(cluster, node_name) -> str | None`**  
  Returns the iDrac (BMC) IP for the node, or `None` if the node has no iDrac network.

### Power status

- **`power_status(idrac_ip, ...) -> (PowerState | None, system_json | None)`**  
  GETs the ComputerSystem resource. `PowerState` is usually `'On'`, `'Off'`, `'PoweringOn'`, or `'PoweringOff'`.

### Power actions (by iDrac IP)

All take `idrac_ip` and optional `system_id`, `user`, `password`, `verify_ssl`. Return `(success: bool, error_message: str | None)`.

| Function | Redfish ResetType | Description |
|----------|-------------------|-------------|
| `power_on` | On | Power on |
| `power_off` | Off | Power off (soft) |
| `power_force_off` | ForceOff | Force off without graceful shutdown |
| `power_graceful_shutdown` | GracefulShutdown | Request OS graceful shutdown |
| `power_reset` | ForceRestart | Force restart |
| `power_cycle` | PowerCycle | Power cycle (off then on) |
| `power_graceful_restart` | GracefulRestart | Graceful restart |
| `power_nmi` | Nmi | Non-Maskable Interrupt |
| `reset(idrac_ip, reset_type, ...)` | (any) | Generic reset with any `ResetType` |

### ResetType constants

Use with `reset()` for other actions: `RESET_ON`, `RESET_OFF`, `RESET_FORCE_OFF`, `RESET_GRACEFUL_SHUTDOWN`, `RESET_GRACEFUL_RESTART`, `RESET_FORCE_RESTART`, `RESET_POWER_CYCLE`, `RESET_NMI`, `RESET_FORCE_ON`, `RESET_PUSH_POWER_BUTTON`, `RESET_SUSPEND`, `RESET_PAUSE`, `RESET_RESUME`.

### By node name (cluster lookup)

- **`run_for_node(cluster, node_name, action, ...) -> (success, error_or_state)`**  
  Resolves iDrac IP from the cluster and runs the given action.  
  **action**: `'on'`, `'off'`, `'force_off'`, `'status'`, `'reset'`, `'cycle'`, `'graceful_shutdown'`, `'graceful_restart'`, `'nmi'`.  
  For `'status'`, the second return is the power state string (e.g. `'On'`); for others it is an error message or `None`.

---

## Usage examples

```python
from redfish_power import (
    get_idrac_ip_for_node,
    power_status,
    power_on,
    power_off,
    power_reset,
    power_cycle,
    run_for_node,
)

# Cluster from omniaHosts (after loading ips.csv)
# cluster = ...

# By node name (uses cluster to get iDrac IP)
ok, err = run_for_node(cluster, "cech-mgt2", "status", verify_ssl=False)
# ok=True, err="On" or "Off" or "unknown"

ok, err = run_for_node(cluster, "cech-mgt2", "off", verify_ssl=False)
ok, err = run_for_node(cluster, "cech-mgt2", "on", verify_ssl=False)

# By iDrac IP directly
ip = get_idrac_ip_for_node(cluster, "cech-mgt2")
state, sys = power_status(ip, verify_ssl=False)
success, err = power_cycle(ip, verify_ssl=False)
```

---

## System ID

Dell iDRAC typically exposes the system as `System.Embedded.1`. The module discovers the system ID from `GET /redfish/v1/Systems` and falls back to `DEFAULT_SYSTEM_ID` (`System.Embedded.1`) if needed. You can pass `system_id=...` to any function to skip discovery.
