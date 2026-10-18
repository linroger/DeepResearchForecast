"""Resend the exact run-3 modeler request once with the plain SDK; print status and the provider's error code/message only."""
import hashlib, json, os, sys, time
from pathlib import Path
src, dossier, profiles, out = sys.argv[1:5]
from dotenv import load_dotenv
load_dotenv("/Users/rogerlin/Downloads/DeepResearchForecast/.env", override=True)
os.environ["DRF_TEST_PROCESS"] = "1"
sys.path.insert(0, src + "/backend")
from app.config import Config
from app.services.world_simulation.compiler import build_compiler_messages
d = Path(dossier)
report = (d / "handoff/research_report.md").read_text(encoding="utf-8")
actors = json.loads((d / "handoff/actors.json").read_text(encoding="utf-8"))
state = json.loads((d / "pipeline_state.json").read_text(encoding="utf-8"))
project = json.loads((d / "project/project.json").read_text(encoding="utf-8"))
gen = "research_" + hashlib.sha256(json.dumps({"report": report, "actors": actors}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
profile = json.loads(Path(profiles).read_text())["after"]
messages = build_compiler_messages(research_report=report, research_generation_id=gen, research_engine="v3", actor_bundle=actors,
                                   ontology=project.get("ontology"), simulation_requirement=state.get("prompt") or "",
                                   max_actors=profile["limits"].get("maxActors"))
import httpx
from openai import OpenAI, APIStatusError
client = OpenAI(api_key=Config.LLM_API_KEY, base_url=profile["policy"]["baseUrl"], max_retries=0, timeout=900,
                http_client=httpx.Client(follow_redirects=False, trust_env=False, timeout=900))
started = time.monotonic()
try:
    response = client.chat.completions.create(model=profile["policy"]["model"], messages=messages, n=1, stream=False,
                                              max_tokens=profile["policy"]["modeler"]["maxOutputTokens"],
                                              response_format={"type": "json_object"},
                                              extra_body={"thinking": {"type": "disabled"}})
    choice = response.choices[0]
    Path(out).write_text(json.dumps({"finish": choice.finish_reason, "usage": response.usage.model_dump(),
                                     "content": choice.message.content}, ensure_ascii=False), encoding="utf-8")
    print("HTTP 200", choice.finish_reason, response.usage.model_dump(), f"{time.monotonic() - started:.1f}s")
except APIStatusError as error:
    body = error.body if isinstance(error.body, dict) else {}
    print("HTTP", error.status_code, "code", body.get("code"), "message", str(body.get("message"))[:300], f"{time.monotonic() - started:.1f}s")
print("system bytes", len(messages[0]["content"].encode()), "user bytes", len(messages[1]["content"].encode()))
