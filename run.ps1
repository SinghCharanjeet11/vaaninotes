# Launch the VaaniNotes desktop UI at http://127.0.0.1:7860
Set-Location $PSScriptRoot
& (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") -m vaani @args
