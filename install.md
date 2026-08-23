# Install DCC-MCP ComfyUI

This is the canonical, agent-first Install SOP for the ComfyUI adapter. Its raw
instructions URL is:

```text
https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-comfyui/main/install.md
```

The adapter service talks to ComfyUI over its local HTTP API. Bounded Load3D
revision sync also requires the wheel's `dcc_mcp_sync` custom node to exist
under the target ComfyUI `custom_nodes` directory. HTTP reachability alone does
not satisfy that contract.

## Requirements

- Python 3.10 or newer.
- `dcc-mcp-core>=0.20.6,<1.0.0` in the same interpreter as the adapter.
- ComfyUI 0.32.0 or newer with the built-in `Load3D` node.
- The exact ComfyUI root containing `main.py` and `custom_nodes`.
- A trusted producer export root and the active ComfyUI input root.

Install or upgrade the published wheel first:

```bash
python -m pip install --upgrade dcc-mcp-comfyui
```

The wheel contains the custom-node payload. The lifecycle never downloads
ComfyUI, scrapes a latest release, or writes an adapter-owned binary cache.

## Supported versions and platforms

| Surface | Supported contract |
| --- | --- |
| Windows | Python 3.10+, ComfyUI 0.32.0+, standard or portable layout |
| macOS | Python 3.10+, ComfyUI 0.32.0+ source/application-managed layout |
| Linux | Python 3.10+, ComfyUI 0.32.0+ source or managed-host layout |
| DCC-MCP Core | `>=0.20.6,<1.0.0` |

All platforms use the same HTTP and custom-node contract. Distribution and
upgrades of ComfyUI itself remain operator-owned.

## Agent quick path

1. Install the published wheel into the exact Python that will run the adapter.
2. Run `dcc-mcp-comfyui install --json --dry-run --dcc-path <COMFYUI_ROOT>`.
3. Review the exact root, target, state, receipt, and ordered plan; repeat with
   `--yes` to commit it.
4. Restart the same ComfyUI instance without automating or closing its UI.
5. Configure both bounded sync roots and run
   `dcc-mcp-comfyui verify --json --comfyui-base-url <ORIGIN>`.
6. Continue only on exit 0 with `verify.directly_usable: true`; otherwise execute
   the single `next_steps[].command` argument vector and repeat verification.

## Manual path

### Resolve the platform path

Pass either the exact ComfyUI root or its `main.py` as `--dcc-path`.
Windows portable layouts may pass the parent whose direct `ComfyUI` child
contains `main.py` and `custom_nodes`.

Typical layouts are:

| Platform | Example ComfyUI root |
| --- | --- |
| Windows | `C:\ComfyUI_windows_portable\ComfyUI` |
| macOS | `/Users/me/Applications/ComfyUI` |
| Linux | `/opt/ComfyUI` |

The lifecycle accepts `DCC_MCP_COMFYUI_DCC_PATH` or `COMFYUI_PATH` when an
operator manages the path in the environment. It does not scan disks or infer a
root from unrelated directory names.

### Install the custom node

Request a non-mutating plan first. Omitting `--yes` is also plan-only:

```bash
dcc-mcp-comfyui install --json --dry-run \
  --dcc-path /absolute/path/to/ComfyUI \
  --python /absolute/path/to/python
```

Review the root, interpreter, state, plan, target, and receipt, then execute:

```bash
dcc-mcp-comfyui install --json --yes \
  --dcc-path /absolute/path/to/ComfyUI \
  --python /absolute/path/to/python
```

The installer copies a complete stage beside `custom_nodes/dcc_mcp_sync`,
validates it, moves the previous receipted node and receipt aside, commits the
new pair, and only then removes its generated backups. A commit failure restores
the previous node and receipt. It never performs delete-then-copy replacement
and never overwrites an unreceipted directory.

A successful file install returns `requires_restart` because ComfyUI registers
Python nodes and web extensions during startup. Save the current workflow and
restart the same ComfyUI instance; the lifecycle does not close or manipulate
the application.

### Configure bounded sync

Set both roots in the service environment. They must already exist:

Windows PowerShell:

```powershell
$env:DCC_MCP_COMFYUI_SYNC_SOURCE_ROOT = "D:\dcc-sync\exports"
$env:DCC_MCP_COMFYUI_INPUT_DIR = "C:\ComfyUI\input"
```

macOS or Linux:

```bash
export DCC_MCP_COMFYUI_SYNC_SOURCE_ROOT=/srv/dcc-sync/exports
export DCC_MCP_COMFYUI_INPUT_DIR=/opt/ComfyUI/input
```

