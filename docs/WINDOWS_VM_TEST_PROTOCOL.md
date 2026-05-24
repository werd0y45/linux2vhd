# Windows VM Test Protocol (v0.5)

## Purpose

Reproducible, rollback-safe Windows VM validation campaign for guarded VHD/BCD experiments.

## Hard safety requirements

- Disposable Windows VM only.
- Snapshot/backup mandatory before mutation.
- No host machine mutation.
- No production boot store experiments.

## VM requirements

- Windows 11 VM (UEFI).
- Administrator account.
- Snapshot/revert capability.
- Python 3.12/3.13 environment with project dependencies.

## Campaign flow (v0.5)

1. Create VM snapshot.
2. `doctor --json`
3. `validation init`
4. `validation capabilities`
5. `validation run-dry`
6. optional `validation windows-probe`
7. optional `validation windows-vhd-smoke`
8. optional `validation windows-bcd-backup-smoke`
9. optional `validation windows-bcd-mutation-smoke`
10. `validation collect`
11. `validation render`
12. `validation bundle`
13. restore snapshot on any rollback uncertainty.

## Recommended command sequence

```powershell
python -m linux_vhd_launcher.cli doctor --json

python -m linux_vhd_launcher.cli validation init --report-dir .\validation_reports\campaign_001 --vm-snapshot-name pre-v05
python -m linux_vhd_launcher.cli validation capabilities --report-dir .\validation_reports\campaign_001 --json
python -m linux_vhd_launcher.cli validation run-dry --report-dir .\validation_reports\campaign_001

python -m linux_vhd_launcher.cli validation windows-probe \
  --report-dir .\validation_reports\campaign_001 \
  --execute-real-windows-ops \
  --i-understand-this-is-experimental \
  --no-dry-run

python -m linux_vhd_launcher.cli validation windows-vhd-smoke \
  --report-dir .\validation_reports\campaign_001 \
  --backend virtdisk \
  --execute-real-windows-ops \
  --i-understand-this-is-experimental \
  --no-dry-run

python -m linux_vhd_launcher.cli validation windows-bcd-backup-smoke \
  --report-dir .\validation_reports\campaign_001 \
  --execute-real-windows-ops \
  --i-understand-this-is-experimental \
  --no-dry-run

python -m linux_vhd_launcher.cli validation windows-bcd-mutation-smoke \
  --report-dir .\validation_reports\campaign_001 \
  --lab-dir .\validation_reports\campaign_001\lab \
  --confirm-vm-snapshot \
  --execute-real-windows-ops \
  --i-understand-this-is-experimental \
  --no-dry-run

python -m linux_vhd_launcher.cli validation collect --report-dir .\validation_reports\campaign_001
python -m linux_vhd_launcher.cli validation render --report-dir .\validation_reports\campaign_001
python -m linux_vhd_launcher.cli validation bundle --report-dir .\validation_reports\campaign_001 --redact --format zip
python -m linux_vhd_launcher.cli validation status --report-dir .\validation_reports\campaign_001
```

## `run-campaign` shortcut

Safe default orchestration:

```powershell
python -m linux_vhd_launcher.cli validation run-campaign --report-dir .\validation_reports\campaign_001
```

Mutation stage can be included only with explicit unsafe flags and snapshot confirmation.

## Pass criteria

- Linux-safe suite and dry campaign pass.
- schema v2 report generated.
- capability matrix persisted.
- mutation stage (if run) creates/deletes temporary entry with rollback evidence.
- bundle produced with checksums.

## Fail criteria

- Any real op bypasses safety gate.
- mutation leaves temporary entry unresolved.
- rollback evidence missing for mutation path.
- report/bundle artifacts inconsistent.

## Scope limitation

v0.5 supports guarded Windows VM validation experiments only.
It is still not a production Linux installer.
