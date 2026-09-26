#!/usr/bin/env python3
"""Parse a curl response file and append result to results JSONL."""
import json, re, os, sys

order = int(sys.argv[1])
name = sys.argv[2]
resp_file = sys.argv[3]
elapsed = float(sys.argv[4])
results_file = sys.argv[5]
outputs_dir = sys.argv[6]
prompt_file = sys.argv[7]
prior_tok = int(sys.argv[8])
prior_time = float(sys.argv[9])
prior_valid = sys.argv[10] == "YES"

# Load response
with open(resp_file) as f:
    data = json.load(f)

content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
usage = data.get("usage", {})
finish = data.get("choices", [{}])[0].get("finish_reason", "")
comp_tok = usage.get("completion_tokens", 0)

# Extract HTML
def extract_html(content):
    m = re.search(r'```html?\s*\n(.*?)```', content, re.DOTALL | re.IGNORECASE)
    if m: return m.group(1).strip()
    m = re.search(r'(<!DOCTYPE|<html).*', content, re.DOTALL | re.IGNORECASE)
    if m: return m.group(0).strip()
    return content.strip()

html = extract_html(content)

# Validate
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
score = (sum(checks.values()) / len(checks)) * 100
lines = html.count("\n") + 1
functions = len(re.findall(r"function\s+\w+|=>\s*{|:\s*function", html))

# Save HTML
output_file = os.path.join(outputs_dir, f"{order:02d}_{name}.html")
with open(output_file, "w") as f:
    f.write(html)

tps = comp_tok / elapsed if elapsed > 0 and comp_tok > 0 else 0

result = {
    "order": order,
    "game": name,
    "prompt_chars": os.path.getsize(prompt_file),
    "prior_model": "Ornith-1.0-9B IQ3_M",
    "prior_tokens": prior_tok,
    "prior_time_s": prior_time,
    "prior_valid": prior_valid,
    "e4b_model": "Gemma 4 E4B QAT",
    "e4b_settings": {"temperature": 0.4, "top_k": 40, "top_p": 0.95, "repeat_penalty": 1.0, "max_tokens": 20000, "thinking": False},
    "timestamp": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
    "completion_tokens": comp_tok,
    "prompt_tokens": usage.get("prompt_tokens", 0),
    "total_tokens": usage.get("total_tokens", 0),
    "elapsed": elapsed,
    "tps": tps,
    "finish_reason": finish,
    "html_chars": len(html),
    "validation": {"checks": checks, "score": score, "passed": sum(checks.values()), "total": 8, "lines": lines, "functions": functions, "chars": len(html)},
    "is_complete": checks["not_truncated"],
    "output_file": output_file,
}

with open(results_file, "a") as f:
    f.write(json.dumps(result) + "\n")

print(f"  RESULT: E4B={comp_tok} tok, {elapsed:.0f}s, {tps:.1f} tok/s, score={score:.0f}, complete={checks['not_truncated']}")
print(f"  HTML: {len(html)} chars, {lines} lines, {functions} functions")
print(f"  Ornith: {prior_tok} tok, valid={prior_valid}")