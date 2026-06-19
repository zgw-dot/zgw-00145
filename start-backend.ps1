# 后端启动脚本
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $ScriptDir "backend"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  门店价签工作台 - 后端服务启动" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

Set-Location $BackendDir

# 检查 Python
try {
    python --version | Out-Null
    Write-Host "[OK] Python 已安装" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] 未找到 Python，请先安装 Python 3.8+" -ForegroundColor Red
    exit 1
}

# 检查依赖是否已安装
$venvDir = Join-Path $BackendDir ".venv"
$useVenv = $false

if (Test-Path $venvDir) {
    Write-Host "[INFO] 检测到虚拟环境，激活中..." -ForegroundColor Yellow
    $activateScript = Join-Path $venvDir "Scripts\Activate.ps1"
    if (Test-Path $activateScript) {
        . $activateScript
        $useVenv = $true
    }
}

# 检查 Flask 是否已安装
try {
    python -c "import flask" | Out-Null
    Write-Host "[OK] 依赖已就绪" -ForegroundColor Green
} catch {
    Write-Host "[INFO] 正在安装依赖包..." -ForegroundColor Yellow
    python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] 依赖安装失败，尝试不带镜像源..." -ForegroundColor Red
        python -m pip install -r requirements.txt
    }
    Write-Host "[OK] 依赖安装完成" -ForegroundColor Green
}

Write-Host ""
Write-Host "[启动] Flask 服务地址: http://localhost:5000" -ForegroundColor Cyan
Write-Host "[提示] 按 Ctrl+C 停止服务" -ForegroundColor DarkGray
Write-Host ""

python app.py
