# BCD_APPLICATION_TYPE_PROBE

## Purpose

`demo bcd probe-application-types` checks which `bcdedit /create /application <type>` values are accepted in an **offline** BCD store.

This is a capability probe, not a boot installer.

## Why offline store

Probe creates and mutates only:

- `C:\LVHLab\bcd_probe\bcd_probe.bcd` (or `<lab-dir>\bcd_probe\bcd_probe.bcd`)

It uses `bcdedit /store <probe-store> ...` for create/enum probes, so it avoids direct system-store mutation.

## Command matrix

Base matrix:

- `osloader`
- `bootsector`
- `bootapp`

Implementation also inspects `bcdedit /? create` output and may probe extra known tokens if present.

## Windows VM result snapshot

Observed in offline store `C:\LVHLab\bcd_probe\bcd_probe.bcd`:

- supported: `osloader`, `bootsector`, `bootapp`, `resume`, `startup`
- invalid/rejected: `ntldr`, `memdiag`
- sample created BOOTAPP GUID: `{4172ed59-57cf-11f1-b3c6-0800274f9ff7}`

Important:

- BOOTAPP creation success in offline store confirms parser acceptance only.
- It does not prove that firmware/bootmgr will boot the entry.

## Safety boundary

Probe does:

- create offline store (`/createstore`)
- create temporary application entries in that store (`/store ... /create`)
- enumerate offline store (`/store ... /enum all /v`)
- write JSON evidence and stdout/stderr artifacts

Probe does not do:

- no `{bootmgr}` mutation
- no `{fwbootmgr}` mutation
- no system `displayorder` changes
- no system BCD `default` changes

## What probe proves

- Whether BCDEdit parser accepts specific `/application` values in offline store context.
- GUID extraction and offline object creation behavior.

## What probe does not prove

- It does **not** prove that an entry is bootable.
- It does **not** prove Linux EFI chainloading support.
- Successful `bootapp` creation is **not** equivalent to successful reboot into GRUB/Ubuntu.

## Output artifacts

In `--report-dir`:

- `bcd_application_type_probe.json`
- `bcd_probe_enum_all_v.txt`
- `bcd_probe_enum_all_v.stderr.txt`

In `--lab-dir`:

- `bcd_probe\bcd_probe.bcd`
