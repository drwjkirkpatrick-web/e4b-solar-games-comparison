# E4B vs Ornith — Solar Games Comparison

Head-to-head comparison of **Gemma 4 E4B QAT** (optimized settings) vs **Ornith-1.0-9B IQ3_M** on the 19-game HTML game prompt suite from the Solar-Powered LLM HTML Game Generation Facts Report.

## Results Summary (13 of 19 games completed)

| Metric | E4B QAT | Ornith IQ3_M |
|--------|---------|-------------|
| Completion rate | **13/13 (100%)** | 8/13 (62%) |
| Avg validation score | **100/100** | 85-95/100 |
| Avg generation speed | **17.1 tok/s** | 9.3 tok/s |
| Speed advantage | **1.85x faster** | baseline |
| Avg tokens per game | 8,795 | 8,010 |
| Avg code size | 29,465 chars / 849 lines / 27 functions | — |
| External dependencies | 1 game (@import fonts) | — |
| Duplicate functions | 1 game (checkers) | — |

**Key finding:** E4B completed 5 games Ornith could not finish (Checkers, Chess, Pac-Maze, Harbor Captain, Slam Arena) — all scoring 100/100.

## Per-Game Results

| # | Game | E4B tok | Orn tok | E4B time | E4B t/s | E4B ✓ | Orn ✓ |
|---|------|---------|---------|----------|---------|-------|-------|
| 1 | Tower Tycoon v2 | 5,711 | 5,739 | 5.5m | 17.4 | ✅ | ✅ |
| 2 | Neon Invaders | 8,866 | 7,369 | 8.6m | 17.2 | ✅ | ✅ |
| 3 | Stellar Assault v2 | 8,889 | 7,573 | 8.6m | 17.3 | ✅ | ✅ |
| 4 | Flippy the Chip | 10,519 | 7,941 | 10.3m | 17.1 | ✅ | ✅ |
| 5 | DS9 Defense | 8,522 | 8,558 | 8.2m | 17.2 | ✅ | ✅ |
| 6 | Grind City | 7,890 | 8,594 | 7.6m | 17.2 | ✅ | ✅ |
| 7 | Jungle Swing | 9,749 | 9,023 | 9.5m | 17.1 | ✅ | ✅ |
| 8 | Dr. Mario v2 | 8,724 | 9,446 | 8.4m | 17.2 | ✅ | ✅ |
| 9 | Checkers Duel | 9,036 | 7,295 | 8.8m | 17.2 | ✅ | ❌ |
| 10 | Chess Arena | 9,174 | 7,578 | 8.9m | 17.2 | ✅ | ❌ |
| 11 | Miss Pac-Maze v2 | 10,308 | 7,773 | 10.5m | 16.4 | ✅ | ❌ |
| 12 | Harbor Captain | 9,032 | 7,817 | 8.8m | 17.2 | ✅ | ❌ |
| 16 | Slam Arena v2 | 7,920 | 9,423 | 7.7m | 17.2 | ✅ | ❌ |

*Games 13-15, 17-19 not yet completed (harness instability — see Code Review below).*

## Code Quality Review

**12 of 13 games produce clean, self-contained HTML:**
- All well-formed (`</html>`, `</body>`, `</script>` present)
- All braces/parens/brackets balanced
- Zero external dependencies (no CDNs, no libraries) — 12/13
- All use canvas rendering + Web Audio API
- All have game loops (`requestAnimationFrame` or `setInterval`) — 12/13
- Zero TODO/FIXME markers
- No duplicate function definitions — 12/13

**Issues found in Checkers Duel (game 9):**
- Duplicate `executeMove` function (lines 639 + 916) — second overrides first
- Win condition never checked in active code path (dead code in first definition)
- `@import` Google Fonts (only external dependency in the set)
- Game can still end via stalemate detection in `cpuTurn()`

**Chess Arena (game 10)** — complex game Ornith failed on:
- Has pawn promotion, check/checkmate, stalemate detection
- Missing castling and en passant (advanced rules)
- Clean code, fully self-contained

## E4B Settings (Verified)

**Infrastructure** (21-config sweep, Sep 25 2026):
- KV cache: f16/f16 (4% faster than q4_0 on Gemma 4 sliding window)
- Batch: 512/512 (+7% prompt processing vs 64)
- Context: 32K, Flash attention on, 6 threads, `-np 1`

**Sampling** (51-test sweep, Sep 25 2026):
- temperature: 0.4 (sweet spot 0.4-0.6)
- top_k: 40, top_p: 0.95
- repeat_penalty: 1.0 (disabled) — **+9% speed**, no accuracy loss on HTML
- thinking: OFF (`/no_think`) — saves ~10% tokens, scores higher

**Launch command:**
```
GGML_CUDA_ENABLE_UNIFIED_MEMORY=1 llama-server \
  -m ~/models/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf \
  --alias gemma-4-e4b-qat --host 127.0.0.1 --port 8091 \
  -ngl 99 -c 32768 -ctk f16 -ctv f16 -b 512 -ub 512 \
  -fa on --jinja --fit off -np 1 -t 6 \
  --temp 0.4 --top-p 0.95 --top-k 40 --repeat-penalty 1.0
```

## Files

- `e4b-setup-guide.pdf` — 10-page complete setup guide with all settings, benchmarks, and harness architecture
- `outputs/` — 13 generated HTML game files (playable in browser)
- `results/comparison_results.jsonl` — raw comparison data (13 entries)
- `run_game_v2.py` — Python harness using curl subprocess (fallback)
- `run_remaining_games.sh` — Bash runner using curl directly (recommended)
- `parse_response.py` — Parses curl response JSON into result entries
- `gen_requests.py` — Generates request JSON files from test_config.json

## Test Methodology

- Single-shot API calls only (no Serena, no MCP, no multi-turn)
- Same methodology as Ornith solar games tests for apples-to-apples comparison
- Server restarted between each game (KV cache accumulation crash prevention)
- `setsid` for server launch (fully detached, no timeout)
- `curl` as separate process writing to file (survives harness death)
- `max_tokens=20000`, HTTP timeout 7200s
- HTML validated for: DOCTYPE, closing tags, body, script, canvas, balanced braces/parens

See `e4b-setup-guide.pdf` for full setup instructions, OOM prevention rules, and harness architecture details.