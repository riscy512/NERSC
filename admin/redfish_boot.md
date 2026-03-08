# redfish_boot.py

Redfish boot configuration: **show/set permanent boot order** and **show/set next boot** (one-time or continuous override). Uses the same iDrac/cluster pattern as `redfish_power.py` (nodes with iDrac network in the cluster).

---

## Requirements

- iDrac IP per node (e.g. from `cluster["hosts"]["byNode"][node_name]["network"]["iDrac"]["ip"]`).
- Credentials: `REDFISH_USER`, `REDFISH_PASSWORD` env or `user`/`password` kwargs.
- `verify_ssl=False` typical for self-signed iDRAC certs.

---

## API overview

### Full boot config

- **`get_boot_config(idrac_ip, ...) -> (boot_dict, error)`**  
  GETs the ComputerSystem and returns the **Boot** object (BootOrder, BootSourceOverrideTarget, BootSourceOverrideEnabled, BootSourceOverrideMode, etc.).

### Permanent boot order

- **`get_permanent_boot_order(idrac_ip, ...) -> (order_list, error)`**  
  Returns the persistent (BIOS) boot order as a list of IDs, e.g. `["NIC.Slot.5-1-1", "HardDisk.List.1-1"]`.

- **`set_permanent_boot_order(idrac_ip, order, ...) -> (success, error)`**  
  PATCHes the persistent boot order. `order` is a list of boot source IDs. Some BMCs require a Settings resource; this PATCHes the main Systems resource.

### Next boot (override)

- **`get_next_boot(idrac_ip, ...) -> (dict, error)`**  
  Returns current override: **BootSourceOverrideTarget**, **BootSourceOverrideEnabled**, **BootSourceOverrideMode**, **UefiTargetBootSourceOverride**.

- **`set_next_boot(idrac_ip, target, enabled=..., mode=..., uefi_target=..., ...) -> (success, error)`**  
  Sets next boot. `target`: e.g. `BOOT_TARGET_PXE`, `BOOT_TARGET_HDD`, `BOOT_TARGET_NONE`. `enabled`: `BOOT_OVERRIDE_ONCE`, `BOOT_OVERRIDE_CONTINUOUS`, or `BOOT_OVERRIDE_DISABLED`. Optional `mode`: `BOOT_MODE_UEFI` / `BOOT_MODE_LEGACY`.

- **`clear_next_boot(idrac_ip, ...) -> (success, error)`**  
  Clears override (use normal boot order).

### Boot options (vendor-specific)

- **`get_boot_options(idrac_ip, ...) -> (list_of_options, error)`**  
  GETs the BootOptions collection (all boot sources the BIOS knows about). May not be supported on all BMCs.

### By node name (cluster)

- **`run_for_node(cluster, node_name, action, ...) -> (success, error, result)`**  
  Resolves iDrac IP from cluster and runs an action:
  - **action** `'show_permanent'` — result = boot order list.
  - **action** `'set_permanent'` — requires **order** = `[...]`.
  - **action** `'show_next'` — result = next-boot dict.
  - **action** `'set_next'` — requires **target** = `...`; optional **enabled**, **mode**.
  - **action** `'clear_next'` — clear override.
  - **action** `'show_options'` — result = BootOptions list (if supported).

---

## Constants

**BootSourceOverrideTarget:**  
`BOOT_TARGET_NONE`, `BOOT_TARGET_PXE`, `BOOT_TARGET_CD`, `BOOT_TARGET_HDD`, `BOOT_TARGET_USB`, `BOOT_TARGET_FLOPPY`, `BOOT_TARGET_BIOS_SETUP`, `BOOT_TARGET_UTILITIES`, `BOOT_TARGET_UEFI_TARGET`, `BOOT_TARGET_SDCARD`, `BOOT_TARGET_UEFI_HTTP`

**BootSourceOverrideEnabled:**  
`BOOT_OVERRIDE_DISABLED`, `BOOT_OVERRIDE_ONCE`, `BOOT_OVERRIDE_CONTINUOUS`

**BootSourceOverrideMode:**  
`BOOT_MODE_UEFI`, `BOOT_MODE_LEGACY`

---

## Usage examples

```python
from redfish_boot import (
    get_permanent_boot_order,
    set_permanent_boot_order,
    get_next_boot,
    set_next_boot,
    clear_next_boot,
    BOOT_TARGET_PXE,
    BOOT_OVERRIDE_ONCE,
    run_for_node,
)

idrac_ip = "10.41.2.116"

# Show permanent boot order
order, err = get_permanent_boot_order(idrac_ip, verify_ssl=False)
if not err:
    print("Permanent order:", order)

# Set permanent order (if BMC allows PATCH on BootOrder)
# ok, err = set_permanent_boot_order(idrac_ip, ["NIC.Slot.5-1-1", "HardDisk.List.1-1"], verify_ssl=False)

# Show next boot override
next_d, err = get_next_boot(idrac_ip, verify_ssl=False)
if not err:
    print("Next boot:", next_d)

# Set next boot to PXE once
ok, err = set_next_boot(idrac_ip, BOOT_TARGET_PXE, enabled=BOOT_OVERRIDE_ONCE, verify_ssl=False)

# Clear next boot
ok, err = clear_next_boot(idrac_ip, verify_ssl=False)

# By node name (cluster from omniaHosts)
ok, err, result = run_for_node(cluster, "cech-mgt2", "show_permanent", verify_ssl=False)
ok, err, result = run_for_node(cluster, "cech-mgt2", "set_next", target=BOOT_TARGET_PXE, verify_ssl=False)
```
