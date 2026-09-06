# benchmarking/

## Python environment

This directory has its own venv at `benchmarking/venv`. Always invoke it by
its interpreter path rather than bare `python`/`pip` — each Bash/PowerShell
tool call is a fresh, non-persistent shell process, so a prior `activate`
does not carry over to the next command anyway. Calling the venv's own
executable is the only invocation that reliably uses the right environment
in both Git Bash and PowerShell:

```bash
# Git Bash
./venv/Scripts/python.exe script.py
./venv/Scripts/pip.exe install -r requirements.txt
```

```powershell
# PowerShell
.\venv\Scripts\python.exe script.py
.\venv\Scripts\pip.exe install -r requirements.txt
```

Do not rely on `source venv/Scripts/activate` / `venv\Scripts\Activate.ps1`
persisting across tool calls — it won't.
