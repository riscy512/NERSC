#!/usr/bin/env python3
"""
Equipment decomposition parser driven by regex hints.

Workflow
--------
1. `hints.txt` describes how to parse endpoints:
     assetType : sample string : tokenized descriptor
2. Each descriptor is converted into a regex with named groups
3. Every label line contains "Origin <-> Destination"; both endpoints
   are parsed with the hint patterns
4. Successful matches populate two lookup structures:
     cluster['rack'][rack]['asset_type'][asset]['position'][pos] = pos
     cluster["asset_type"][asset]["rack"][rack]['position'][pos] = pos
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


class autoDict(dict):
    """Hash-of-hashes helper (Perl nostalgia)."""

    def __missing__(self, key):
        value = self[key] = type(self)()
        return value
    
cluster=autoDict()

# Read switch descriptions file and store in cluster dictionary
switch_file = Path("switchDescriptions.txt")
if switch_file.exists():
    with switch_file.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Parse colon-delimited format: model:Name:description:ports:uplinks(optional)
            fields = line.split(':')
            if len(fields) >= 4:
                switchModel = fields[0].strip()
                cluster["switchDefs"][switchModel]["name"] = fields[1].strip()
                cluster["switchDefs"][switchModel]["description"] = fields[2].strip()
                cluster["switchDefs"][switchModel]["ports"] = fields[3].strip()
                # Only set uplinks if it exists and is not empty
                if len(fields) > 4 and fields[4].strip():
                    cluster["switchDefs"][switchModel]["uplinks"] = fields[4].strip()
else:
    print(f"Warning: {switch_file} not found")

rackList = [ "rack1", "rack2", "rack3" ]

for rack in rackList:
    rack_file = Path(f"{rack}.csv")
    if rack_file.exists():
        # Read the file and merge "Cable Lengths" line with next line
        lines = []
        with rack_file.open() as f:
            file_lines = f.readlines()
            i = 0
            while i < len(file_lines):
                line = file_lines[i].rstrip('\n\r')
                # Check if line contains "Cable Lengths" followed by commas
                if 'Cable Lengths' in line:
                    # Merge with next line if it exists
                    if i + 1 < len(file_lines):
                        next_line = file_lines[i + 1].rstrip('\n\r')
                        # Parse both lines as CSV rows to merge properly
                        first_row = next(csv.reader([line]))
                        second_row = next(csv.reader([next_line]))
                        # Find where "Cable Lengths" is in first row
                        cable_idx = None
                        for idx, cell in enumerate(first_row):
                            if 'Cable Lengths' in cell:
                                cable_idx = idx
                                break
                        # Merge: keep first row up to and including "Cable Lengths", 
                        # then append second row starting from its second column (skip empty first)
                        if cable_idx is not None:
                            merged_row = first_row[:cable_idx + 1] + second_row[1:]  # Skip first empty col of second row
                            lines.append(','.join(merged_row))
                        else:
                            # Fallback: just concatenate
                            lines.append(line + ',' + next_line)
                        i += 2  # Skip both lines
                        continue
                lines.append(line)
                i += 1
        
        # Parse CSV: skip first line (rack name), skip second line (header)
        reader = csv.reader(lines)
        all_rows = list(reader)
        
        # Skip first two lines (rack name + header)
        if len(all_rows) < 2:
            print(f"{rack}: Not enough rows")
            continue
        
        data_rows = all_rows[2:]  # Skip first two lines (rack name + header)
        
        # Define column indices manually (you can adjust these as needed)
        # Column 0: Position (OU/U number)
        # Column 1: Front Mounted
        # Column 2: Rear Mounted
        # Column 3: Order Number
        # Column 4: PS 1
        # Column 5: PS 2
        # Column 6: Card Installs
        # Column 7: IB Route
        # Column 8: IB Length
        # Column 9: CAT6 Route
        # Column 10: CAT6 Length
        # Column 11: 25GbE SFP28 Route
        # Column 12: 25GbE SFP28 Length
        # Column 13: 100GbE MPO Route
        # Column 14: 100GbE MPO Length
        # Column 15: QSFP112 Route
        # Column 16: QSFP112 Length
        
        # Pattern to match OU# at start of first column
        ou_pattern = re.compile(r'^O?U(\d+)$', re.IGNORECASE)
        
        # Find the maximum OU number to start descending from
        max_ou = 0
        for row in data_rows:
            if row and row[0].strip() and ou_pattern.match(row[0].strip()):
                ou_num = int(ou_pattern.match(row[0].strip()).group(1))
                max_ou = max(max_ou, ou_num)
        
        if max_ou == 0:
            print(f"{rack}: No OU lines found")
            continue
        
        # Process OU lines: merge continuation lines until we find expected OU number
        processed_ou = []
        expected_ou = max_ou
        current_ou_row = None
        current_ou_num = None
        
        for row in data_rows:
            if not row or not row[0].strip():
                # Empty row - merge to current OU if we're collecting
                if current_ou_row is not None and expected_ou > 0:
                    # Merge cells: append non-empty cells to current OU row
                    for col_idx in range(max(len(current_ou_row), len(row))):
                        if col_idx >= len(current_ou_row):
                            current_ou_row.append('')
                        if col_idx < len(row) and row[col_idx].strip():
                            if current_ou_row[col_idx].strip():
                                current_ou_row[col_idx] += ' ' + row[col_idx].strip()
                            else:
                                current_ou_row[col_idx] = row[col_idx].strip()
                continue
            
            match = ou_pattern.match(row[0].strip())
            if match:
                found_ou = int(match.group(1))
                
                # If we have a previous OU being collected, save it
                if current_ou_row is not None:
                    processed_ou.append((current_ou_num, current_ou_row))
                
                # Start collecting this OU
                current_ou_num = found_ou
                current_ou_row = row.copy()
                
                # Check if this is the expected OU
                if found_ou == expected_ou:
                    # Found expected - move to next expected
                    expected_ou -= 1
                elif found_ou < expected_ou:
                    # Found a lower number - adjust expected
                    expected_ou = found_ou - 1
            else:
                # Not an OU line - if we're expecting an OU number > 0, merge to current
                if current_ou_row is not None and expected_ou > 0:
                    # Merge this row's cells to current OU row
                    for col_idx in range(max(len(current_ou_row), len(row))):
                        if col_idx >= len(current_ou_row):
                            current_ou_row.append('')
                        if col_idx < len(row) and row[col_idx].strip():
                            if current_ou_row[col_idx].strip():
                                current_ou_row[col_idx] += ' ' + row[col_idx].strip()
                            else:
                                current_ou_row[col_idx] = row[col_idx].strip()
        
        # Don't forget the last OU
        if current_ou_row is not None:
            processed_ou.append((current_ou_num, current_ou_row))
        
        # Process OU rows in descending order, access columns manually
        processed_ou.sort(reverse=True, key=lambda x: x[0])
        for ou_num, row in processed_ou:
            # Access columns by index manually
            # You can define your own column access here
            position = row[0] if len(row) > 0 else ''
            front_mounted = row[1] if len(row) > 1 else ''
            rear_mounted = row[2] if len(row) > 2 else ''
            slotName = ""
            if "blank" not in front_mounted and front_mounted != "Geist SwitchAir duct":
                slotName = front_mounted
            elif rear_mounted:
                slotName = rear_mounted
#            register_equipment(cluster, slotName, rack, ou_num)
            if (slotName):
                cluster["asset_type"][slotName]["rack"][rack]["position"][ou_num] = ou_num
                cluster["rack"][rack]["position"][ou_num]["asset"]=slotName

                modelNumber = slotName.split(" ")[0]
                if modelNumber:
                    cluster["asset_type"][slotName]["modelNumber"] = modelNumber
                    cluster["modelNumber"][modelNumber]["rack"][rack]["position"][ou_num] = ou_num
                    cluster["rack"][rack]["position"][ou_num]["modelNumber"] = modelNumber  
                    if modelNumber in cluster["switchDefs"]:
                        cluster["switches"][modelNumber]["rack"][rack]["position"][ou_num] = ou_num
                        cluster["rack"][rack]["switches"][modelNumber]["position"][ou_num] = ou_num



                else:
                    cluster["asset_type"][slotName]["modelNumber"] = "unknown"
                

                print("slotName: ", slotName, "MODEL NUMBER: ", modelNumber)
                # Get all words after the first word
                words = slotName.split()
                function = ' '.join(words[1:]) if len(words) > 1 else ''
                if function:
                    cluster["asset_type"][slotName]["function"] = function
                    cluster["function"][function]["rack"][rack]["position"][ou_num] = ou_num
                    cluster["rack"][rack]["position"][ou_num]["function"] = function


            order_number = row[3] if len(row) > 3 else ''
            ps1 = row[4] if len(row) > 4 else ''
            ps2 = row[5] if len(row) > 5 else ''
            card_installs = row[6] if len(row) > 6 else ''
            ib_route = row[7] if len(row) > 7 else ''
            ib_length = row[8] if len(row) > 8 else ''
            cat6_route = row[9] if len(row) > 9 else ''
            cat6_length = row[10] if len(row) > 10 else ''
            sfp28_route = row[11] if len(row) > 11 else ''
            sfp28_length = row[12] if len(row) > 12 else ''
            mpo_route = row[13] if len(row) > 13 else ''
            mpo_length = row[14] if len(row) > 14 else ''
            qsfp112_route = row[15] if len(row) > 15 else ''
            qsfp112_length = row[16] if len(row) > 16 else ''
            
            # Example usage
            print(f"{rack}: OU{ou_num} - slotName: {slotName}\tFront: {front_mounted}\tBack: {rear_mounted}")
#            if ib_route:
#                print(f"  IB Route: {ib_route[:60]}...")
    else:
        print(f"Warning: {rack_file} not found")

# Parse links.csv - Windows newlines are record separators, Unix newlines within records need rejoining
links_file = Path("links.csv")
if links_file.exists():
    with links_file.open('rb') as f:  # Read in binary to preserve line endings
        content = f.read().decode('utf-8')
    
    # Split on Windows newlines (\r\n) to get actual records
    records = content.split('\r\n')
    
    # First line is the header
    if not records:
        print(f"Warning: {links_file} is empty")
    else:
        # Parse header - remove Unix newlines and split by comma
        header_line = records[0].replace('\n', '')
        headers = [h.strip() for h in header_line.split(',')]
        
        # Find column indices
        # Source: first Row, Rack, Node, and Card (if exists, might be "Sled" or "Interface")
        src_row_idx = headers.index('Row') if 'Row' in headers else None
        src_rack_idx = None
        src_node_idx = None
        card_idx = None
        
        # Find first occurrence of each (source columns)
        for idx, h in enumerate(headers):
            if h == 'Rack' and src_rack_idx is None:
                src_rack_idx = idx
            elif h == 'Node' and src_node_idx is None:
                src_node_idx = idx
            elif h in ['Card', 'Sled'] and card_idx is None:
                card_idx = idx
        
        # Destination: second Row, Rack, Switch, Port
        dest_row_idx = None
        dest_rack_idx = None
        switch_idx = None
        port_idx = None
        
        # Find second occurrence (destination columns)
        found_first_rack = False
        for idx, h in enumerate(headers):
            if h == 'Row' and idx != src_row_idx:
                dest_row_idx = idx
            elif h == 'Rack' and idx != src_rack_idx:
                dest_rack_idx = idx
            elif h == 'Switch':
                switch_idx = idx
            elif h == 'Port':
                port_idx = idx
        
        # Process data records (skip header)
        for record in records[1:]:
            # Remove Unix newlines within the record
            record = record.replace('\n', '').strip()
            if not record:
                continue
            
            # Parse CSV record
            reader = csv.reader([record])
            try:
                row = next(reader)
                
                # Extract source endpoint
                src_row = row[src_row_idx] if src_row_idx is not None and src_row_idx < len(row) else ''
                src_rack = row[src_rack_idx] if src_rack_idx is not None and src_rack_idx < len(row) else ''
                src_node = row[src_node_idx] if src_node_idx is not None and src_node_idx < len(row) else ''
                card = row[card_idx] if card_idx is not None and card_idx < len(row) else ''
                
                # Extract destination endpoint
                dest_row = row[dest_row_idx] if dest_row_idx is not None and dest_row_idx < len(row) else ''
                dest_rack = row[dest_rack_idx] if dest_rack_idx is not None and dest_rack_idx < len(row) else ''
                switch = row[switch_idx] if switch_idx is not None and switch_idx < len(row) else ''
                port = row[port_idx] if port_idx is not None and port_idx < len(row) else ''
                
                # Store in cluster structure
                if src_row and src_rack and src_node:
                    cluster["ethConnections"]["byRow"][src_row]["rack"][src_rack]["node"][src_node]["destRow"] = dest_row
                    cluster["ethConnections"]["byRow"][src_row]["rack"][src_rack]["node"][src_node]["switch"] = switch
                    cluster["ethConnections"]["byRow"][src_row]["rack"][src_rack]["node"][src_node]["port"] = port
                    # Store card if populated
                    if card:
                        cluster["ethConnections"]["byRow"][src_row]["rack"][src_rack]["node"][src_node]["card"] = card
                
            except Exception as e:
                print(f"Error parsing record: {e}")
                continue
else:
    print(f"Warning: {links_file} not found")
     
print ("\n\n\n\n\n",cluster["ethConnections"],"\n\n\n\n\n")
