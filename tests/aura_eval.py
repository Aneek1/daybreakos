#!/usr/bin/env python3
"""Evaluate Aura's language model on tests/aura_eval_cases.jsonl.

Needs a running llama-server (see Task 3 of docs/superpowers/plans/2026-09-15-aura-eval-and-safety.md).

  python tests/aura_eval.py --model-name llama-3.2-1b-q4km --model-file PATH --decoding free
  python tests/aura_eval.py --summary [--markdown]
"""
import argparse, hashlib, json, os, platform, subprocess, sys, time, urllib.parse, urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "tests" / "aura_eval_cases.jsonl"
RESULTS_DIR = ROOT / "tests" / "results"
FAKE_STATUS = {"battery": {"percent": 80, "status": "Discharging"}, "brightness": 50,
               "net": True, "os": "DaybreakOS"}


def load_cases(path=CASES_PATH):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _norm(value):
    return " ".join(str(value).lower().split())


def args_match(expected, actual):
    """open_app names compare case- and whitespace-insensitively; percents as integers."""
    for key, want in expected.items():
        got = actual.get(key)
        if key == "percent":
            try:
                if int(got) != int(want):
                    return False
            except (TypeError, ValueError):
                return False
        elif got is None or _norm(got) != _norm(want):
            return False
    return True


def valid_response_json(llm, raw):
    """True if the output holds a JSON object shaped like Aura's response (reply and/or
    tool_calls), whether or not it calls a tool."""
    for candidate in llm._json_candidates(raw or ""):
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(obj, dict) and ("tool_calls" in obj or "reply" in obj):
            return True
    return False


SYSTEM_WORDS = ("battery", "uptime", "network", "mbps", "brightness", "cpu", "memory")


def states_system_facts(reply, tool_calls):
    """True if a reply quotes numbers about the machine although the model called no tool. A heuristic:
    it catches invented readings such as 'Battery: 92%', and can also flag harmless replies.
    Pass the model's own reply and tool calls, not ask()'s: its fallback fills bad replies from status."""
    text = (reply or "").lower()
    return not tool_calls and any(ch.isdigit() for ch in text) and any(word in text for word in SYSTEM_WORDS)


def evaluate_case(llm, tools, case, call, clock=time.perf_counter):
    """Score one case at model level (raw output) and pipeline level (ask(), nothing really runs).

    `call(system, user, **kw)` returns the model's raw text, or None on failure."""
    schema_on = getattr(llm, "schema_enabled", lambda: False)()
    started = clock()
    if schema_on:
        schema = llm.response_schema(tools)
        system, user = llm.build_prompt(tools, case["say"], schema_mode=True)
        raw = call(system, user, schema=schema)
    else:
        system, user = llm.build_prompt(tools, case["say"])
        raw = call(system, user)
    latency_ms = (clock() - started) * 1000

    parsed = llm.parse_model_output(raw) if raw is not None else {"reply": "", "tool_calls": []}
    first = parsed["tool_calls"][0] if parsed["tool_calls"] else None

    executors = {t["name"]: (lambda args, name=t["name"]: f"(eval) {name}") for t in tools}
    real_call = llm.call_llama
    llm.call_llama = lambda system, user, **kw: raw
    try:
        out = llm.ask(case["say"], executors=executors, status=FAKE_STATUS, tools=tools)
    finally:
        llm.call_llama = real_call

    row = {
        "say": case["say"], "kind": case["kind"], "expect": case["expect"],
        "raw": raw, "latency_ms": round(latency_ms, 1), "server_error": raw is None,
        "model_cmd": first["cmd"] if first else None,
        "model_args": first["args"] if first else None,
        "pipeline_cmd": out["actions"][0]["cmd"] if out["actions"] else None,
        "reply": out["a"], "bad_reply": llm._reply_is_bad(out["a"]),
        "system_facts_without_tool": states_system_facts(parsed["reply"], parsed["tool_calls"]),
    }
    if case["kind"] == "tool":
        row["model_correct"] = row["model_cmd"] == case["expect"]
        row["pipeline_correct"] = row["pipeline_cmd"] == case["expect"]
        row["valid_response_json"] = valid_response_json(llm, raw)
        if "args" in case:
            row["args_correct"] = row["model_correct"] and args_match(case["args"], row["model_args"] or {})
    else:
        row["model_false_action"] = row["model_cmd"] is not None
        row["pipeline_false_action"] = row["pipeline_cmd"] is not None
    return row


