# NominaBoard - Arranque LOCAL (sin Docker)
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $ProjectRoot "backend"
$VenvDir     = Join-Path $ProjectRoot ".venv"
$EnvFile     = Join-Path $ProjectRoot ".env.local"
$python      = Join-Path $VenvDir "Scripts\python.exe"
$uvicorn     = Join-Path $VenvDir "Scripts\uvicorn.exe"
$pip         = Join-Path $VenvDir "Scripts\pip.exe"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  NominaBoard - Arranque Local" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Crear venv si no existe
if (-not (Test-Path $VenvDir)) {
    Write-Host "Creando entorno virtual..." -ForegroundColor Yellow
    python -m venv $VenvDir
}

# 2. Instalar dependencias
Write-Host "Instalando dependencias..." -ForegroundColor Yellow
$reqFile = Join-Path $ProjectRoot "requirements_local.txt"
& $pip install -r $reqFile --quiet

# 3. Crear carpeta logs
$logsDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

# 4. Copiar .env.local al backend
Copy-Item $EnvFile (Join-Path $BackendDir ".env") -Force

Write-Host ""
Write-Host "  URL:         http://localhost:8000" -ForegroundColor Green
Write-Host "  Login:       http://localhost:8000/login.html" -ForegroundColor Green
Write-Host "  Credencial:  admin / Admin2024!" -ForegroundColor Green
Write-Host "  Ctrl+C para detener" -ForegroundColor Gray
Write-Host ""

# 5. Arrancar uvicorn
Set-Location $BackendDir
& $uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
