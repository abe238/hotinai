#!/usr/bin/env python3
"""Regenerate the CLI's default insider roster from the GitHub API.

The shipped roster in `src/hotin/sources/_roster_data.py` was produced by this
script. Nothing about it is privileged: point it at whatever repositories you
care about, pick a commit threshold, and you get your own roster.

    GITHUB_TOKEN=... python3 scripts/build_roster.py            # print a summary
    GITHUB_TOKEN=... python3 scripts/build_roster.py --write    # rewrite _roster_data.py
    GITHUB_TOKEN=... python3 scripts/build_roster.py --min-commits 500

Only the standard library is used, matching the package's zero-dependency rule.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
import urllib.error
import urllib.request

# The surveyed set: major open-source AI projects across inference, training,
# agents, tooling, vector stores, eval, ML infra, speech and vision. Edit freely.
REPOS = [
    "vllm-project/vllm", "ggml-org/llama.cpp", "huggingface/text-generation-inference",
    "ollama/ollama", "sgl-project/sglang", "InternLM/lmdeploy",
    "pytorch/pytorch", "huggingface/transformers", "huggingface/peft",
    "huggingface/accelerate", "huggingface/diffusers", "huggingface/datasets",
    "huggingface/tokenizers", "microsoft/DeepSpeed", "NVIDIA/Megatron-LM",
    "unslothai/unsloth", "axolotl-ai-cloud/axolotl", "hiyouga/LLaMA-Factory",
    "langchain-ai/langchain", "langchain-ai/langgraph", "run-llama/llama_index",
    "crewAIInc/crewAI", "microsoft/autogen", "geekan/MetaGPT",
    "Significant-Gravitas/AutoGPT", "open-webui/open-webui", "lm-sys/FastChat",
    "oobabooga/text-generation-webui", "comfyanonymous/ComfyUI",
    "AUTOMATIC1111/stable-diffusion-webui", "invoke-ai/InvokeAI",
    "chroma-core/chroma", "qdrant/qdrant", "weaviate/weaviate", "milvus-io/milvus",
    "facebookresearch/faiss", "openai/openai-python", "anthropics/anthropic-sdk-python",
    "EleutherAI/lm-evaluation-harness", "confident-ai/deepeval", "Arize-ai/phoenix",
    "ray-project/ray", "mlflow/mlflow", "wandb/wandb", "gradio-app/gradio",
    "scikit-learn/scikit-learn", "numpy/numpy", "openai/whisper",
    "ultralytics/ultralytics", "facebookresearch/segment-anything",
]

API = "https://api.github.com"


def _get(url: str, token: str):
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer {}".format(token),
        "Accept": "application/vnd.github+json",
        "User-Agent": "hotin-build-roster",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8", "replace")), None
    except urllib.error.HTTPError as exc:
        return None, exc.code
    except Exception as exc:  # noqa: BLE001 - report and continue to the next repo
        return None, str(exc)


def collect(repos, token):
    """Return (commits_by_login, repos_by_login, failures)."""
    commits = collections.Counter()
    repos_seen = collections.defaultdict(set)
    failures = []
    for repo in repos:
        data, err = _get("{}/repos/{}/contributors?per_page=100".format(API, repo), token)
        if not isinstance(data, list):
            failures.append((repo, err))
            continue
        for entry in data:
            if entry.get("type") != "User":
                continue
            login = entry.get("login") or ""
            if not login or login.endswith("[bot]") or login.lower().endswith("-bot"):
                continue
            commits[login] += int(entry.get("contributions") or 0)
            repos_seen[login].add(repo)
        time.sleep(0.15)
    return commits, repos_seen, failures


def render(names):
    def block(items, indent="    "):
        line, out = indent, []
        for name in items:
            piece = '"%s", ' % name
            if len(line) + len(piece) > 88:
                out.append(line.rstrip())
                line = indent
            line += piece
        if line.strip():
            out.append(line.rstrip())
        return "\n".join(out)
    return block(names)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-commits", type=int, default=250,
                        help="commit-depth threshold (default: 250)")
    parser.add_argument("--write", action="store_true",
                        help="rewrite src/hotin/sources/_roster_data.py")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("GITHUB_TOKEN is required (unauthenticated calls are limited to 60/hr)",
              file=sys.stderr)
        return 2

    commits, repos_seen, failures = collect(REPOS, token)
    if failures:
        print("repos that could not be read: {}".format(failures), file=sys.stderr)
    names = sorted([n for n, c in commits.items() if c >= args.min_commits],
                   key=lambda n: (-commits[n], n))

    print("surveyed repos     : {}/{}".format(len(REPOS) - len(failures), len(REPOS)))
    print("unique humans      : {}".format(len(commits)))
    print(">= {:<4} commits    : {}".format(args.min_commits, len(names)))
    print("est. calls/poll    : ~{}".format(len(names)))
    if not args.write:
        print("\n(pass --write to rewrite _roster_data.py)")
        return 0

    target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "src", "hotin", "sources", "_roster_data.py")
    with open(target, "r", encoding="utf-8") as handle:
        current = handle.read()
    head, sep, _ = current.partition("TOP_CONTRIBUTORS = (")
    if not sep:
        print("could not find TOP_CONTRIBUTORS in {}".format(target), file=sys.stderr)
        return 1
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(head + "TOP_CONTRIBUTORS = (\n" + render(names)
                     + "\n)\n\nROSTER = TOP_CONTRIBUTORS\n")
    print("\nwrote {} ({} handles)".format(target, len(names)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
