variable "ovh_endpoint" {
  description = "OVH API endpoint, for example ovh-eu."
  type        = string
  default     = "ovh-eu"
}

variable "current_sauvage_server_name" {
  description = "Existing KS-7/Sauvage service name used to discover the target datacenter."
  type        = string
}

variable "enable_order" {
  description = "Set true only when ready to order the 3 KS-5 servers."
  type        = bool
  default     = false
}

variable "confirm_ovh_order" {
  description = "Manual destructive/cost gate. Must be exactly order-3-ks5 when enable_order=true."
  type        = string
  default     = ""
  sensitive   = true
}

variable "ks5_count" {
  description = "Number of KS-5 servers to order."
  type        = number
  default     = 3

  validation {
    condition     = var.ks5_count == 3
    error_message = "This rollout is intentionally designed for exactly 3 KS-5 control-plane nodes."
  }
}

variable "hostname_prefix" {
  description = "Display-name prefix for ordered KS-5 servers."
  type        = string
  default     = "ks5-cp"
}

variable "ks5_plan_code" {
  description = "OVH catalog plan code for KS-5-A. Discover with scripts/ovh_install.py catalog and do not use HDD/SATA variants."
  type        = string
  default     = "CHANGE_ME_KS5A_PLAN_CODE"
}

variable "duration" {
  description = "OVH duration code."
  type        = string
  default     = "P1M"
}

variable "pricing_mode" {
  description = "OVH pricing mode."
  type        = string
  default     = "default"
}

variable "target_datacenter_override" {
  description = "Optional explicit OVH datacenter. Empty means reuse Sauvage datacenter."
  type        = string
  default     = ""
}

variable "ubuntu_2404_template" {
  description = "OVH install template to use after delivery. Keep overridable because OVH template names vary by region/catalog."
  type        = string
  default     = "ubuntu2404-server_64"
}

variable "required_offer_name" {
  description = "Guardrail: the only accepted Kimsufi offer name."
  type        = string
  default     = "KS-5-A"
}

variable "required_cpu_model" {
  description = "Guardrail: expected CPU for KS-5-A."
  type        = string
  default     = "Intel Xeon E-2274G"
}

variable "required_storage_profile" {
  description = "Guardrail: only pick SSD NVMe Soft RAID storage, never HDD/SATA variants."
  type        = string
  default     = "2x SSD NVMe 960GB Enterprise Class Soft RAID"
}

variable "plan_options" {
  description = "Optional OVH plan options for RAM/bandwidth/disks. Do not add HDD/SATA storage options for KS-5-A."
  type = list(object({
    plan_code    = string
    duration     = optional(string)
    pricing_mode = optional(string)
    quantity     = optional(number)
  }))
  default = []
}

variable "ks5_storage_option_plan_code" {
  description = "Optional explicit storage option plan code. Use only if OVH requires a storage option; it must be the SSD NVMe Soft RAID option."
  type        = string
  default     = ""
}
