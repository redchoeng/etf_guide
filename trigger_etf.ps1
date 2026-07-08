# ETF Monitor 워크플로우 수동 트리거 (Windows 작업 스케줄러용)
# GitHub 무료 크론이 자주 스킵돼서 로컬에서 09:05 KST에 직접 dispatch를 쏜다.
$log = Join-Path $PSScriptRoot "trigger_etf.log"
function Log($msg) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Add-Content $log }

try {
    $git = "C:\Program Files\Git\cmd\git.exe"
    $credInput = "protocol=https`nhost=github.com`n"
    $tmp = Join-Path $env:TEMP "etf_cred_tmp.txt"
    [IO.File]::WriteAllText($tmp, $credInput, [Text.Encoding]::ASCII)
    $out = cmd /c "`"$git`" credential fill < `"$tmp`""
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    $token = ($out | Where-Object { $_ -match '^password=' }) -replace '^password=', ''
    if (-not $token) { Log "FAIL: 토큰 없음"; exit 1 }

    $resp = Invoke-WebRequest `
        -Uri "https://api.github.com/repos/redchoeng/etf_guide/actions/workflows/etf-monitor.yml/dispatches" `
        -Method POST `
        -Headers @{ Authorization = "token $token"; Accept = "application/vnd.github.v3+json"; "User-Agent" = "etf-trigger" } `
        -Body '{"ref":"main"}' -ContentType "application/json" -UseBasicParsing
    Log "OK: dispatch $($resp.StatusCode)"
} catch {
    Log "FAIL: $($_.Exception.Message)"
    exit 1
}
