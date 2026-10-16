<#
.SYNOPSIS
  Keeps the local pipeline running: starts what is down, restarts what is stuck, tells you
  when data stops arriving, and closes the gaps an outage leaves behind.

.DESCRIPTION
  One pass per run; install_watchdog.ps1 schedules it every 2 minutes and at logon. Each pass:
    1. Postgres and Kafka are up (starts them if not).
    2. The eight pipeline processes are running and, for the two inference services, healthy.
    3. Each data stream is fresh (scripts/pipeline_status.py), and the hourly Neon sync ran.
    4. Once a day, re-pulls the last few days from the verified feeds and re-scores them, which
       is what closes the hole a stall or reboot leaves (the live PJM feed only ever returns
       the newest interval, so a missed stretch cannot be recovered live).
  Problems are written to the log, shown as a Windows notification, and, if WATCHDOG_NTFY_TOPIC
  is set in the repo's .env, pushed to your phone through ntfy.sh. Each problem alerts once,
  repeats every 3 hours while it lasts, and sends a recovery message when it clears.

.PARAMETER Status
  Report only. Starts nothing, restarts nothing, sends nothing.

.PARAMETER ForceHeal
  Run the gap heal now regardless of the time of day or when it last ran.

.PARAMETER DryRun
  Log what a pass would do instead of doing it. Alerts are logged, not sent.

.EXAMPLE
  powershell -File scripts\windows\watchdog.ps1 -Status
#>
[CmdletBinding()]
param(
    [switch]$Status,
    [switch]$DryRun,
    [switch]$ForceHeal
)

$ErrorActionPreference = 'Stop'

# ---- Configuration ---------------------------------------------------------------------
$Repo   = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$UserHome = $env:USERPROFILE
$PgDir  = Join-Path $UserHome 'pgportable\pgsql'
$PgData = Join-Path $UserHome 'pgportable\data'
$KafkaDir = Join-Path $UserHome 'kafkaportable\kafka_2.13-4.3.1'
$JavaExe  = Join-Path $UserHome 'javaportable\jdk-21.0.12.1+1-jre\bin\java.exe'
$Python   = Join-Path $Repo '.venv\Scripts\python.exe'
$LogDir   = Join-Path $UserHome 'pjm-logs'
$LogFile  = Join-Path $LogDir 'watchdog.log'
$StateFile = Join-Path $LogDir 'watchdog-state.json'

$KafkaPort = 9092
$PgPort = 5432
$RealertHours = 3
$MaxRestartsPerHour = 5

# Minutes a stream may go without a new row before it counts as stalled. Normal ages are
# PJM LMP a few minutes, EIA about 2 to 6 hours, PJM metered load 1 to 2 days (see
# scripts/pipeline_status.py).
$StaleMinutes = @{
    pjm_lmp        = 25
    pjm_lmp_scored = 40
    eia_demand     = 480
    eia_scored     = 540
    pjm_load       = 5760   # 4 days
}
$NeonMaxAgeHours = 2.5
$HealHourLocal = 7          # earliest local hour the daily gap-heal may run
$HealDays = 4

# Every process the pipeline needs. Metrics ports are distinct because the processes share
# one host (the code defaults them all to 9100).
$Services = @(
    @{ Name = 'eia-poller';        Match = 'ingestion\.eia_poller(\s|$)';           Run = '-m ingestion.eia_poller';           Metrics = 9111 },
    @{ Name = 'eia-consumer';      Match = 'ingestion\.eia_poller\.consumer';       Run = '-m ingestion.eia_poller.consumer';  Metrics = 9101 },
    @{ Name = 'pjm-poller';        Match = 'ingestion\.pjm_poller(\s|$)';           Run = '-m ingestion.pjm_poller';           Metrics = 9112 },
    @{ Name = 'pjm-consumer';      Match = 'ingestion\.pjm_poller\.consumer';       Run = '-m ingestion.pjm_poller.consumer';  Metrics = 9102 },
    @{ Name = 'pjm-load-poller';   Match = 'ingestion\.pjm_load_poller(\s|$)';      Run = '-m ingestion.pjm_load_poller';      Metrics = 9113 },
    @{ Name = 'pjm-load-consumer'; Match = 'ingestion\.pjm_load_poller\.consumer';  Run = '-m ingestion.pjm_load_poller.consumer'; Metrics = 9103 },
    @{ Name = 'eia-inference';     Match = 'inference\.eia_service:app';
       Run = '-m uvicorn inference.eia_service:app --host 127.0.0.1 --port 8000';  Metrics = 9121; Health = 'http://127.0.0.1:8000/health' },
    @{ Name = 'pjm-inference';     Match = 'inference\.pjm_service:app';
       Run = '-m uvicorn inference.pjm_service:app --host 127.0.0.1 --port 8001';  Metrics = 9122; Health = 'http://127.0.0.1:8001/health' }
)

