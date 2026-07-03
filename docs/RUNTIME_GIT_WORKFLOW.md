# Runtime-Safe Git Workflow

Garner Quant writes local CSV and JSON files while the runtime is running. These
files are generated state, not source code. They must not participate in stash,
pop, rebase, merge, or conflict resolution.

## File Convention

Source files live in normal project folders such as:

- `config.py`
- `execution/`
- `runtime/`
- `research/`
- `dashboard/`
- `pages/`
- `scripts/`
- `docs/`

Generated runtime files are listed in:

- `runtime/generated_runtime_files.txt`

Current runtime outputs still use legacy paths such as `paper_portfolio_v3.csv`
and `data/live_runtime_status.json`. New generated runtime data should prefer:

- `data/runtime/`
- `runtime_data/`

## Normal Development

1. Keep the runtime stopped while changing source code.
2. Check repository state:

   ```powershell
   .\scripts\status_repo.ps1
   ```

3. Edit source files only.
4. Validate/start runtime:

   ```powershell
   .\scripts\start_runtime.ps1
   ```

The runtime refuses to start if generated CSV/JSON files contain git conflict
markers or invalid JSON/CSV structure.

## Updating The Repository

Use the safe wrapper instead of raw `git pull --rebase`:

```powershell
.\scripts\update_repo.ps1
```

The wrapper:

- refuses to run while the local runtime is active
- validates generated runtime data before updating
- marks tracked generated runtime files as `skip-worktree`
- stashes source changes only
- runs `git pull --rebase`
- restores source changes
- validates generated runtime data again

## Restarting Runtime

```powershell
.\scripts\stop_runtime.ps1
.\scripts\status_repo.ps1
.\scripts\update_repo.ps1
.\scripts\start_runtime.ps1
```

## Recovering From Failed Stash, Pop, Rebase, Or Merge

1. Stop the runtime:

   ```powershell
   .\scripts\stop_runtime.ps1
   ```

2. Check for conflicts and corrupted generated files:

   ```powershell
   .\scripts\status_repo.ps1
   ```

3. Resolve source conflicts only.
4. If a generated runtime file contains conflict markers, recover it from a
   known-good local backup, latest clean runtime output, or remote dashboard
   state. Do not hand-edit ticker rows around conflict markers.
5. Validate again:

   ```powershell
   python -m runtime.startup_validation
   ```

6. Start runtime only after validation passes.

## Why This Exists

Generated runtime files can change every cycle. If git writes conflict markers
into them, downstream code can misread those markers as real data, including as
ticker symbols. The startup validator is deliberately strict so corrupted
runtime state fails fast instead of being interpreted by live automation.
