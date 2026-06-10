# Gemma 4 local serving - Windows (NVIDIA GPU) via vLLM.
#
# Prereqs: Python 3.12 + CUDA-capable GPU. Install vLLM into your env first:
#     pip install vllm
# (vLLM is intentionally NOT in ml/requirements.txt - it is heavy and
#  platform/CUDA-specific. Install it only on the serving host.)
#
# Usage:
#     ./ml/serving/start_vllm.ps1                 # serves google/gemma-3n-E2B-it on :8080
#     ./ml/serving/start_vllm.ps1 -Variant e4b
#     ./ml/serving/start_vllm.ps1 -Model C:\models\gemma-ft  # finetuned/merged checkpoint
#
# After this, set in .env:   LLM_BACKEND=vllm   (or leave LLM_BACKEND=auto on Windows)
param(
    [string]$Variant = "e2b",
    [string]$Model   = "",
    [int]$Port       = 8080,
    # Optional LoRA adapter for finetuned serving: -LoraPath C:\models\lora-adapter
    [string]$LoraPath = ""
)

$ErrorActionPreference = "Stop"

if (-not $Model) {
    $Model = "google/gemma-3n-$($Variant.ToUpper())-it"
}

$vllmArgs = @(
    "serve", $Model,
    "--port", $Port,
    "--served-model-name", $Model,
    # Structured outputs (response_format: json_schema) require a guided-decoding backend.
    "--guided-decoding-backend", "xgrammar"
)

if ($LoraPath) {
    $vllmArgs += @("--enable-lora", "--lora-modules", "gemma-ft=$LoraPath")
    Write-Host "LoRA enabled: serving adapter 'gemma-ft' from $LoraPath"
    Write-Host "  -> set VLLM_MODEL=gemma-ft in .env to use the finetuned adapter"
}

Write-Host "Starting vLLM: $Model on http://localhost:$Port/v1"
Write-Host "  .env ->  LLM_BACKEND=vllm   GEMMA_MODEL_VARIANT=$Variant   VLLM_BASE_URL=http://localhost:$Port/v1"
Write-Host "  Verify (another shell): `$env:PYTHONPATH='.'; python ml/scripts/llm_healthcheck.py"

vllm @vllmArgs