# ---- Plumbing --------------------------------------------------------------------------
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }

function Write-Log([string]$Message) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    if ($Status -or $DryRun) { Write-Host $line; return }
    try {
        if ((Test-Path $LogFile) -and (Get-Item $LogFile).Length -gt 1MB) {
            Move-Item -Force $LogFile "$LogFile.1"
        }
        Add-Content -Path $LogFile -Value $line
    } catch { }
}

# A second pass starting while one is still working (a Kafka start can take a minute) must
# not race it.
$mutex = New-Object System.Threading.Mutex($false, 'Local\pa-grid-monitor-watchdog')
if (-not $mutex.WaitOne(0)) { exit 0 }

function Read-State {
    $empty = @{ active = @{}; counters = @{}; restarts = @{}; lastHeal = $null; lastLmpRestart = $null }
    if (-not (Test-Path $StateFile)) { return $empty }
    try {
        $raw = Get-Content $StateFile -Raw | ConvertFrom-Json
        $s = $empty
        foreach ($section in 'active', 'counters', 'restarts') {
            if ($raw.$section) { foreach ($p in $raw.$section.PSObject.Properties) { $s[$section][$p.Name] = $p.Value } }
        }
        $s.lastHeal = $raw.lastHeal
        $s.lastLmpRestart = $raw.lastLmpRestart
        return $s
    } catch { return $empty }
}
$State = Read-State
function Save-State {
    if ($Status -or $DryRun) { return }
    try { $State | ConvertTo-Json -Depth 6 | Set-Content -Path $StateFile -Encoding ASCII } catch { }
}

function Get-EnvFileValue([string]$Key) {
    $envFile = Join-Path $Repo '.env'
    if (-not (Test-Path $envFile)) { return $null }
    $m = Select-String -Path $envFile -Pattern "^\s*$Key\s*=\s*(.+?)\s*$" | Select-Object -First 1
    if ($m) { return $m.Matches[0].Groups[1].Value.Trim('"', "'") }
    return $null
}

function Send-Notification([string]$Title, [string]$Body) {
    if ($Status -or $DryRun) { return }
    try {
        [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
        $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $text = $xml.GetElementsByTagName('text')
        [void]$text.Item(0).AppendChild($xml.CreateTextNode($Title))
        [void]$text.Item(1).AppendChild($xml.CreateTextNode($Body))
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        $aumid = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($aumid).Show($toast)
    } catch { Write-Log "toast failed: $($_.Exception.Message)" }
    $topic = Get-EnvFileValue 'WATCHDOG_NTFY_TOPIC'
    if ($topic) {
        try {
            Invoke-RestMethod -Uri "https://ntfy.sh/$topic" -Method Post -Body $Body -Headers @{ Title = $Title } -TimeoutSec 15 | Out-Null
        } catch { Write-Log "ntfy failed: $($_.Exception.Message)" }
    }
}

function Test-Port([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        return ($task.Wait(1500) -and $client.Connected)
    } catch { return $false } finally { $client.Dispose() }
}

function Test-PgReady {
    & (Join-Path $PgDir 'bin\pg_isready.exe') -h 127.0.0.1 -p $PgPort -t 3 *> $null
    return ($LASTEXITCODE -eq 0)
}

# Processes are created through WMI so they are not children of the scheduled task, which
# Task Scheduler would otherwise tear down along with the task.
function Start-Detached([string]$CommandLine, [string]$WorkDir) {
    if ($DryRun) { Write-Log "DRYRUN would start: $CommandLine"; return $true }
    $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $CommandLine; CurrentDirectory = $WorkDir; ProcessStartupInformation = $startup }
    if ($r.ReturnValue -ne 0) { Write-Log "start failed (code $($r.ReturnValue)): $CommandLine" }
    return ($r.ReturnValue -eq 0)
}

