<#
  VaaniNotes one-step setup.

  On a Snapdragon PC (Windows on ARM, native ARM64 Python 3.11-3.13):
    - installs onnxruntime-qnn (Hexagon NPU execution provider)
    - downloads Qualcomm AI Hub's Whisper-Small, precompiled for your chipset
  On any other PC:
    - installs PyTorch (CPU) so the same app runs with a CPU fallback

  Usage:  powershell -ExecutionPolicy Bypass -File setup.ps1 [-Chipset qualcomm-snapdragon-x-elite] [-WithCpuFallback]
#>
param(
    [string]$Chipset = "",
    [switch]$WithCpuFallback
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

Step "Checking Python"
$pyArch = python -c "import platform; print(platform.machine())"
$pyVer = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "Python $pyVer ($pyArch)"
$cpu = (Get-CimInstance Win32_Processor).Name
$isSnapdragon = $cpu -match "Snapdragon|Qualcomm|Oryon"
if ($isSnapdragon -and $pyArch -ne "ARM64") {
    Write-Warning "Snapdragon detected but Python is $pyArch (emulated). Install native ARM64 Python 3.11+ from python.org for NPU support."
}

Step "Creating virtual environment (.venv)"
if (-not (Test-Path .venv)) { python -m venv .venv }
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$useNpu = $isSnapdragon -and $pyArch -eq "ARM64"
if ($useNpu) {
    Step "Installing ONNX Runtime QNN (Hexagon NPU)"
    & $py -m pip install -r requirements-npu.txt --quiet
    if ($LASTEXITCODE -ne 0) { throw "onnxruntime-qnn install failed" }

    if (-not $Chipset) {
        if ($cpu -match "X2") { $Chipset = "qualcomm-snapdragon-x2-elite" }
        elseif ($cpu -match "X1P|X Plus") { $Chipset = "qualcomm-snapdragon-x-plus-8-core" }
        else { $Chipset = "qualcomm-snapdragon-x-elite" }
    }
    Step "Downloading AI Hub Whisper-Small (precompiled QNN ONNX, $Chipset)"
    & (Join-Path $PSScriptRoot ".venv\Scripts\qai-hub-models.exe") fetch whisper_small `
        -r precompiled_qnn_onnx -p float -c $Chipset -o models\whisper_small
    if ($LASTEXITCODE -ne 0) { throw "Model download failed" }
}

if (-not $useNpu -or $WithCpuFallback) {
    Step "Installing PyTorch (CPU fallback)"
    & $py -m pip install -r requirements-cpu.txt --quiet --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
    if ($LASTEXITCODE -ne 0) { Write-Warning "PyTorch install failed; CPU fallback unavailable." }
}

Step "Caching tokenizer / feature extractor for offline use"
& $py -c "import vaani; from transformers import WhisperConfig, WhisperFeatureExtractor, WhisperTokenizer as T; m='openai/whisper-small'; WhisperConfig.from_pretrained(m); WhisperFeatureExtractor.from_pretrained(m); T.from_pretrained(m); print('ok')"

Step "Hardware check"
& $py -c "from vaani import device; [print(f'{k}: {v}') for k, v in device.summary().items()]"

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Notes LLM on the NPU: install Qualcomm GenieX (https://geniex.aihub.qualcomm.com), then run:"
Write-Host "    geniex serve        # OpenAI-compatible server on http://127.0.0.1:18181"
Write-Host "Start the app:  .\run.ps1"
