terraform {
  required_version = ">= 1.6.0"

  required_providers {
    ovh = {
      source  = "ovh/ovh"
      version = "~> 2.13"
    }
  }
}

provider "ovh" {
  endpoint = var.ovh_endpoint
}
