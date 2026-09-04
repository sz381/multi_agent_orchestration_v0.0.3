#!/usr/bin/env bash
# cache_hit_rate.sh —— Calculate the hit rate of the LLM prompt cache by analyzing the log records.
# usage: ./scripts/cache_hit_rate.sh fname=<name_of_log_file> [mode=<1|2|3|4>]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOGS_DIR="$PROJECT_ROOT/logs"

usage() {
    cat <<'EOF'
Usage: ./scripts/cache_hit_rate.sh fname=<name_of_log_file> [mode=<1|2|3|4>]

Parameters:
  fname   Log file under logs/ (or any path). The ".log" suffix is optional.
  mode    1  Simple average of per-call cache_hit_rate (default)
          2  Token-weighted hit rate: sum(cache_read_tokens) / sum(input_tokens)
          3  Per-agent breakdown (calls, avg, weighted, tokens)
          4  Token totals summary

Examples:
  ./scripts/cache_hit_rate.sh fname=run_test_v003_n001 mode=1
  ./scripts/cache_hit_rate.sh fname=logs/run_test_v003_n001.log mode=3
EOF
}

fname=""
mode="1"

if [ "$#" -eq 0 ]; then
    usage
    exit 1
fi

for arg in "$@"; do
    case "$arg" in
        fname=*) fname="${arg#fname=}" ;;
        mode=*) mode="${arg#mode=}" ;;
        -h|--help) usage; exit 0 ;;
        *)
            echo "Error: unknown argument '$arg'; expected key=value pairs." >&2
            usage
            exit 1
            ;;
    esac
done

if [ -z "$fname" ]; then
    echo "Error: missing required argument fname=<name_of_log_file>." >&2
    usage
    exit 1
fi

case "$mode" in
    1|2|3|4) ;;
    *) echo "Error: invalid mode '$mode' (expected 1, 2, 3 or 4)." >&2; exit 1 ;;
esac

log_path=""
for candidate in "$fname" "$fname.log" "$LOGS_DIR/$fname" "$LOGS_DIR/$fname.log"; do
    if [ -f "$candidate" ]; then
        log_path="$candidate"
        break
    fi
done

if [ -z "$log_path" ]; then
    echo "Error: log file not found: '$fname' (also tried '${fname}.log' and $LOGS_DIR)." >&2
    exit 1
fi

awk -v mode="$mode" '
/llm_token_usage/ {
    n_records++
    delete kv
    for (i = 1; i <= NF; i++) {
        pos = index($i, "=")
        if (pos > 0) kv[substr($i, 1, pos - 1)] = substr($i, pos + 1)
    }

    hit  = kv["cache_hit_rate"] + 0
    read = kv["cache_read_tokens"] + 0
    inp  = kv["input_tokens"] + 0
    crn  = kv["cache_creation_tokens"] + 0
    outp = kv["output_tokens"] + 0

    sum_hit += hit
    sum_read += read
    sum_inp += inp
    sum_crn += crn
    sum_outp += outp
    if (hit == 0) zero_calls++

    aid = kv["agent_id"]
    calls[aid]++
    hit_sum[aid] += hit
    read_sum[aid] += read
    inp_sum[aid] += inp
    outp_sum[aid] += outp
}
END {
    if (n_records == 0) {
        print "Error: no llm_token_usage records found in log." > "/dev/stderr"
        exit 1
    }

    if (mode == 1) {
        avg = sum_hit / n_records
        printf "count=%d, avg_cache_hit_rate=%.4f (%.2f%%)\n", n_records, avg, avg * 100
        if (n_records > zero_calls) {
            navg = sum_hit / (n_records - zero_calls)
            printf "count_nonzero=%d, avg_hit_rate_excl_zero=%.4f (%.2f%%)\n", n_records - zero_calls, navg, navg * 100
        } else {
            printf "count_nonzero=0 (all calls had zero cache hits)\n"
        }

    } else if (mode == 2) {
        wavg = sum_inp > 0 ? sum_read / sum_inp : 0
        printf "total_input_tokens=%d, total_cache_read_tokens=%d\n", sum_inp, sum_read
        printf "weighted_cache_hit_rate=%.4f (%.2f%%)\n", wavg, wavg * 100

    } else if (mode == 3) {
        n_agents = 0
        for (a in calls) keys[++n_agents] = a
        for (i = 1; i <= n_agents; i++) {
            for (j = i + 1; j <= n_agents; j++) {
                if (keys[j] < keys[i]) { t = keys[i]; keys[i] = keys[j]; keys[j] = t }
            }
        }

        printf "%-18s %5s %10s %14s %14s %14s %14s\n", "agent_id", "calls", "avg_hit", "weighted_hit", "input_tokens", "cache_read", "output_tokens"
        for (i = 1; i <= n_agents; i++) {
            a = keys[i]
            w = inp_sum[a] > 0 ? read_sum[a] / inp_sum[a] : 0
            printf "%-18s %5d %9.2f%% %13.2f%% %14d %14d %14d\n", a, calls[a], hit_sum[a] / calls[a] * 100, w * 100, inp_sum[a], read_sum[a], outp_sum[a]
        }

    } else {
        non_cached = sum_inp - sum_read - sum_crn
        printf "llm_calls=%d\n", n_records
        printf "input_tokens=%d (cache_read=%d, cache_creation=%d, non_cached=%d)\n", sum_inp, sum_read, sum_crn, non_cached
        printf "output_tokens=%d\n", sum_outp
    }
}
' "$log_path"
