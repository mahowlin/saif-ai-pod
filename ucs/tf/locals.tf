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

locals {
  global_settings = {
    tags = lookup(local.model.global_settings, "tags", [
      {
        key   = "Module"
        value = "saif-sno"
      },
      {
        key   = "Version"
        value = "1.0.0"
      }
    ])
  }
  intersight_fqdn = lookup(local.model.global_settings, "intersight_fqdn", "intersight.com")
  model           = yamldecode(data.utils_yaml_merge.model.output)
  non_orgs        = ["global_settings", "intersight"]

  #__________________________________________________________________
  #
  # Sensitive Variables - Minimal set for saif-sno
  #__________________________________________________________________
  policies_sensitive = {
    certificate_management = { certificate = {}, private_key = {} }
    drive_security = {
      current_security_key_passphrase   = {}
      new_security_key_passphrase       = {}
      password                          = {}
      server_public_root_ca_certificate = {}
    }
    firmware          = { cco_password = {}, cco_user = {} }
    ipmi_over_lan     = { encryption_key = {} }
    iscsi_boot        = { password = {} }
    ldap              = { password = {} }
    local_user        = { password = var.local_user_password != "" ? { 1 = var.local_user_password } : {} }
    mac_sec           = { fallback_key_chain = {}, primary_key_chain = {} }
    persistent_memory = { passphrase = {} }
    snmp = {
      access_community_string = {}
      auth_password           = {}
      privacy_password        = {}
      trap_community_string   = {}
    }
    switch_control = { aes_primary_key = {} }
    virtual_media  = { password = var.vmedia_password != "" ? { 1 = var.vmedia_password } : {} }
  }
}