# cmd.exe strips the outer pair of quotes after /c, which lets the inner command keep its own.
function New-ShellLine([string]$Inner) { return 'cmd.exe /c "' + $Inner + '"' }

function Find-Processes([string]$ImageLike, [string]$Pattern) {
    @(Get-CimInstance Win32_Process -Filter "Name LIKE '$ImageLike'" |
        Where-Object { $_.CommandLine -match $Pattern })
}

function Stop-Matching([string]$ImageLike, [string]$Pattern) {
    if ($DryRun) { Write-Log "DRYRUN would stop processes matching $Pattern"; return }
    foreach ($p in (Find-Processes $ImageLike $Pattern)) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch { }
    }
}

# ---- Problems and alerting -------------------------------------------------------------
$Problems = @{}   # key -> message, rebuilt every pass
function Add-Problem([string]$Key, [string]$Message) { $Problems[$Key] = $Message }

function Publish-Alerts {
    $now = Get-Date
    foreach ($key in $Problems.Keys) {
        $last = $State.active[$key]
        $due = $true
        if ($last) { $due = (($now - [datetime]$last).TotalHours -ge $RealertHours) }
        if ($due) {
            Write-Log "ALERT [$key] $($Problems[$key])"
            Send-Notification 'PA Grid Monitor: problem' $Problems[$key]
            $State.active[$key] = $now.ToString('o')
        }
    }
    foreach ($key in @($State.active.Keys)) {
        if (-not $Problems.ContainsKey($key)) {
            Write-Log "RECOVERED [$key]"
            Send-Notification 'PA Grid Monitor: recovered' "Problem cleared: $key"
            $State.active.Remove($key)
        }
    }
}

function Test-RestartAllowed([string]$Name) {
    $cutoff = (Get-Date).AddHours(-1)
    $recent = @()
    if ($State.restarts[$Name]) { $recent = @($State.restarts[$Name] | Where-Object { [datetime]$_ -gt $cutoff }) }
    $State.restarts[$Name] = $recent
    if ($recent.Count -ge $MaxRestartsPerHour) {
        Add-Problem "loop:$Name" "$Name keeps dying ($($recent.Count) restarts in the last hour). Check $LogDir\$Name.err.log."
        return $false
    }
    return $true
}
function Note-Restart([string]$Name) { $State.restarts[$Name] = @($State.restarts[$Name]) + (Get-Date).ToString('o') }

# ---- Report rows for -Status -----------------------------------------------------------
$Report = New-Object System.Collections.ArrayList
function Add-Report([string]$Item, [string]$State_, [string]$Detail) {
    [void]$Report.Add([pscustomobject]@{ Item = $Item; State = $State_; Detail = $Detail })
}

# ---- 1. Postgres -----------------------------------------------------------------------
$pgOk = Test-PgReady
if (-not $pgOk -and -not $Status) {
    Write-Log 'postgres is down, starting it'
    $line = '"{0}" start -D "{1}" -l "{2}"' -f (Join-Path $PgDir 'bin\pg_ctl.exe'), $PgData, (Join-Path $LogDir 'postgres.log')
    [void](Start-Detached $line $PgDir)
    for ($i = 0; $i -lt 20 -and -not $pgOk -and -not $DryRun; $i++) { Start-Sleep -Seconds 3; $pgOk = Test-PgReady }
}
if (-not $pgOk) { Add-Problem 'postgres' 'Postgres is not accepting connections and could not be started.' }
Add-Report 'postgres' ($(if ($pgOk) { 'ok' } else { 'DOWN' })) "port $PgPort"

