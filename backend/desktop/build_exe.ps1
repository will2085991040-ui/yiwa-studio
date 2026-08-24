# YIWA 桌面 EXE 构建脚本（Windows）。
# 用途：一条命令产出 backend\dist\YIWA.exe（内置后端 + 前端静态站点 + Alembic 迁移）。
# 用法（任意目录，脚本会自动定位仓库根）：powershell -ExecutionPolicy Bypass -File <repo>\backend\desktop\build_exe.ps1
$ErrorActionPreference = "Stop"
$Backend = Split-Path -Parent $PSScriptRoot            # backend\
$Repo = Split-Path -Parent $Backend                     # repo root
$Frontend = Join-Path $Repo "frontend"

Write-Host "[1/5] 构建前端静态产物（out/）"
Set-Location $Frontend
& npm.cmd install --no-audit --no-fund 2>&1 | Out-Null
& npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }

Write-Host "[2/5] 安装/校验打包依赖（pyinstaller）"
Set-Location $Backend
& .\.venv\Scripts\python.exe -m pip install pyinstaller==6.11.1 2>&1 | Out-Null
& .\.venv\Scripts\python.exe -c "import PyInstaller; print('PyInstaller', PyInstaller.__version__)"

Write-Host "[3/5] 校验后端测试"
& .\.venv\Scripts\python.exe -m pytest -q --no-cov
if ($LASTEXITCODE -ne 0) { throw "后端测试失败" }

Write-Host "[4/5] PyInstaller 打包单文件 EXE"
& .\.venv\Scripts\pyinstaller.exe --clean --noconfirm desktop\yiwa.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }

Write-Host "[5/5] 完成"
if (Test-Path .\dist\YIWA.exe) {
    Write-Host "已生成：$((Resolve-Path .\dist\YIWA.exe).Path)"
} else {
    throw "未找到 dist\YIWA.exe"
}