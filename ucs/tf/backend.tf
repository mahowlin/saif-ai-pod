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

# HTTP Backend for Terraform State
#
# This enables persistent state storage across workflow runs.
# State is stored on the runner VM's terraform-backend service.
#
# URL configuration via environment variables (set in workflow):
# - TF_HTTP_ADDRESS: Base URL for state operations
# - TF_HTTP_LOCK_ADDRESS: URL for state locking
# - TF_HTTP_UNLOCK_ADDRESS: URL for state unlocking
# - TF_HTTP_USERNAME: Basic auth username
# - TF_HTTP_PASSWORD: Basic auth password

terraform {
  backend "http" {
    # All URLs set via TF_HTTP_* environment variables in workflow
    # This allows different environments without code changes
  }
}
