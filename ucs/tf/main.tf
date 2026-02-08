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
# Data Model Merge Process - Merge YAML Files into HCL Format
# Loads all YAML config files from the config directory
#
# Server profiles use active/inactive model:
# - profiles/*.ezi.yaml         = domain profile (always included)
# - profiles/active/*.ezi.yaml  = server profiles TO MANAGE
# - profiles/inactive/*.ezi.yaml = server profiles REMOVED (not loaded)
#_________________________________________________________________________________________
data "utils_yaml_merge" "model" {
  input = concat(
    [for file in fileset("${path.module}/../config", "*.ezi.yaml") : file("${path.module}/../config/${file}")],
    [for file in fileset("${path.module}/../config", "policies/*.ezi.yaml") : file("${path.module}/../config/${file}")],
    [for file in fileset("${path.module}/../config/templates", "*.ezi.yaml") : file("${path.module}/../config/templates/${file}")],
    [for file in fileset("${path.module}/../config/profiles", "*.ezi.yaml") : file("${path.module}/../config/profiles/${file}")],
    [for file in fileset("${path.module}/../config/profiles/active", "*.ezi.yaml") : file("${path.module}/../config/profiles/active/${file}")]
  )
  merge_list_items = false
}

#_________________________________________________________________________________________
#
# Intersight:Organizations
# GUI Location: Settings > Organizations/Resource Groups
#_________________________________________________________________________________________
module "organizations" {
  source          = "terraform-cisco-modules/organizations/intersight"
  version         = "4.2.11-20250512205939815"
  for_each        = { for i in ["map"] : i => i if length([setsubtract(keys(local.model), local.non_orgs)]) > 0 }
  global_settings = local.global_settings
  model           = { for k, v in local.model : k => v if length(regexall("^global_settings|intersight$", k)) == 0 }
}

#_________________________________________________________________________________________
#
# Intersight:Pools
# GUI Location: Infrastructure Service > Configure > Pools
#_________________________________________________________________________________________
module "pools" {
  source  = "terraform-cisco-modules/pools/intersight"
  version = "4.2.11-20250512205939815"
  for_each = {
    for i in ["map"] : i => i if length(flatten([for org in setsubtract(keys(local.model), local.non_orgs) : [
      for e in keys(lookup(local.model[org], "pools", {})) : e]])) > 0 || length(flatten([
      for org in setsubtract(keys(local.model), local.non_orgs) : [
        for e in lookup(lookup(local.model[org], "policies", {}), "server_pool_qualification", []) : e
      ]])) > 0 || length(
      flatten([for org in setsubtract(keys(local.model), local.non_orgs) : [for e in lookup(lookup(local.model[org], "profiles", {}), "server", []) : [
        for d in e["targets"] : lookup(d, "reservations", [])
      ]]])
    ) > 0
  }
  global_settings = local.global_settings
  model           = { for k, v in local.model : k => v if length(regexall("^global_settings|intersight$", k)) == 0 }
  orgs            = module.organizations["map"].organizations
}

#_________________________________________________________________________________________
#
# Intersight:Policies
# GUI Location: Infrastructure Service > Configure > Policies
#_________________________________________________________________________________________
module "policies" {
  source  = "terraform-cisco-modules/policies/intersight"
  version = "4.2.11-20250512205939815"
  for_each = {
    for i in ["map"] : i => i if length(flatten([for org in keys(local.model) : [
      for e in setsubtract(keys(lookup(local.model[org], "policies", {})), ["server_pool_qualification"]
      ) : local.model[org].policies[e] if length(lookup(lookup(local.model[org], "policies", {}), e, [])) > 0]])
    ) > 0
  }
  global_settings    = local.global_settings
  model              = { for k, v in local.model : k => v if length(regexall("^global_settings|intersight$", k)) == 0 }
  orgs               = module.organizations["map"].organizations
  policies_sensitive = local.policies_sensitive
  pools              = module.pools
}

#_________________________________________________________________________________________
#
# Intersight: UCS Chassis, Domain, and Server Profiles/Templates
# GUI Location: Infrastructure Service > Configure > Profiles
# GUI Location: Infrastructure Service > Configure > Templates
#_________________________________________________________________________________________
module "profiles" {
  source  = "terraform-cisco-modules/profiles/intersight"
  version = "4.2.11-20250512205939815"
  for_each = {
    for i in ["map"] : i => i if length(flatten([for org in keys(local.model) : [for e in ["profiles", "templates"] : [
      for d in ["chassis", "domain", "server"] : lookup(lookup(local.model[org], e, {}), d, [])]]]
    )) > 0
  }
  global_settings = local.global_settings
  model           = { for k, v in local.model : k => v if length(regexall("^global_settings|intersight$", k)) == 0 }
  orgs            = module.organizations["map"].organizations
  policies        = module.policies
  pools           = module.pools
}
