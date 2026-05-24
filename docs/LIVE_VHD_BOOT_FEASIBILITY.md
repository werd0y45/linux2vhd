# LIVE_VHD_BOOT_FEASIBILITY

Date: 2026-05-24
Status: demo-only feasibility, not a production claim

## 1) Что Microsoft документирует для Native Boot VHD/VHDX

Подтверждено:

- `bcdedit` поддерживает управление store/entries (`/enum`, `/export`, `/import`, `/copy`, `/create`, `/delete`, `/set`, `/displayorder`).
- `bcdboot` документирован для инициализации Windows boot files/BCD.
- `diskpart` документирует `create vdisk`, `select vdisk`, `attach vdisk`, `detach vdisk`.
- PowerShell документирует `Mount-DiskImage`/`Dismount-DiskImage` и Hyper-V `New-VHD`/`Mount-VHD`/`Dismount-VHD`.

Ограничение:

- Microsoft Native Boot guidance фокусируется на Windows boot targets в VHD/VHDX, а не на Linux live ISO chain.

## 2) Документирован ли Linux live boot из VHDX через BCD напрямую

Ответ: **не подтверждено**.

В официальной документации не найден подтвержденный сценарий прямой цепочки `Windows Boot Manager -> Linux live EFI payload inside VHDX file`.

## 3) Может ли Windows Boot Manager загрузить произвольный EFI binary из VHDX

Ответ: **не подтверждено для данного сценария**.

`bcdedit` позволяет задавать entry/payload path, но документированная гарантия для произвольного Linux EFI binary внутри VHDX как native path отсутствует.

## 4) Может ли UEFI firmware видеть EFI-раздел внутри VHDX-файла на NTFS

Ответ: **не подтверждено**.

UEFI обычно работает с firmware-visible devices/ESP; для ESP, вложенного в файл VHDX на NTFS host volume, подтвержденного универсального поведения не зафиксировано.

## 5) Реалистичные стратегии demo

- Strategy A: `VHDX payload + BCD/Windows Boot Manager chain`
  - Применять только как **experimental registration attempt**.
  - Готовая загрузка не заявляется без reboot proof.

- Strategy B: `VHDX payload + firmware/ESP-staged shim/grub`
  - Может быть ближайшим fallback, но в текущем этапе остается экспериментом.

- Strategy C: `VHDX payload artifact only + blocked registration`
  - Рекомендуемая безопасная default-стратегия, если путь не подтвержден.

## 6) Что проверяется только реальным reboot test

Только реальный VM reboot подтверждает:

- что boot entry реально появляется и исполняется;
- что shim/grub/kernel/initrd цепочка фактически запускается;
- что ISO loopback параметры корректны для конкретного ISO;
- что после rollback BCD store остается консистентным.

## 7) Команды, используемые в demo, и подтверждение источниками

- BCD operations: `bcdedit /enum /export /copy /set /delete`.
- BCD restore primitive: `bcdedit /import` (emergency mode only).
- Boot files tooling: `bcdboot <source> [/s] [/f]`.
- Virtual disk ops: `diskpart` (`create/select/attach/detach vdisk`).
- ISO mount: `Mount-DiskImage`, `Dismount-DiskImage`.
- Optional Hyper-V path: `New-VHD`, `Mount-VHD`, `Dismount-VHD`.

## Sources

- https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/bcdedit
- https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/bcdboot
- https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/create-vdisk
- https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/attach-vdisk
- https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/detach-vdisk
- https://learn.microsoft.com/en-us/powershell/module/storage/mount-diskimage
- https://learn.microsoft.com/en-us/powershell/module/storage/dismount-diskimage
- https://learn.microsoft.com/en-us/powershell/module/hyper-v/new-vhd
- https://learn.microsoft.com/en-us/powershell/module/hyper-v/mount-vhd
- https://learn.microsoft.com/en-us/powershell/module/hyper-v/dismount-vhd
- https://www.gnu.org/software/grub/manual/grub/grub.html
