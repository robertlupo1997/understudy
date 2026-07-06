# Gotchas — verified traps running Ornith-1.0 locally

## 1. The max_tokens / <think> trap
Ornith always opens a mandatory <think> block. Too-low max_tokens → thinking eats the
whole budget → EMPTY content with a benign finish_reason. Use max_tokens ≥ 8192 for
coding tasks and always check for empty output. (The worker defaults to 8192 and fails
loudly with exit 3.)

## 2. 35B over-reasoning spiral — and the fix
On hard tasks the 35B thinks past any budget; more tokens just buys more thinking.
Fix: pass reasoning_effort:"none" on Ollama's /v1 endpoint (chat_template_kwargs is
silently ignored). The worker auto-retries with thinking off (--no-think to force).
Caveat: no-think 35B emits code but can be wrong on the hardest tasks — decompose them.

## 3. Chat-template tool-calling bug (llama.cpp / LM Studio)
The shipped chat_template.jinja contains hard raise_exception assertions that break
runtimes that probe the template to auto-build a parser ("400 Unable to generate parser").
Fixes: (a) strip the two assertions (rendered output is byte-identical for valid input),
(b) --chat-template-file at runtime, (c) an Ollama Modelfile with PARSER/RENDERER.
Sources: HF discussion deepreinforce-ai/Ornith-1.0-35B #10; ollama/ollama#16988.
Our Ollama setup did NOT hit this (both models verified working).

## 4. Ollama cannot expert-offload the 35B
The 35B is a ~3B-active sparse MoE: it runs on an 8GB GPU via llama.cpp --n-cpu-moe
(experts in system RAM). Ollama runs it too (~7GB VRAM + ~19GB RAM) but cannot do
selective expert offload. --jinja is mandatory on llama.cpp or tool calls break.

## 5. bwrap sandbox prerequisites (Linux/WSL only)
The gate runs the repo's trusted steps inside bwrap. It is Linux/WSL only (macOS: roadmap).
The sandbox string ro-binds ~/.local/lib with --ro-bind-try, so a system-Python/venv
install (no ~/.local/lib) still works. bwrap must be installed (`apt install bubblewrap`).

## 6. "Self-improving" is training-time only
You get frozen weights. No online learning. Plan reviews accordingly.
