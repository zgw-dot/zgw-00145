# 前端启动脚本
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendDir = Join-Path $ScriptDir "frontend"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  门店价签工作台 - 前端服务启动" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

Set-Location $FrontendDir

# 检查 Node.js
try {
    node --version | Out-Null
    npm --version | Out-Null
    Write-Host "[OK] Node.js 和 npm 已安装" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] 未找到 Node.js，请先安装 Node.js 16+" -ForegroundColor Red
    Write-Host "下载地址: https://nodejs.org/" -ForegroundColor Yellow
    exit 1
}

# 设置国内镜像源（可选）
npm config get registry | ForEach-Object {
    if ($_ -ne "https://registry.npmmirror.com/" -and $_ -ne "https://registry.npm.taobao.org/") {
        $choice = Read-Host "当前 npm 源: $_，是否切换到淘宝镜像? (Y/n)"
        if ($choice -ne "n" -and $choice -ne "N") {
            npm config set registry https://registry.npmmirror.com
            Write-Host "[OK] 已切换到淘宝镜像源" -ForegroundColor Green
        }
    }
}

# 检查 node_modules
if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Host "[INFO] 正在安装前端依赖..." -ForegroundColor Yellow
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] 依赖安装失败" -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] 前端依赖安装完成" -ForegroundColor Green
} else {
    Write-Host "[OK] node_modules 已存在" -ForegroundColor Green
}

Write-Host ""
Write-Host "[启动] Vite 开发服务器: http://localhost:5173" -ForegroundColor Cyan
Write-Host "[提示] 按 Ctrl+C 停止服务" -ForegroundColor DarkGray
Write-Host ""

npm run dev
