# BCD_BOOTAPP_ELEMENT_PROBE

## Purpose

`demo bcd probe-bootapp-elements` checks whether an offline BOOTAPP object accepts key elements:

- `device`
- `path`
- `description`

It runs only against an offline store and writes structured evidence.

Related probe:

- `demo bcd probe-bootapp-vhd-device` checks BOOTAPP with:
  - `device vhd=[C:]\LVHLab\ubuntu-live.vhdx`
  - `path \EFI\BOOT\BOOTX64.EFI`
  in offline BCD store only.

## Safety model

Probe store path:

- `C:\LVHLab\bcd_probe\bootapp_elements_probe.bcd`

All mutating commands use:

- `bcdedit /store <offline-store> ...`

This is safer than touching the live system store because:

- no mutation of active boot menu
- no `{bootmgr}` rewrite
- no `{fwbootmgr}` rewrite
- no `default` change
- no system `displayorder` change

## What it verifies

- Offline `/create /application bootapp` parser acceptance.
- Offline `/set` acceptance for tested element/value pairs.
- Whether `bcdedit /enum all /v` shows resulting object state.

## What it does not verify

- It does not verify firmware execution path.
- It does not verify Windows Boot Manager runtime behavior.
- It does not verify Secure Boot compatibility for shim/grub.
- It does not verify Ubuntu/GRUB boot success.
- It does not guarantee that GRUB launched from ESP can see ISO that lives inside VHDX payload.

## Important interpretation rule

Even when `bcdedit /set {GUID} path ...` is accepted in an offline store, this only proves syntactic/semantic acceptance by BCDEdit parser for that store.

It is not proof of bootability.

## Why VHD-device probe matters

- ESP-staged BOOTAPP can be valid syntactically but still fail the project goal where ISO is stored inside VHDX.
- BOOTAPP + VHD device probe is the next closest offline experiment to project intent:
  - BCD points to VHDX payload path
  - BOOTAPP path points to EFI loader expected inside that payload
