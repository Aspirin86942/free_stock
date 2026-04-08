# 运行 gm.api 验证脚本
# 用法: .\run_verify.ps1

if (-not $env:GM_TOKEN) {
    Write-Host "❌ 错误: 未设置环境变量 GM_TOKEN" -ForegroundColor Red
    Write-Host ""
    Write-Host "请先设置:"
    Write-Host '  $env:GM_TOKEN="your-token"'
    exit 1
}

Write-Host "使用 Token: $($env:GM_TOKEN.Substring(0, [Math]::Min(10, $env:GM_TOKEN.Length)))..." -ForegroundColor Green
Write-Host ""

& "C:\Users\Aspir\anaconda3\envs\stock_analysis\python.exe" scripts/verify_gm_api.py a9efa143-52fb-11f0-82fa-52560acd7da0
