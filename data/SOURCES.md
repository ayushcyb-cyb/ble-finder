# Data sources & licenses

All reference data bundled here is from permissively-licensed, publicly
redistributable sources. Refresh it with `python3 update_data.py`.

## `company_ids.json` and `service_uuids.json`

- **Source:** [NordicSemiconductor/bluetooth-numbers-database](https://github.com/NordicSemiconductor/bluetooth-numbers-database)
  (`v1/company_ids.json`, `v1/service_uuids.json`), derived from the Bluetooth
  SIG Assigned Numbers.
- **License:** BSD-3-Clause.

  > Copyright (c) 2019 - 2020, Nordic Semiconductor ASA. All rights reserved.
  > Redistribution and use in source and binary forms, with or without
  > modification, are permitted provided that the conditions of the
  > BSD-3-Clause license are met.

## `known_devices.json` (not in git)

Created at runtime when you use **Save as known** in the app. It holds *your*
device labels (name + address/fingerprint) and is git-ignored — it's your
data, not a shipped dataset.

## A note on adding more data

Only add datasets whose license allows redistribution, and record each one
here with its URL and license. For data without a clear redistribution
license, fetch it at runtime instead of committing it. Do not scrape search
engines or sites that forbid it — the useful data lives in named, licensed
databases like the one above.
