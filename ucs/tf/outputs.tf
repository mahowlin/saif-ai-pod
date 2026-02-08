# Copyright (c) 2026 Cisco and/or its affiliates.
#
# This software is licensed to you under the terms of the Cisco Sample
# Code License, Version 1.1 (the "License"). You may obtain a copy of the
# License at
#
#                https://developer.cisco.com/docs/licenses
#
# All use of the material herein must be in accordance with the terms of
# the License. All rights not expressly granted by the License are
# reserved. Unless required by applicable law or agreed to separately in
# writing, software distributed under the License is distributed on an "AS
# IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
# or implied.

#_________________________________________________________________________________________
#
# Outputs - MAC Addresses for OpenShift Deployment
#_________________________________________________________________________________________

# Output MAC addresses assigned to server profiles
output "server_mac_addresses" {
  description = "MAC addresses for each server (keyed by serial number)"
  value = {
    for profile_name, profile in try(module.profiles["map"].profiles.server, {}) :
    # Map profile name to serial and MAC
    # Note: Path may need adjustment based on Easy-IMM module structure
    profile_name => {
      serial      = try(profile.targets[0].serial_number, "unknown")
      mac_address = try(profile.lan_connectivity[0].vnics[0].mac_address, "not-assigned")
    }
  }
}