# ---- 2. Kafka --------------------------------------------------------------------------
$kafkaOk = Test-Port $KafkaPort
$kafkaProc = @(Find-Processes 'java%' 'kafka\.Kafka')
if (-not $kafkaOk -and $kafkaProc.Count -gt 0) {
    # Running but not answering. Give it a few passes (startup is slow) before assuming a hang.
    $State.counters['kafkaBad'] = 1 + [int]$State.counters['kafkaBad']
    if ($State.counters['kafkaBad'] -ge 4 -and -not $Status) {
        Write-Log 'kafka process is up but has not answered for several passes, restarting it'
        Stop-Matching 'java%' 'kafka\.Kafka'
        $kafkaProc = @()
        $State.counters['kafkaBad'] = 0
    }
} else {
    $State.counters['kafkaBad'] = 0
}
if (-not $kafkaOk -and $kafkaProc.Count -eq 0 -and -not $Status) {
    Write-Log 'kafka is down, starting it'
    $inner = '"{0}" -Xmx1G -Xms512M "-Dkafka.logs.dir={1}\logs" "-Dlog4j2.configurationFile=file:{1}\config\log4j2.yaml" -cp "{1}\libs\*" kafka.Kafka "{1}\config\server-local.properties" >> "{2}" 2>> "{3}"' -f `
        $JavaExe, $KafkaDir, (Join-Path $LogDir 'kafka.out.log'), (Join-Path $LogDir 'kafka.err.log')
    [void](Start-Detached (New-ShellLine $inner) $KafkaDir)
    for ($i = 0; $i -lt 30 -and -not $kafkaOk -and -not $DryRun; $i++) { Start-Sleep -Seconds 3; $kafkaOk = Test-Port $KafkaPort }
}
if (-not $kafkaOk) { Add-Problem 'kafka' 'Kafka is not accepting connections.' }
Add-Report 'kafka' ($(if ($kafkaOk) { 'ok' } else { 'DOWN' })) "port $KafkaPort"

# ---- 3. Pipeline processes -------------------------------------------------------------
foreach ($svc in $Services) {
    $name = $svc.Name
    $procs = @(Find-Processes 'python%' $svc.Match)
    if ($procs.Count -eq 0) {
        if ($Status) { Add-Report $name 'DOWN' 'not running'; continue }
        if (-not ($pgOk -and $kafkaOk)) { Add-Report $name 'waiting' 'needs postgres and kafka'; continue }
        if (-not (Test-RestartAllowed $name)) { Add-Report $name 'LOOP' 'restart limit reached'; continue }
        Write-Log "$name is not running, starting it"
        $inner = 'set METRICS_PORT={0}&& "{1}" {2} >> "{3}" 2>> "{4}"' -f `
            $svc.Metrics, $Python, $svc.Run, (Join-Path $LogDir "$name.out.log"), (Join-Path $LogDir "$name.err.log")
        if (Start-Detached (New-ShellLine $inner) $Repo) { Note-Restart $name }
        Add-Report $name 'started' "metrics $($svc.Metrics)"
        continue
    }
    $detail = "pid $(($procs | Select-Object -First 1).ProcessId)"
    $svcState = 'ok'
    if ($svc.Health) {
        $healthy = $false
        try {
            $h = Invoke-RestMethod -Uri $svc.Health -TimeoutSec 5
            $healthy = ($h.model_loaded -eq $true -and $h.consumer_alive -eq $true)
            if ($h.last_scored_at) { $detail += ", last scored $($h.last_scored_at)" }
        } catch { }
        if ($healthy) {
            $State.counters["health:$name"] = 0
        } else {
            $svcState = 'UNHEALTHY'
            $State.counters["health:$name"] = 1 + [int]$State.counters["health:$name"]
            if ($State.counters["health:$name"] -ge 3 -and -not $Status -and (Test-RestartAllowed $name)) {
                Write-Log "$name failed its health check 3 passes in a row, restarting it"
                Stop-Matching 'python%' $svc.Match
                Note-Restart $name
                $State.counters["health:$name"] = 0
                $svcState = 'restarting'
            } elseif ($State.counters["health:$name"] -ge 3) {
                Add-Problem "health:$name" "$name is unhealthy."
            }
        }
    }
    Add-Report $name $svcState $detail
}

