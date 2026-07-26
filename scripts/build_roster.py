import json, subprocess, urllib.request, urllib.error, time, collections

token = subprocess.run(["gh","auth","token"],capture_output=True,text=True).stdout.strip()

REPOS = [
 # inference / serving
 "vllm-project/vllm","ggml-org/llama.cpp","huggingface/text-generation-inference",
 "ollama/ollama","sgl-project/sglang","InternLM/lmdeploy",
 # training / core frameworks
 "pytorch/pytorch","huggingface/transformers","huggingface/peft","huggingface/accelerate",
 "huggingface/diffusers","huggingface/datasets","huggingface/tokenizers",
 "microsoft/DeepSpeed","NVIDIA/Megatron-LM","unslothai/unsloth",
 "axolotl-ai-cloud/axolotl","hiyouga/LLaMA-Factory",
 # agents
 "langchain-ai/langchain","langchain-ai/langgraph","run-llama/llama_index",
 "crewAIInc/crewAI","microsoft/autogen","geekan/MetaGPT","Significant-Gravitas/AutoGPT",
 # apps / tooling
 "open-webui/open-webui","lm-sys/FastChat","oobabooga/text-generation-webui",
 "comfyanonymous/ComfyUI","AUTOMATIC1111/stable-diffusion-webui","invoke-ai/InvokeAI",
 # vector / RAG
 "chroma-core/chroma","qdrant/qdrant","weaviate/weaviate","milvus-io/milvus",
 "facebookresearch/faiss",
 # SDKs
 "openai/openai-python","anthropics/anthropic-sdk-python",
 # eval / observability
 "EleutherAI/lm-evaluation-harness","confident-ai/deepeval","Arize-ai/phoenix",
 # ML infra / data
 "ray-project/ray","mlflow/mlflow","wandb/wandb","gradio-app/gradio",
 "scikit-learn/scikit-learn","numpy/numpy",
 # speech / vision
 "openai/whisper","ultralytics/ultralytics","facebookresearch/segment-anything",
]

def get(url):
    req = urllib.request.Request(url, headers={"Authorization":f"Bearer {token}",
        "User-Agent":"hotin-roster","Accept":"application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception as e:
        return None, str(e)

people = collections.defaultdict(set)
commits = collections.Counter()
ok, failed = 0, []
for repo in REPOS:
    data, err = get(f"https://api.github.com/repos/{repo}/contributors?per_page=100")
    if not isinstance(data, list):
        failed.append((repo, err)); continue
    ok += 1
    for c in data:
        if c.get("type") != "User":
            continue
        login = c.get("login","")
        if not login or login.endswith("[bot]") or login.lower().endswith("-bot"):
            continue
        people[login].add(repo)
        commits[login] += int(c.get("contributions") or 0)
    time.sleep(0.15)

tier2 = {k:v for k,v in people.items() if len(v) >= 2}
tier3 = {k:v for k,v in people.items() if len(v) >= 3}
out = {
 "repos_ok": ok, "repos_failed": failed,
 "raw_unique": len(people),
 "tier_2plus": sorted(tier2, key=lambda k: (-len(people[k]), -commits[k])),
 "tier_3plus": sorted(tier3, key=lambda k: (-len(people[k]), -commits[k])),
 "commits": dict(commits),
 "repo_counts": {k: len(v) for k,v in people.items()},
}
json.dump(out, open("roster_raw.json","w"))
print("repos queried OK:", ok, "| failed:", failed)
print("RAW unique humans:", len(people))
print("tier 2+ repos:", len(tier2))
print("tier 3+ repos:", len(tier3))
print("top 25 by breadth:", out["tier_2plus"][:25])
