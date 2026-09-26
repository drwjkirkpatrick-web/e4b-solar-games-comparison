#!/usr/bin/env python3
"""Generate request JSON files and meta files for games in a range."""
import json, os, sys

CONFIG = "/home/walker/projects/ornith-q4km-retest/test_config.json"
LOGS = "/home/walker/projects/e4b-solar-games-comparison/logs"

start = int(sys.argv[1])
end = int(sys.argv[2])

with open(CONFIG) as f:
    games = json.load(f)

for game in games:
    order = game["order"]
    if order < start or order > end:
        continue
    
    name = game["project"]
    prompt = game["prompt"]
    system_prompt = game["system_prompt"] + "\n/no_think"
    
    # Write request file
    req = {
        "model": "gemma-4-e4b-qat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "top_k": 40,
        "top_p": 0.95,
        "repeat_penalty": 1.0,
        "max_tokens": 20000,
        "stream": False,
    }
    
    req_file = os.path.join(LOGS, f"request_{name}.json")
    with open(req_file, "w") as f:
        json.dump(req, f)
    
    # Write meta file for bash script to source
    meta_file = os.path.join(LOGS, f"meta_{order}.txt")
    prior_tok = game.get("prior_tokens", 0)
    prior_time = game.get("prior_time_s", 0)
    prior_valid = "YES" if game.get("prior_valid") else "NO"
    
    with open(meta_file, "w") as f:
        f.write(f'GAME_NAME="{name}"\n')
        f.write(f'PRIOR_TOK={prior_tok}\n')
        f.write(f'PRIOR_TIME={prior_time}\n')
        f.write(f'PRIOR_VALID="{prior_valid}"\n')
    
    print(f"  Game {order}: {name} — request + meta written")

print(f"Done. {end - start + 1} games prepared.")