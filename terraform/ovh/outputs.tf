output "sauvage_datacenter" {
  description = "Datacenter detected from the existing Sauvage dedicated server."
  value       = var.target_datacenter_override != "" ? null : data.ovh_dedicated_server.sauvage[0].datacenter
}

output "target_datacenter" {
  description = "Datacenter requested for KS-5 servers."
  value       = local.target_datacenter
}

output "ks5_servers" {
  description = "Delivered KS-5 server metadata. Empty unless enable_order=true."
  value = [
    for server in ovh_dedicated_server.ks5 : {
      service_name      = server.service_name
      name              = server.name
      display_name      = server.display_name
      ip                = server.ip
      datacenter        = server.datacenter
      availability_zone = server.availability_zone
      state             = server.state
    }
  ]
}

output "required_ks5a_profile" {
  description = "Server profile this module is locked to."
  value = {
    offer                    = var.required_offer_name
    cpu                      = var.required_cpu_model
    storage                  = var.required_storage_profile
    storage_option_plan_code = var.ks5_storage_option_plan_code
    os                       = "Ubuntu Server 24.04 LTS"
  }
}
