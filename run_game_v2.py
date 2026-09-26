#!/usr/bin/env python3
"""
E4B vs Ornith Solar Games Comparison — Hardened v2
Uses curl as detached subprocess to survive harness death.
Curl writes streaming JSON to a file; harness parses afterward.
Server started via setsid, fully detached.
"""
import subprocess
import json
import time
import re
import os
import sys
import signal
import urllib.request
import urllib.error
from pathlib import Path

MODEL = os.path.expanduser("~/models/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf")
LLAMA_SERVER = os.path.expanduser("~/llama.cpp/build/bin/llama-server")
TEST_CONFIG = os.path.expanduser("~/projects/ornith-q4km-retest/test_config.json")
PROJECT_DIR = os.path.expanduser("~/projects/e4b-solar-games-comparison")
OUTPUTS_DIR = os.path.join(PROJECT_DIR, "outputs")
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")
RESULTS_FILE = os.path.join(RESULTS_DIR, "comparison_results.jsonl")
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")
PORT = 8091
MAX_TOKENS = 20000

os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

SAMPLING = {
    "temperature": 0.4,
    "top_k": 40,
    "top_p": 0.95,
    "repeat_penalty": 1.0,
}

SERVER_ARGS = [
    LLAMA_SERVER,
    "-m", MODEL,
    "--alias", "gemma-4-e4b-qat",
    "--host", "127.0.0.1", "--port", str(PORT),
    "-ngl", "99", "-c", "32768",
    "-ctk", "f16", "-ctv", "f16",
    "-b", "512", "-ub", "512",
    "-fa", "on", "--jinja", "--fit", "off",
    "-np", "1", "-t", "6",
    "--temp", "0.4", "--top-p", "0.95", "--top-k", "40",
    "--repeat-penalty", "1.0",
]

def load_games():
    with open(TEST_CONFIG) as f:
        return json.load(f)

def start_server(game_name):
    """Start E4B server fully detached via setsid"""
    log_file = os.path.join(LOGS_DIR, f"server_{game_name}.log")
    env = os.environ.copy()
    env["GGML_CUDA_ENABLE_UNIFIED_MEMORY"] = "1"

    # Write a launcher script so setsid runs it cleanly
    launcher = os.path.join(LOGS_DIR, f"launch_server_{game_name}.sh")
    with open(launcher, "w") as f:
        f.write("#!/bin/bash\n")
        f.write(f"exec {' '.join(SERVER_ARGS)} > {log_file} 2>&1\n")
    os.chmod(launcher, 0o755)

    # Launch with setsid — fully detached, survives parent death
    proc = subprocess.Popen(
        ["setsid", "bash", launcher],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait for server readiness
    for i in range(90):
        time.sleep(2)
        try:
            req = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=5)
            if req.status == 200:
                return proc
        except:
            pass

    print(f"  ERROR: Server failed to start within 180s")
    proc.kill()
    return None

def stop_server():
    """Kill any running llama-server"""
    subprocess.run(["pkill", "-9", "-f", "llama-server"], capture_output=True)
    time.sleep(3)

