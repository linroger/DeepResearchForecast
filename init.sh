#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

test -f "$project_root/backend/pyproject.toml"
test -x "$project_root/backend/.venv/bin/python"
test -f "$project_root/frontend/package.json"
test -f "$project_root/deerflow_bridge/deerflow_research.py"

"$project_root/backend/.venv/bin/python" -m compileall -q \
  "$project_root/backend/app/services/actor_context.py" \
  "$project_root/backend/app/services/actor_dossier_compactor.py" \
  "$project_root/backend/app/services/actor_role_prompt.py" \
  "$project_root/backend/app/services/oasis_profile_generator.py" \
  "$project_root/backend/app/services/pipeline_orchestrator.py" \
  "$project_root/backend/app/services/simulation_config_generator.py" \
  "$project_root/backend/app/services/simulation_manager.py" \
  "$project_root/backend/app/services/simulation_runner.py" \
  "$project_root/backend/app/utils/actors.py" \
  "$project_root/deerflow_bridge/deerflow_research.py" \
  "$project_root/deerflow_bridge/data_mcp.py" \
  "$project_root/deerflow_bridge/data_catalog.py" \
  "$project_root/deerflow_bridge/data_sources.py" \
  "$project_root/deerflow_bridge/data_tools.py" \
  "$project_root/deerflow_bridge/research_skills.py"

node -e "const p=require(process.argv[1]); if(!p.scripts) process.exit(1)" \
  "$project_root/frontend/package.json"

printf 'DeepResearchForecast actor-grounding smoke check passed.\n'
