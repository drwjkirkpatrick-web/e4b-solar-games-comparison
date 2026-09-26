#!/bin/bash
# run_remaining_games.sh — runs games 13-19 one at a time
# Each game: start server (setsid), send curl, wait for response file, parse, stop server
# Survives independently — no Python harness that can die

CONFIG="/home/walker/projects/ornith-q4km-retest/test_config.json"
PROJECT="/home/walker/projects/e4b-solar-games-comparison"
RESULTS="$PROJECT/results/comparison_results.jsonl"
LOGS="$PROJECT/logs"
OUTPUTS="$PROJECT/outputs"
MODEL="/home/walker/models/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf"
SERVER="/home/walker/llama.cpp/build/bin/llama-server"
PORT=8091

export GGML_CUDA_ENABLE_UNIFIED_MEMORY=1

run_game() {
    local ORDER=$1
    local NAME=$2
    local PROMPT_FILE=$3
    local PRIOR_TOK=$4
    local PRIOR_TIME=$5
    local PRIOR_VALID=$6

    echo ""
    echo "======================================================================"
    echo "GAME $ORDER/19: $NAME"
    echo "  Prior Ornith: $PRIOR_TOK tok, ${PRIOR_TIME}s, valid=$PRIOR_VALID"
    echo "======================================================================"

    # Kill any existing server
    pkill -9 -f llama-server 2>/dev/null
    sleep 3
    sync

    # Start server via setsid
    echo "  Starting E4B server..."
    setsid $SERVER \
        -m $MODEL --alias gemma-4-e4b-qat \
        --host 127.0.0.1 --port $PORT \
        -ngl 99 -c 32768 -ctk f16 -ctv f16 \
        -b 512 -ub 512 -fa on --jinja --fit off -np 1 -t 6 \
        --temp 0.4 --top-p 0.95 --top-k 40 --repeat-penalty 1.0 \
        > "$LOGS/server_${NAME}.log" 2>&1 &

    # Wait for server
    for i in $(seq 1 90); do
        sleep 2
        if curl -s --connect-timeout 5 "http://127.0.0.1:$PORT/v1/models" | grep -q "gemma"; then
            echo "  Server ready (${i}x2s)"
            break
        fi
    done

    # Delete any stale response file first
    rm -f "$LOGS/response_${NAME}.json"
    
    # Send request via curl (blocks until response)
    echo "  Sending prompt via curl (max_tokens=20000)..."
    local T0=$(date +%s)
    curl -s -S --max-time 7200 --connect-timeout 30 \
        -X POST "http://127.0.0.1:$PORT/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d "@$PROMPT_FILE" \
        -o "$LOGS/response_${NAME}.json" 2>&1
    local CURL_EXIT=$?
    local T1=$(date +%s)
    local ELAPSED=$((T1 - T0))

    if [ $CURL_EXIT -ne 0 ]; then
        echo "  ERROR: curl exit $CURL_EXIT"
        echo "{\"order\":$ORDER,\"game\":\"$NAME\",\"error\":\"curl exit $CURL_EXIT\",\"elapsed\":$ELAPSED}" >> "$RESULTS"
    else
        echo "  curl completed in ${ELAPSED}s, parsing response..."
        # Parse with Python (quick, no long-running process)
        python3 "$PROJECT/parse_response.py" "$ORDER" "$NAME" "$LOGS/response_${NAME}.json" "$ELAPSED" "$RESULTS" "$OUTPUTS" "$PROMPT_FILE" "$PRIOR_TOK" "$PRIOR_TIME" "$PRIOR_VALID"
    fi

    # Stop server
    echo "  Stopping server..."
    pkill -9 -f llama-server 2>/dev/null
    sleep 3
    sync
}

echo "Starting remaining games (13-19)..."

# Generate request files for games 13-19 using Python
python3 "$PROJECT/gen_requests.py" 13 19

# Run each game
for ORDER in 13 14 15 16 17 18 19; do
    # Read game info from the generated meta file
    META="$LOGS/meta_${ORDER}.txt"
    if [ ! -f "$META" ]; then
        echo "  Skipping game $ORDER — no meta file"
        continue
    fi
    source "$META"
    run_game "$ORDER" "$GAME_NAME" "$LOGS/request_${GAME_NAME}.json" "$PRIOR_TOK" "$PRIOR_TIME" "$PRIOR_VALID"
    sleep 5
done

echo ""
echo "All remaining games complete. Printing summary..."
python3 "$PROJECT/run_game_v2.py" summary