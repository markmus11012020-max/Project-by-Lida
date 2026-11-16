param(
    [int]$Port = 8030
)

$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$stopped = New-Object System.Collections.Generic.List[int]

function Stop-ProjectProcess {
    param([int]$ProcessId)
    if ($ProcessId -and $ProcessId -ne $PID) {
        Stop-Process -Id $ProcessId -Force
        $stopped.Add($ProcessId)
    }
}

# 1. Stop uvicorn processes of this project (parent and direct workers).
$processes = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and
    $_.CommandLine -match "uvicorn" -and
    $_.CommandLine -match "app[.]main:app"
}
foreach ($process in $processes) {
    Stop-ProjectProcess -ProcessId ([int]$process.ProcessId)
}

Start-Sleep -Milliseconds 700

# 2. Fallback: find the listener and its multiprocessing children.
$listeners = @()
try {
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen
} catch {
    $listeners = @()
}

foreach ($listener in $listeners) {
    $listenerPid = [int]$listener.OwningProcess
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $listenerPid"
    $ownerName = if ($owner) { [string]$owner.Name } else { "unknown" }
    $ownerCommand = if ($owner) { [string]$owner.CommandLine } else { "" }
    $isOurs = $ownerCommand -match "uvicorn|app[.]main:app|multiprocessing"

    if ($owner -and $isOurs) {
        Stop-ProjectProcess -ProcessId $listenerPid
        continue
    }

    # uvicorn --reload keeps a spawn_main child whose parent PID is the
    # listener PID. If the parent is already gone, kill the child.
    $children = @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and
        $_.CommandLine -match "multiprocessing[.]spawn" -and
        $_.CommandLine -match "parent_pid=$listenerPid"
    })
    if ($children.Count -gt 0) {
        foreach ($child in $children) {
            Stop-ProjectProcess -ProcessId ([int]$child.ProcessId)
        }
        continue
    }

    if ($ownerName -eq "unknown") {
        Write-Warning "Port $Port is held by an unknown process $listenerPid. Stop it manually."
    } else {
        Write-Warning "Port $Port is busy with process $listenerPid ($ownerName). Stop it manually."
    }
    exit 1
}

# 3. Wait until the port is actually free.
for ($i = 0; $i -lt 10; $i++) {
    $remaining = @()
    try {
        $remaining = @(Get-NetTCPConnection -LocalPort $Port -State Listen)
    } catch {
        $remaining = @()
    }
    if ($remaining.Count -eq 0) {
        break
    }
    Start-Sleep -Milliseconds 300
}

$unique = $stopped | Sort-Object -Unique
if ($unique.Count -gt 0) {
    Write-Host "Stopped processes: $($unique -join ', ')"
} else {
    Write-Host "Old server not found."
}
exit 0