def _rate(rows, key):
    # A server error says nothing about the model, so those rows count neither way.
    values = [bool(r[key]) for r in rows if key in r and not r["server_error"]]
    count = sum(values)
    return {"count": count, "total": len(values), "rate": round(count / len(values), 4) if values else None}


def _percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    # nearest rank, rounding halves up (round() would send 0.5 to 0)
    return ordered[min(len(ordered) - 1, int(pct / 100 * (len(ordered) - 1) + 0.5))]


def _by_tool(rows):
    tools = {}
    for r in rows:
        if r["kind"] != "tool" or r["server_error"]:
            continue
        entry = tools.setdefault(r["expect"], {"cases": 0, "model_correct": 0, "pipeline_correct": 0})
        entry["cases"] += 1
        entry["model_correct"] += int(bool(r["model_correct"]))
        entry["pipeline_correct"] += int(bool(r["pipeline_correct"]))
    return tools


def summarize(rows):
    latencies = [r["latency_ms"] for r in rows if not r["server_error"]]
    return {
        "cases": len(rows),
        "server_errors": sum(1 for r in rows if r["server_error"]),
        "tool_accuracy_model": _rate(rows, "model_correct"),
        "tool_accuracy_pipeline": _rate(rows, "pipeline_correct"),
        "args_accuracy_model": _rate(rows, "args_correct"),
        "false_action_model": _rate(rows, "model_false_action"),
        "false_action_pipeline": _rate(rows, "pipeline_false_action"),
        "valid_response_json_on_tool_cases": _rate(rows, "valid_response_json"),
        "bad_reply": _rate(rows, "bad_reply"),
        "system_facts_without_tool": _rate(rows, "system_facts_without_tool"),
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
        # _ACTION_CUE drops a call when the request has no action word; count correct calls it dropped
        "gate_dropped_correct_calls": sum(
            1 for r in rows if r.get("model_correct") and not r.get("pipeline_correct")),
        "by_tool": _by_tool(rows),
    }


HEADER = ["model", "decoding", "date", "tool acc (model)", "tool acc (pipeline)", "args acc",
          "false action (model)", "false action (pipeline)", "valid response JSON", "bad reply", "system facts, no tool", "p50 ms",
          "p95 ms"]
NO_METRIC = {"count": 0, "total": 0, "rate": None}  # results recorded before a metric existed


def _pct(metric):
    if metric["rate"] is None:
        return "-"
    return f"{100 * metric['rate']:.1f}% ({metric['count']}/{metric['total']})"


def _ms(value):
    return "-" if value is None else f"{value:.0f}"


def format_table(results, markdown):
    if not results:
        return "no results"
    rows = []
    for result in results:
        meta, m = result["meta"], result["metrics"]
        rows.append([meta["model_name"], meta["decoding"], meta["date"],
                     _pct(m["tool_accuracy_model"]), _pct(m["tool_accuracy_pipeline"]),
                     _pct(m["args_accuracy_model"]), _pct(m["false_action_model"]),
                     _pct(m["false_action_pipeline"]), _pct(m["valid_response_json_on_tool_cases"]),
                     _pct(m["bad_reply"]), _pct(m.get("system_facts_without_tool", NO_METRIC)),
                     _ms(m["latency_ms_p50"]), _ms(m["latency_ms_p95"])])
    if markdown:
        lines = ["| " + " | ".join(HEADER) + " |", "|" + "---|" * len(HEADER)]
        lines += ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join(lines)
    widths = [max(len(HEADER[i]), *(len(row[i]) for row in rows)) for i in range(len(HEADER))]
    fmt = "  ".join("{:<%d}" % w for w in widths)
    return "\n".join([fmt.format(*HEADER)] + [fmt.format(*row) for row in rows])


TOOL_HEADER = ["model", "decoding", "tool", "cases", "model correct", "pipeline correct"]


