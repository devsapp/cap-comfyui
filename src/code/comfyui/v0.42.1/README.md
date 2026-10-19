# ComfyUI v0.42.1 / CAP v5

This independent release line inherits the v4 multi-tenant plugin, template
input provisioning, snapshot restoration and opaque FC task-ID compatibility.
Older release directories and the default root build version are unchanged.

| Component | Pinned version |
| --- | --- |
| Upstream ComfyUI | `v0.42.1` / `63be2f9b82ad0dac88a7ceaa28a9cf3154125a18` |
| CAP / builtin dependency fingerprint | `5.0.0` |
| Agent production candidate | `image-generation-comfyui-agent:v5.0.0` |
| OSS base prefix | `base/comfyui/v0.42.1-gamma` |
| Frontend | `1.55.18` (upstream requirements) |
| Workflow templates | `0.11.89` |
| Template input revision | `7d8ed32f0bf6b8d52129976535422d6f518fe463` |

## Compatibility audit

Compared with v0.33.1, upstream raises embedded docs to 0.5.14, PyAV to
`>=17.0.0`, comfy-kitchen to 0.2.39 and comfy-aimdo to 0.5.6. The v4
Torch 2.9.1 / Nunchaku 1.0.2 / transformers 4.56.2 constraints are retained.
The two allowlisted Nano Banana Pro PNGs have the same Git blobs and lengths
in templates 0.11.41 and 0.11.89; their existing SHA256 checks remain valid.

Upstream `PromptExecutor.execute` is still synchronous and delegates through
`asyncio.run`, so the tenant context continues into async execution. The cache
signature hook is still asynchronous with the same parameters. The UUID-only
validator is still imported into both `server` and `comfy_execution.jobs`, and
the builtin compatibility plugin patches both aliases.

Upstream now checks traversal in annotated input paths; the contract tests use
the actual upstream functions and verify they compose with DynamicPathProxy.
The upstream asset database is disabled by default and this release does not
enable it. Multi-tenant support for a user-supplied `--enable-assets` boot flag
is outside this release's validated configuration.

## Validation

```bash
COMFYUI_UPSTREAM_DIR=/path/to/ComfyUI-v0.42.1 python3 -m pytest \
  src/code/comfyui/v0.42.1/tests \
  src/code/comfyui/custom_nodes/funart_prompt_id_compat/tests -q

make -C src/code/comfyui/v0.42.1 build
```

The source build checks that the upstream tag resolves to the pinned SHA.
After building, validate startup, `/initialize`, a real prompt with an opaque
FC task ID, tenant input/output separation and snapshot save/restore in the
candidate image before accepting the release. Unit/contract tests do not
replace these runtime checks.
