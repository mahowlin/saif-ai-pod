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

#______________________________________________
#
# Intersight Provider Settings
#______________________________________________

variable "intersight_api_key_id" {
  description = "Intersight API Key."
  sensitive   = true
  type        = string
  validation {
    condition     = length(regexall("^[\\da-f]{24}/[\\da-f]{24}/[\\da-f]{24}$", var.intersight_api_key_id)) > 0
    error_message = "Intersight API Key Should match the following: ```^[\\da-f]{24}/[\\da-f]{24}/[\\da-f]{24}$```"
  }
}

variable "intersight_secret_key" {
  default     = "blah.txt"
  description = "Intersight Secret Key or path to secret key file."
  sensitive   = true
  type        = string
}

#______________________________________________
#
# Local User Password for UCS Server Access
# Set via TF_VAR_local_user_password environment variable
#______________________________________________
variable "local_user_password" {
  description = "Password for the local admin user on UCS servers. Set via TF_VAR_local_user_password."
  sensitive   = true
  type        = string
  default     = ""
}

#______________________________________________
#
# vMedia Password for HTTP Basic Auth
# Set via TF_VAR_vmedia_password environment variable
#______________________________________________
variable "vmedia_password" {
  description = "Password for vMedia HTTP basic auth. Set via TF_VAR_vmedia_password."
  sensitive   = true
  type        = string
  default     = ""
}
