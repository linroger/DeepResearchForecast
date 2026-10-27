# Official connection and execution

Use `https://financialmodelingprep.com/mcp`. FMP documents MCP authentication through an `apikey` query parameter and demonstrates `list_tools` followed by `call_tool`. The helper constructs the authenticated URL privately from `FMP_API_KEY`; it does not print or persist it. See [FMP's official MCP documentation](https://site.financialmodelingprep.com/developer/docs/mcp-server).

The user-selected official service is distinct from the [imbenrabi community implementation](https://github.com/imbenrabi/financial-modeling-prep-mcp-server). Do not send credentials to that community deployment, launch its npm package, or use its tool names as official schemas. This skill does not need it.

## Credentials

Prefer `FMP_API_KEY` in the process environment or a private application dotenv file populated by the user. Never paste the value into a tool command. The standalone helper accepts `--env-file /absolute/path/.env` to read only FMP settings without printing values; it does not search the filesystem for secrets. Process environment takes precedence. In the application, use its normal environment loading. `FMP_ENABLED=false` disables acquisition.

An exposed key should be rotated locally. Do not copy an exposed chat key into a generated file. A missing key is a configuration gap; the rest of the research can continue using other sources.

## Standalone Codex helper

Run from the installed skill using an existing Python environment with `mcp>=1.30,<2`, `httpx>=0.28,<1`, and `jsonschema>=4.20,<5`. The project's backend virtual environment is suitable when provisioned from its current dependency files. Do not install packages globally or start a server merely to retrieve one dataset.

```sh
python3 <skill-dir>/scripts/fmp.py discover --query 'company profile financial statements'
python3 <skill-dir>/scripts/fmp.py call --tool <name-from-discovery> \
  --arguments-file /absolute/path/request.json --output /absolute/path/new-capture.json
```

If the secret lives in a local dotenv rather than the process environment, put `--env-file /absolute/path/.env` before `discover` or `call`. The JSON argument file contains only data parameters from the discovered schema. It must never contain an API key, network endpoint override or arbitrary request URL. A provider-defined `endpoint` selector is valid only when it exactly matches the discovered schema enum; also satisfy that endpoint's required parameters in the description.

The helper writes a new JSON file and refuses to overwrite an existing capture. A failed request has an explicit status and nonzero exit code. A successful helper call proves access through the helper only; native Codex MCP registration and the application's loaded deployment are separate states.

## Availability

The provider controls endpoint entitlements and quotas. `tools/list` availability is not a guarantee that a tool can retrieve data on the current account. Stop acquisition on provider-wide authentication failure. A capability-specific permission denial stops that access path and unchanged retries; independently available official capabilities may continue. A bare 403 establishes denied access, not its cause or scope. Report rate limits and do not silently switch providers or plans. FMP's [quickstart](https://site.financialmodelingprep.com/developer/docs/quickstart) and [documentation](https://site.financialmodelingprep.com/developer/docs) describe provider access and endpoint details.

Do not log authenticated URLs, HTTP headers, environment dumps or raw exception objects. Debug using status codes and sanitized reason classes. No credential belongs in the skill, repository, source citations or MCP tool arguments.