def send_completion_curl(prompt_text, system_prompt, game_name):
    """Send completion via detached curl that writes to a file.
    Curl survives even if the harness dies."""
    sys_content = system_prompt + "\n/no_think"

    body = json.dumps({
        "model": "gemma-4-e4b-qat",
        "messages": [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": prompt_text},
        ],
        "temperature": SAMPLING["temperature"],
        "top_k": SAMPLING["top_k"],
        "top_p": SAMPLING["top_p"],
        "repeat_penalty": SAMPLING["repeat_penalty"],
        "max_tokens": MAX_TOKENS,
        "stream": False,
    })

    # Write request body to temp file (avoids shell escaping issues)
    req_file = os.path.join(LOGS_DIR, f"request_{game_name}.json")
    with open(req_file, "w") as f:
        f.write(body)

    resp_file = os.path.join(LOGS_DIR, f"response_{game_name}.json")

    # Build curl command with no shell timeout
    curl_cmd = [
        "curl", "-s", "-S",
        "--max-time", "7200",        # 2 hour max
        "--connect-timeout", "30",
        "-X", "POST",
        f"http://127.0.0.1:{PORT}/v1/chat/completions",
        "-H", "Content-Type: application/json",
        "-d", f"@{req_file}",
        "-o", resp_file,
    ]

    # Run curl directly (not backgrounded) — it blocks until done
    # but even if THIS process dies, curl was already given the output file
    t0 = time.time()
    result = subprocess.run(curl_cmd, capture_output=True, timeout=7300)
    elapsed = time.time() - t0

    if result.returncode != 0:
        return {"error": f"curl exit {result.returncode}: {result.stderr.decode()[:200]}", "elapsed": elapsed}

    # Parse response file
    if not os.path.exists(resp_file) or os.path.getsize(resp_file) == 0:
        return {"error": "empty response file", "elapsed": elapsed}

    try:
        with open(resp_file) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        # Try to read raw for debugging
        with open(resp_file) as f:
            raw = f.read(500)
        return {"error": f"JSON parse error: {e}, raw: {raw}", "elapsed": elapsed}

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    reasoning = data.get("choices", [{}])[0].get("message", {}).get("reasoning_content", "")
    usage = data.get("usage", {})
    finish_reason = data.get("choices", [{}])[0].get("finish_reason", "")

    completion_tokens = usage.get("completion_tokens", 0)
    prompt_tokens = usage.get("prompt_tokens", 0)
    tps = completion_tokens / elapsed if elapsed > 0 and completion_tokens > 0 else 0

    return {
        "content": content,
        "reasoning": reasoning,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": usage.get("total_tokens", 0),
        "elapsed": elapsed,
        "tps": tps,
        "finish_reason": finish_reason,
        "thinking_chars": len(reasoning),
        "content_chars": len(content),
    }

def validate_html(html):
    checks = {
        "has_html": "<html" in html.lower() or "<!DOCTYPE" in html.lower(),
        "has_closing_html": "</html>" in html.lower(),
        "has_body": "<body" in html.lower(),
        "has_script": "<script" in html.lower(),
        "has_canvas": "<canvas" in html.lower(),
        "balanced_braces": html.count("{") == html.count("}"),
        "balanced_parens": html.count("(") == html.count(")"),
        "not_truncated": "</html>" in html.lower() or "</body>" in html.lower(),
    }
    passed = sum(checks.values())
    total = len(checks)
    lines = html.count("\n") + 1
    functions = len(re.findall(r"function\s+\w+|=>\s*{|:\s*function", html))
    return {
        "checks": checks,
        "score": (passed / total) * 100,
        "passed": passed,
        "total": total,
        "lines": lines,
        "functions": functions,
        "chars": len(html),
    }

def extract_html(content):
    html_match = re.search(r'```html?\s*\n(.*?)```', content, re.DOTALL | re.IGNORECASE)
    if html_match:
        return html_match.group(1).strip()
    html_match = re.search(r'(<!DOCTYPE|<html).*', content, re.DOTALL | re.IGNORECASE)
    if html_match:
        return html_match.group(0).strip()
    if "<html" in content.lower() or "<!DOCTYPE" in content.lower():
        return content.strip()
    return content.strip()

