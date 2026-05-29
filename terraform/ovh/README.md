# OVH / Kimsufi KS-5

This module is intentionally safe by default:

- It always discovers the current Sauvage datacenter.
- It orders nothing while `enable_order=false`.
- Ordering requires both `enable_order=true` and `confirm_ovh_order=order-3-ks5`.
- The rollout is locked to **KS-5-A** with **SSD NVMe Soft RAID**. Do not select
  HDD/SATA variants.

Required target profile:

- Offer: `KS-5-A`
- CPU: `Intel Xeon E-2274G`
- RAM: `32GB DDR4 ECC` included
- Storage: `2x SSD NVMe 960GB Enterprise Class Soft RAID` included

Credentials are read by the OVH provider from environment variables:

```bash
export OVH_ENDPOINT=ovh-eu
export OVH_APPLICATION_KEY=...
export OVH_APPLICATION_SECRET=...
export OVH_CONSUMER_KEY=...
```

Discovery:

```bash
tofu init
tofu plan -var-file=terraform.tfvars
```

Validate the current OVH catalog before ordering:

```bash
python3 ../../scripts/ovh_install.py catalog \
  --offer-name KS-5-A \
  --require "Intel Xeon E-2274G" \
  --require "SSD NVMe" \
  --require "Soft RAID" \
  --reject HDD \
  --reject SATA
```

Order gate:

```bash
tofu apply \
  -var-file=terraform.tfvars \
  -var enable_order=true \
  -var confirm_ovh_order=order-3-ks5
```

Ubuntu Server 24.04 LTS installation is handled after delivery by
`../../scripts/ovh_install.py`, because the exact OS template and RAID support
must be validated against each delivered server.