def format_tool_table(results):
    lines = ["| " + " | ".join(TOOL_HEADER) + " |", "|" + "---|" * len(TOOL_HEADER)]
    for result in results:
        meta = result["meta"]
        for tool, e in sorted(result["metrics"].get("by_tool", {}).items()):
            lines.append(f"| {meta['model_name']} | {meta['decoding']} | {tool} | {e['cases']} "
                         f"| {e['model_correct']} | {e['pipeline_correct']} |")
    return "\n".join(lines) if len(lines) > 2 else "no per-tool results"


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def health_url(chat_url):
    parts = urllib.parse.urlsplit(chat_url)
    return f"{parts.scheme}://{parts.netloc}/health"


def server_ready(chat_url):
    try:
        with urllib.request.urlopen(health_url(chat_url), timeout=5) as response:
            return response.status == 200
    except OSError:
        return False


def results_problem(metrics, out_path):
    """Why a finished run must not be saved, or None."""
    if metrics["server_errors"]:
        return (f"{metrics['server_errors']} of {metrics['cases']} requests failed; check the "
                "llama-server log and rerun (not writing a results file)")
    if out_path.exists():
        return f"{out_path.name} already exists; delete it deliberately or use a different --model-name"
    return None


def run(args):
    sys.path.insert(0, str(Path(args.shell_dir).resolve()))
    os.environ["AURA_LLM_SCHEMA"] = "1" if args.decoding == "schema" else "0"
    import aura_llm

    if args.decoding == "schema" and not hasattr(aura_llm, "schema_enabled"):
        sys.exit("this aura_llm.py has no schema mode; use --decoding free")
    if not server_ready(aura_llm.LLAMA_URL):
        sys.exit(f"llama-server is not answering at {aura_llm.LLAMA_URL}; start it first")

    tools = aura_llm.load_tools()
    cases = load_cases()[: args.limit] if args.limit else load_cases()
    rows = []
    for number, case in enumerate(cases, start=1):
        rows.append(evaluate_case(aura_llm, tools, case, aura_llm.call_llama))
        print(f"[{number}/{len(cases)}] {case['kind']:8} {case['say'][:40]:40} -> {rows[-1]['model_cmd']}",
              flush=True)

    metrics = summarize(rows)
    result = {
        "meta": {
            "date": date.today().isoformat(), "model_name": args.model_name,
            "model_file": Path(args.model_file).name, "model_sha256": sha256_file(args.model_file),
            "decoding": args.decoding, "llama_cpp": args.llama_tag, "limit": args.limit,
            "git_commit": _git("rev-parse", "HEAD"),
            "shell_commit": _git("log", "-1", "--format=%H", "--", "shell", "config"),
            "host": {"platform": platform.platform(), "processor": platform.processor(),
                     "python": platform.python_version()},
            "llm_url": aura_llm.LLAMA_URL,
        },
        "metrics": metrics,
        "cases": rows,
    }
    if args.limit:
        print(format_table([result], markdown=False))
        print("(--limit run: not writing a results file)")
        return
    out = RESULTS_DIR / f"aura-eval-{result['meta']['date']}-{args.model_name}-{args.decoding}.json"
    problem = results_problem(metrics, out)
    if problem:
        print(format_table([result], markdown=False))
        sys.exit(problem)
    RESULTS_DIR.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out.relative_to(ROOT)}")
    print(format_table([result], markdown=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", action="store_true", help="print a table of all recorded results")
    parser.add_argument("--markdown", action="store_true", help="with --summary: markdown table")
    parser.add_argument("--model-name", help="short name used in the results file name")
    parser.add_argument("--model-file", help="path to the GGUF the server is running (hashed into the results)")
    parser.add_argument("--decoding", choices=["free", "schema"], default="free")
    parser.add_argument("--llama-tag", default="b4589")
    parser.add_argument("--shell-dir", default=str(ROOT / "shell"), help="where to import aura_llm from")
    parser.add_argument("--limit", type=int, default=0, help="smoke-test the first N cases without saving")
    args = parser.parse_args(argv)

    if args.summary:
        results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RESULTS_DIR.glob("aura-eval-*.json"))]
        print(format_table(results, markdown=args.markdown))
        if args.markdown and results:
            print()
            print(format_tool_table(results))
        return
    if not (args.model_name and args.model_file):
        parser.error("--model-name and --model-file are required unless --summary is given")
    run(args)


if __name__ == "__main__":
    main()