`DCC_MCP_COMFYUI_BASE_URL` defaults to `http://127.0.0.1:8188`. Use an
explicit credential-free HTTP(S) origin when the intended instance differs.

### Status and verify

Status is read-only and can consume the default receipt without another host
path:

```bash
dcc-mcp-comfyui status --json
```

After restarting ComfyUI, verify the full usable contract:

```bash
dcc-mcp-comfyui verify --json \
  --comfyui-base-url http://127.0.0.1:8188
```

Verification checks the target Python imports and Core floor, bounded sync
configuration, `/system_stats` and the ComfyUI 0.32.0 floor, live `Load3D`
discovery, the exact `dcc_mcp_sync` web extension, and its typed latest-revision
route. `verify.directly_usable=true` is emitted only when every check passes.

`doctor --json` performs the same read-only checks and is suitable for support
and CI diagnostics. A reachable base URL without the typed custom-node route is
reported as `custom_node_runtime_missing`, not as usable.

## Upgrade

Upgrade the wheel, plan the receipted custom-node replacement, execute it, then
restart and verify:

```bash
python -m pip install --upgrade dcc-mcp-comfyui
dcc-mcp-comfyui upgrade --json --dry-run
dcc-mcp-comfyui upgrade --json --yes
dcc-mcp-comfyui verify --json
```

`upgrade` requires a receipt and uses the same staged replacement and rollback
contract as install. A missing receipted target is a repairable partial state;
a modified or unreceipted target fails closed instead of deleting unknown
content.

## Uninstall

Plan and execute removal before uninstalling the wheel:

```bash
dcc-mcp-comfyui uninstall --json --dry-run
dcc-mcp-comfyui uninstall --json --yes
python -m pip uninstall dcc-mcp-comfyui
```

Uninstall consumes only the receipt and verifies the exact file set and
SHA-256 digests before removal. It refuses an unreceipted or modified directory,
does not remove ComfyUI, and does not touch workflows, models, inputs, outputs,
or other custom nodes. Running it again is an idempotent exit 0.

Stop any adapter sidecar through the operator or service supervisor that
started it. If the operating system reports a file lock, save work and stop the
specific ComfyUI process before retrying. The lifecycle never terminates either
process itself.

## JSON and exit codes

All lifecycle verbs accept `--json`, `--yes`, `--dry-run`, `--dcc-path`,
`--python`, `--receipt-path`, `--comfyui-base-url`, `--sync-source-root`, and
`--input-dir`. Results follow Install SOP schema version 1. Each next step is an
argument vector suitable for direct execution after substituting only a named
placeholder.

| Exit | Meaning |
| ---: | --- |
| `0` | Plan or operation completed, or verify proved direct usability. |
| `10` | Preflight failed: path, interpreter, config, receipt, or ownership is invalid. |
| `20` | Reserved for pinned acquisition or integrity failure. |
| `30` | Install, uninstall, receipt commit, or rollback failed. |
| `40` | Endpoint or typed verify-to-usable failed. |
| `50` | A restart is required, including a proven Windows file lock. |

## Troubleshooting

- `comfyui_root_required` or `comfyui_root_invalid`: pass the exact root that
  contains `main.py` and `custom_nodes`. Do not substitute the output, input,
  model, or application-launcher directory.
- `target_import_failed` or `core_version_unsupported`: install the adapter and
  supported Core into the exact `--python`, then repeat the read-only plan.
- `sync_config_missing`: configure both trusted roots. Doctor never guesses or
  creates them.
- `endpoint_unreachable`: start the intended ComfyUI instance and confirm the
  credential-free base URL. Inspect ComfyUI's own log for startup errors.
- `base_url_invalid`: pass one credential-free HTTP(S) origin. Embedded URL
  credentials, paths, queries, and fragments are rejected; this adapter does
  not silently negotiate a private authentication scheme.
- `comfyui_version_unsupported`: upgrade ComfyUI through its operator-owned
  installation channel to 0.32.0 or newer.
- `load3d_unavailable`: use a compatible ComfyUI build that contains `Load3D`.
- `custom_node_runtime_missing`: if status says `installed`, restart ComfyUI and
  rerun verify. Otherwise run the returned receipted install plan.
- `installed_file_set_mismatch` or `installed_file_digest_mismatch`: inspect the
  target manually. The lifecycle will not overwrite or uninstall files outside
  its receipt.
- `windows_file_lock`: save work, stop only the reported ComfyUI process, and
  repeat the returned command. No UI automation is attempted.

The DCC-MCP Core catalog still needs to publish this runbook as the adapter's
`instructions_url`; that cross-repository catalog entry is not installed or
claimed by this repository lifecycle.