# ---- 4. Data freshness and the Neon sync -----------------------------------------------
$ages = $null
if ($pgOk) {
    try {
        $out = & $Python (Join-Path $Repo 'scripts\pipeline_status.py') 2>$null
        $ages = $out | ConvertFrom-Json
        if ($ages.error) { Add-Problem 'database' "Database query failed: $($ages.error)"; $ages = $null }
    } catch { Add-Problem 'database' "Could not read data freshness: $($_.Exception.Message)" }
}
if ($ages) {
    foreach ($key in $StaleMinutes.Keys) {
        $age = $ages.$key
        if ($null -eq $age) { Add-Report "data:$key" 'empty' 'no rows'; continue }
        $limit = $StaleMinutes[$key]
        if ($age -gt $limit) {
            Add-Problem "stale:$key" ("{0} has had no new data for {1:N0} min (limit {2} min)." -f $key, $age, $limit)
            Add-Report "data:$key" 'STALE' ('{0:N0} min old' -f $age)
        } else {
            Add-Report "data:$key" 'ok' ('{0:N0} min old' -f $age)
        }
    }
    # LMP stalled while everything claims to be running: restart that chain, at most hourly.
    $lmpAge = $ages.pjm_lmp
    if ($null -ne $lmpAge -and $lmpAge -gt 30 -and $pgOk -and $kafkaOk -and -not $Status) {
        $canRestart = $true
        if ($State.lastLmpRestart) { $canRestart = (((Get-Date) - [datetime]$State.lastLmpRestart).TotalMinutes -ge 60) }
        if ($canRestart) {
            Write-Log ('pjm LMP data is {0:N0} min old, restarting the PJM poller, consumer and inference service' -f $lmpAge)
            foreach ($n in 'pjm-poller', 'pjm-consumer', 'pjm-inference') {
                Stop-Matching 'python%' ($Services | Where-Object { $_.Name -eq $n }).Match
            }
            $State.lastLmpRestart = (Get-Date).ToString('o')
        }
    }
}

$neonTask = Get-ScheduledTask -TaskName 'pa-grid-monitor-neon-sync' -ErrorAction SilentlyContinue
if ($neonTask) {
    $info = $neonTask | Get-ScheduledTaskInfo
    $hours = ((Get-Date) - $info.LastRunTime).TotalHours
    if ($info.LastTaskResult -ne 0 -and $info.LastTaskResult -ne 267009) {
        Add-Problem 'neon-sync' ("The Neon sync last failed (result {0}). The website is not receiving new data." -f $info.LastTaskResult)
        Add-Report 'neon-sync' 'FAILED' ("result {0}" -f $info.LastTaskResult)
    } elseif ($hours -gt $NeonMaxAgeHours) {
        Add-Problem 'neon-sync' ("The Neon sync has not run for {0:N1} hours. The website is going stale." -f $hours)
        Add-Report 'neon-sync' 'STALE' ("{0:N1} h since last run" -f $hours)
    } else {
        Add-Report 'neon-sync' 'ok' ("{0:N1} h since last run" -f $hours)
    }
}

# ---- 5. Daily gap heal -----------------------------------------------------------------
if (-not $Status -and $pgOk -and $kafkaOk) {
    $now = Get-Date
    $due = ($now.Hour -ge $HealHourLocal)
    if ($State.lastHeal) { $due = $due -and (($now - [datetime]$State.lastHeal).TotalHours -ge 20) }
    if ($ForceHeal) { $due = $true }
    $running = @(Find-Processes 'python%' 'ingestion\.backfill|rescore_recent').Count -gt 0
    if ($due -and -not $running) {
        $start = (Get-Date).ToUniversalTime().AddDays(-$HealDays).ToString('yyyy-MM-dd')
        $log = Join-Path $LogDir 'heal.log'
        Write-Log "starting the daily gap heal from $start"
        $steps = @(
            ('"{0}" -m ingestion.backfill --source pjm --start {1} --no-metrics-server' -f $Python, $start),
            ('"{0}" -m ingestion.backfill --source eia --start {1} --no-metrics-server' -f $Python, $start),
            ('"{0}" scripts\rescore_recent.py --days {1}' -f $Python, ($HealDays + 1))
        )
        $inner = (($steps | ForEach-Object { '{0} >> "{1}" 2>&1' -f $_, $log }) -join ' & ')
        if (Start-Detached (New-ShellLine $inner) $Repo) { $State.lastHeal = $now.ToString('o') }
    }
}

# ---- Wrap up ---------------------------------------------------------------------------
if ($Status) {
    $Report | Format-Table -AutoSize | Out-String | Write-Host
    if ($Problems.Count -gt 0) { Write-Host 'Problems:'; $Problems.Values | ForEach-Object { Write-Host "  $_" } }
    else { Write-Host 'No problems found.' }
} else {
    Publish-Alerts
    Save-State
}
$mutex.ReleaseMutex()
