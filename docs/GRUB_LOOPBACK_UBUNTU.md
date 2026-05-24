# GRUB_LOOPBACK_UBUNTU

`v0.6-demo` generates a minimal GRUB entry for Ubuntu live ISO loopback boot.

## Template logic

- locate ISO inside VHD payload
- create `loopback`
- boot kernel/initrd from `(loop)`

Template example:

```grub
search --no-floppy --set=iso_root --file /live/ubuntu.iso
set root=($iso_root)
loopback loop /live/ubuntu.iso
linux (loop)/casper/vmlinuz boot=casper iso-scan/filename=/live/ubuntu.iso quiet splash ---
initrd (loop)/casper/initrd
boot
```

## Constraints

- Kernel/initrd paths are validated from inspected ISO metadata.
- If required paths are missing or nonstandard, build plan returns blocker.
- Boot parameters are template-based and must be validated by real VM reboot.

## Confirmation level

The generated `grub.cfg` is a demo artifact. Successful boot is **не подтверждено** until manual reboot test.

## Source

- GNU GRUB manual: https://www.gnu.org/software/grub/manual/grub/grub.html