def run_single_game(game):
    order = game["order"]
    name = game["project"]
    prompt = game["prompt"]
    system_prompt = game["system_prompt"]

    prior_tokens = game.get("prior_tokens", 0)
    prior_time = game.get("prior_time_s", 0)
    prior_energy = game.get("prior_energy_wh", 0) or 0
    prior_valid = game.get("prior_valid", False)

    print(f"\n{'='*70}")
    print(f"GAME {order}/19: {name}")
    print(f"  Prompt: {len(prompt)} chars")
    print(f"  Prior Ornith: {prior_tokens} tok, {prior_time}s, {prior_energy:.2f} Wh, valid={'YES' if prior_valid else 'NO'}")
    print(f"{'='*70}")
    print(f"  Starting E4B server (setsid detached)...")

    # Kill any leftover server, drop caches
    stop_server()
    sync_caches()

    proc = start_server(name)
    if not proc:
        result = {
            "order": order, "game": name, "error": "server failed to start",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(RESULTS_FILE, "a") as f:
            f.write(json.dumps(result) + "\n")
        return result

    result = {
        "order": order,
        "game": name,
        "prompt_chars": len(prompt),
        "prior_model": "Ornith-1.0-9B IQ3_M",
        "prior_tokens": prior_tokens,
        "prior_time_s": prior_time,
        "prior_energy_wh": prior_energy,
        "prior_valid": prior_valid,
        "prior_issues": game.get("prior_issues", 0),
        "e4b_model": "Gemma 4 E4B QAT",
        "e4b_settings": {**SAMPLING, "max_tokens": MAX_TOKENS, "thinking": False},
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        print(f"  Sending prompt via curl (max_tokens={MAX_TOKENS})...")
        print(f"  Settings: temp={SAMPLING['temperature']} topk={SAMPLING['top_k']} topp={SAMPLING['top_p']} rp={SAMPLING['repeat_penalty']} thinking=off")
        completion = send_completion_curl(prompt, system_prompt, name)

        if "error" in completion:
            result["error"] = completion["error"]
            result["elapsed"] = completion.get("elapsed", 0)
            print(f"  ERROR: {completion['error'][:100]}")
        else:
            result.update(completion)
            html = extract_html(completion["content"])
            result["html_chars"] = len(html)
            validation = validate_html(html)
            result["validation"] = validation
            result["is_complete"] = validation["checks"]["not_truncated"]

            output_file = os.path.join(OUTPUTS_DIR, f"{order:02d}_{name}.html")
            with open(output_file, "w") as f:
                f.write(html)
            result["output_file"] = output_file

            tok_diff = completion["completion_tokens"] - prior_tokens
            time_diff = completion["elapsed"] - prior_time
            o_tps = prior_tokens / prior_time if prior_time > 0 else 0

            print(f"\n  RESULT:")
            print(f"    E4B:     {completion['completion_tokens']} tok, {completion['elapsed']:.1f}s, {completion['tps']:.1f} tok/s, score={validation['score']:.0f}, complete={'YES' if result['is_complete'] else 'NO'}")
            print(f"    Ornith:  {prior_tokens} tok, {prior_time}s, {o_tps:.1f} tok/s, valid={'YES' if prior_valid else 'NO'}")
            print(f"    Delta:   {tok_diff:+d} tok, {time_diff:+.1f}s, {completion['tps']/o_tps:.2f}x speed" if o_tps > 0 else "")
            print(f"    HTML:    {validation['chars']} chars, {validation['lines']} lines, {validation['functions']} functions")
            print(f"    Saved:   {output_file}")

    except Exception as e:
        result["error"] = str(e)
        print(f"  EXCEPTION: {e}")
    finally:
        print(f"  Stopping server...")
        stop_server()

    with open(RESULTS_FILE, "a") as f:
        f.write(json.dumps(result) + "\n")

    return result

def sync_caches():
    """Drop filesystem caches to free memory (needs sudo)"""
    subprocess.run(["sync"], capture_output=True)
    try:
        subprocess.run(["sudo", "tee", "/proc/sys/vm/drop_caches"], input=b"3\n", capture_output=True, timeout=5)
    except Exception:
        pass  # non-fatal, just skip cache drop

def print_summary():
    if not os.path.exists(RESULTS_FILE):
        print("No results yet.")
        return

    results = []
    with open(RESULTS_FILE) as f:
        for line in f:
            results.append(json.loads(line.strip()))

    valid = [r for r in results if "error" not in r and r.get("completion_tokens", 0) > 0]
    errors = [r for r in results if "error" in r or r.get("completion_tokens", 0) == 0]

    print(f"\n{'='*90}")
    print(f"E4B vs Ornith Solar Games Comparison — {len(valid)} completed, {len(errors)} errors/incomplete")
    print(f"{'='*90}")

    print(f"\n{'#':>2} {'Game':<26} {'E4B tok':>8} {'Orn tok':>8} {'E4B t(s)':>9} {'Orn t(s)':>9} {'E4B t/s':>7} {'Orn t/s':>7} {'E4B ok':>6} {'Orn ok':>6}")
    print(f"{'-'*2} {'-'*26} {'-'*8} {'-'*8} {'-'*9} {'-'*9} {'-'*7} {'-'*7} {'-'*6} {'-'*6}")

    for r in valid:
        order = r["order"]
        name = r["game"][:26]
        e_tok = r.get("completion_tokens", 0)
        o_tok = r.get("prior_tokens", 0)
        e_time = r.get("elapsed", 0)
        o_time = r.get("prior_time_s", 0)
        e_tps = r.get("tps", 0)
        o_tps = o_tok / o_time if o_time > 0 else 0
        e_ok = "YES" if r.get("is_complete") else "NO"
        o_ok = "YES" if r.get("prior_valid") else "NO"
        print(f"{order:>2} {name:<26} {e_tok:>8} {o_tok:>8} {e_time:>9.1f} {o_time:>9.1f} {e_tps:>7.1f} {o_tps:>7.1f} {e_ok:>6} {o_ok:>6}")

    if valid:
        avg_e_tok = sum(r.get("completion_tokens",0) for r in valid) / len(valid)
        avg_o_tok = sum(r.get("prior_tokens",0) for r in valid) / len(valid)
        avg_e_time = sum(r.get("elapsed",0) for r in valid) / len(valid)
        avg_o_time = sum(r.get("prior_time_s",0) for r in valid) / len(valid)
        avg_e_tps = sum(r.get("tps",0) for r in valid) / len(valid)
        avg_o_tps = sum(r.get("prior_tokens",0)/r.get("prior_time_s",1) for r in valid) / len(valid)
        e_complete = sum(1 for r in valid if r.get("is_complete"))
        o_complete = sum(1 for r in valid if r.get("prior_valid"))

        print(f"{'-'*2} {'-'*26} {'-'*8} {'-'*8} {'-'*9} {'-'*9} {'-'*7} {'-'*7} {'-'*6} {'-'*6}")
        print(f"   {'AVERAGE':<26} {avg_e_tok:>8.0f} {avg_o_tok:>8.0f} {avg_e_time:>9.1f} {avg_o_time:>9.1f} {avg_e_tps:>7.1f} {avg_o_tps:>7.1f} {e_complete:>6} {o_complete:>6}")
        print(f"   {'SPEEDUP':<26} {'':>8} {'':>8} {'':>9} {'':>9} {avg_e_tps/avg_o_tps:>6.2f}x {'':>7}")

    if errors:
        print(f"\nErrors/Incomplete:")
        for r in errors:
            print(f"  Game {r['order']} {r.get('game','')}: {r.get('error','0 tokens')[:60]}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run_game_v2.py <game_number|all|summary>")
        print("  game_number: 1-19")
        print("  all: run all remaining games (skips completed)")
        print("  summary: print comparison table")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "summary":
        print_summary()
        return

    games = load_games()

    if arg == "all":
        # Resume support
        completed_orders = set()
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE) as f:
                for line in f:
                    try:
                        r = json.loads(line.strip())
                        if "error" not in r and r.get("completion_tokens", 0) > 0:
                            completed_orders.add(r["order"])
                    except:
                        pass
        if completed_orders:
            print(f"Resuming — {len(completed_orders)} games already completed: {sorted(completed_orders)}")
        
        remaining = [g for g in games if g["order"] not in completed_orders]
        print(f"Running {len(remaining)} of {len(games)} games (skipping {len(completed_orders)})...")
        for game in remaining:
            run_single_game(game)
            time.sleep(5)
        print_summary()
    elif arg.isdigit():
        game_num = int(arg)
        if game_num < 1 or game_num > len(games):
            print(f"Invalid game number. Range: 1-{len(games)}")
            sys.exit(1)
        # For single game, remove any old result for this order first
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE) as f:
                lines = [l for l in f if json.loads(l.strip()).get("order") != game_num]
            with open(RESULTS_FILE, "w") as f:
                f.writelines(lines)
        run_single_game(games[game_num - 1])
    else:
        print(f"Unknown argument: {arg}")

if __name__ == "__main__":
    main()