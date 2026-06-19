# 一键启动脚本 - 前后端同时启动
$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   门店价签发布工作台 - 一键启动脚本" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "   后端地址: http://localhost:5000" -ForegroundColor Gray
Write-Host "   前端地址: http://localhost:5173" -ForegroundColor Gray
Write-Host ""

# 创建独立控制台窗口启动后端
$backendCmd = "powershell -NoExit -ExecutionPolicy Bypass -File `"$ScriptDir\start-backend.ps1`""
Write-Host "[1/2] 启动后端服务..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy Bypass", "-File", "`"$ScriptDir\start-backend.ps1`""

Write-Host "       等待后端初始化..." -ForegroundColor Gray
Start-Sleep -Seconds 8

# 创建独立控制台窗口启动前端
Write-Host "[2/2] 启动前端服务..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy Bypass", "-File", "`"$ScriptDir\start-frontend.ps1`""

Start-Sleep -Seconds 5

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  启动完成！" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  浏览器访问:  http://localhost:5173" -ForegroundColor Cyan
Write-Host ""
Write-Host "  测试账号：" -ForegroundColor Yellow
Write-Host "    管理员 admin    / admin123   " -ForegroundColor White
Write-Host "    运营   operator / operator123" -ForegroundColor White
Write-Host "    店员   clerk    / clerk123   " -ForegroundColor White
Write-Host ""
Write-Host "  要停止服务，直接关闭两个独立窗口即可" -ForegroundColor DarkGray
Write-Host ""

# 可选：自动打开浏览器
$openBrowser = Read-Host "是否自动打开浏览器访问? (Y/n)"
if ($openBrowser -ne "n" -and $openBrowser -ne "N") {
    Start-Process "http://localhost:5173"
}
