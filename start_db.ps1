# =============================================================
# start_db.ps1 — 啟動本機 PostgreSQL（port 5433）
# 每次 重開機後 執行一次即可
# =============================================================

$pgBin = "D:\ton\pgsql\bin"
$dataDir = "D:\ton\pgdata"

# 確認程序沒有已在跑
$running = Get-Process -Name "postgres" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "*D:\ton\pgsql*" }

if ($running) {
    Write-Host "PostgreSQL 已在運行 (PID: $($running[0].Id))" -ForegroundColor Green
    exit 0
}

Write-Host "啟動 PostgreSQL on port 5433..." -ForegroundColor Cyan

# 確保 PATH 包含 PG binaries（避免 DLL 0xC0000142 崩潰）
$env:PATH = "$pgBin;$env:PATH"

# 直接啟動 postgres.exe（不用 pg_ctl，避免子程序問題）
$p = Start-Process -FilePath "$pgBin\postgres.exe" `
    -ArgumentList "-D", $dataDir, "-p", "5433", "-c", "listen_addresses=localhost" `
    -WindowStyle Hidden -PassThru

Start-Sleep -Seconds 3

if (-not $p.HasExited) {
    Write-Host "PostgreSQL 啟動成功 (PID: $($p.Id), port 5433)" -ForegroundColor Green
    Write-Host "連線字串: postgresql://cryptomind:cryptomind@localhost:5433/cryptomind"
} else {
    Write-Host "PostgreSQL 啟動失敗 (exit code: $($p.ExitCode))" -ForegroundColor Red
    Write-Host "請檢查 log: $dataDir\server.log"
    exit 1
}
