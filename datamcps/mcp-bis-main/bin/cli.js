#!/usr/bin/env node
//
// Entry point for `npx @pipeworx/mcp-<slug>`.
//
// Packs ship as raw TypeScript (no build step — see publish-pack.sh for why:
// tsx sidesteps every extensionless-import / bare-JSON-import edge case a
// per-pack tsc build would have to solve one pack at a time). This file
// registers tsx's ESM loader programmatically, then hands off to src/server.ts,
// which wraps the pack's {tools, callTool} export in a stdio MCP server.
//
// Copied verbatim into every published pack repo by scripts/publish-pack.sh —
// edit this file, not a per-pack copy.
import { register } from 'tsx/esm/api';

register();

await import('../src/server.ts');
