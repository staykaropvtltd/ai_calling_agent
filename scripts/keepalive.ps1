# ============================================================
# Staykaro — Supabase Keep-Alive Script
# Runs every 5 minutes via Windows Task Scheduler.
# Prevents Supabase free-tier from pausing after 1 week idle.
# ============================================================

$API_BASE   = "http://localhost"
$USERNAME   = "admin"
$PASSWORD   = "calling_agent_2026"
$MAX_RETRY  = 3
$LOG_FILE   = "$PSScriptRoot\keepalive.log"
$TIMESTAMP  = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $line = "[$TIMESTAMP] [$Level] $Message"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

# ── Rotate log file if it exceeds 1 MB ────────────────────────────────────────
if (Test-Path $LOG_FILE) {
    $size = (Get-Item $LOG_FILE).Length
    if ($size -gt 1MB) {
        Rename-Item $LOG_FILE "$PSScriptRoot\keepalive.log.bak" -Force
        Write-Log "Log rotated (was $([math]::Round($size/1KB)) KB)"
    }
}

# ── Step 1: Get JWT token ──────────────────────────────────────────────────────
Write-Log "Starting keep-alive ping"

$token = $null
for ($i = 1; $i -le $MAX_RETRY; $i++) {
    try {
        $resp = Invoke-RestMethod `
            -Method POST `
            -Uri "$API_BASE/api/auth/token" `
            -ContentType "application/x-www-form-urlencoded" `
            -Body "username=$USERNAME&password=$PASSWORD" `
            -TimeoutSec 10 `
            -ErrorAction Stop

        $token = $resp.access_token
        Write-Log "Auth OK — token obtained (attempt $i)"
        break
    } catch {
        Write-Log "Auth attempt $i failed: $($_.Exception.Message)" "WARN"
        if ($i -lt $MAX_RETRY) { Start-Sleep -Seconds 5 }
    }
}

if (-not $token) {
    Write-Log "Auth failed after $MAX_RETRY attempts — aborting" "ERROR"
    exit 1
}

# ── Step 2: Ping /keepalive — runs SELECT 1 against Supabase ──────────────────
for ($i = 1; $i -le $MAX_RETRY; $i++) {
    try {
        $ping = Invoke-RestMethod `
            -Method GET `
            -Uri "$API_BASE/api/keepalive" `
            -Headers @{ Authorization = "Bearer $token" } `
            -TimeoutSec 15 `
            -ErrorAction Stop

        Write-Log "Keepalive OK — db=$($ping.db) redis=$($ping.redis)"
        if ($ping.db -ne "ok") {
            Write-Log "DB is unreachable — Supabase may be paused or pooler not connected" "WARN"
        }
        break
    } catch {
        Write-Log "Keepalive attempt $i failed: $($_.Exception.Message)" "WARN"
        if ($i -lt $MAX_RETRY) { Start-Sleep -Seconds 5 }
    }
}

Write-Log "Done"
