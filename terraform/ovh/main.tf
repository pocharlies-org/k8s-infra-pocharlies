data "ovh_me" "account" {}

data "ovh_dedicated_server" "sauvage" {
  count        = var.target_datacenter_override == "" ? 1 : 0
  service_name = var.current_sauvage_server_name
}

locals {
  target_datacenter = var.target_datacenter_override != "" ? var.target_datacenter_override : data.ovh_dedicated_server.sauvage[0].datacenter
  storage_option = var.ks5_storage_option_plan_code == "" ? [] : [
    {
      plan_code    = var.ks5_storage_option_plan_code
      duration     = var.duration
      pricing_mode = var.pricing_mode
      quantity     = 1
    }
  ]
  effective_plan_options = concat(var.plan_options, local.storage_option)
}

resource "ovh_dedicated_server" "ks5" {
  count = var.enable_order ? var.ks5_count : 0

  ovh_subsidiary = data.ovh_me.account.ovh_subsidiary
  display_name   = format("%s-%d", var.hostname_prefix, count.index + 1)
  os             = var.ubuntu_2404_template
  range          = "eco"

  plan = [
    {
      plan_code    = var.ks5_plan_code
      duration     = var.duration
      pricing_mode = var.pricing_mode

      configuration = [
        {
          label = "dedicated_datacenter"
          value = local.target_datacenter
        },
        {
          label = "dedicated_os"
          value = "none_64.en"
        }
      ]
    }
  ]

  plan_option = local.effective_plan_options

  lifecycle {
    precondition {
      condition     = var.confirm_ovh_order == "order-3-ks5"
      error_message = "Ordering KS-5 servers costs money. Set confirm_ovh_order=order-3-ks5 explicitly."
    }

    precondition {
      condition     = var.ks5_plan_code != "CHANGE_ME_KS5A_PLAN_CODE"
      error_message = "Set ks5_plan_code from OVH catalog discovery for the KS-5-A SSD NVMe Soft RAID offer before enabling ordering."
    }

    precondition {
      condition     = lower(var.required_offer_name) == "ks-5-a"
      error_message = "This rollout is locked to KS-5-A only."
    }

    precondition {
      condition     = can(regex("(?i)nvme", var.required_storage_profile)) && can(regex("(?i)soft raid", var.required_storage_profile)) && !can(regex("(?i)hdd|sata", var.required_storage_profile))
      error_message = "Storage guardrail failed: only SSD NVMe Soft RAID is allowed; HDD/SATA variants are refused."
    }

    precondition {
      condition = alltrue([
        for option in local.effective_plan_options :
        !can(regex("(?i)hdd|sata", option.plan_code))
      ])
      error_message = "Refusing a plan option that looks like HDD/SATA storage. Use the included KS-5-A NVMe Soft RAID profile."
    }

    precondition {
      condition     = var.ks5_storage_option_plan_code == "" || can(regex("(?i)nvme", var.ks5_storage_option_plan_code))
      error_message = "Explicit storage option must be the SSD NVMe Soft RAID plan code."
    }
  }
}
