param(
    [string]$Action = "help"
)

$RuntimeDir = Join-Path $PSScriptRoot "runtime"

if (!(Test-Path $RuntimeDir)) {
    Write-Host "Error: runtime directory not found at $RuntimeDir" -ForegroundColor Red
    exit 1
}

Set-Location -Path $RuntimeDir

switch ($Action) {
    "test" {
        Write-Host "Running tests in runtime module..." -ForegroundColor Green
        cargo test
    }
    "build" {
        Write-Host "Building WASM module via wasm-pack..." -ForegroundColor Green
        wasm-pack build --target web
    }
    "serve" {
        Write-Host "Starting local HTTP server on port 8000..." -ForegroundColor Green
        python -m http.server 8000
    }
    "all" {
        Write-Host "Running tests..." -ForegroundColor Green
        cargo test
        if ($LASTEXITCODE -eq 0 -or $?) {
            Write-Host "Building WASM module..." -ForegroundColor Green
            wasm-pack build --target web
        } else {
            Write-Host "Tests failed. Skipping build." -ForegroundColor Red
        }
    }
    default {
        Write-Host "Usage: .\run.ps1 [Action]"
        Write-Host "Actions:"
        Write-Host "  test  - Run cargo tests"
        Write-Host "  build - Build WASM module via wasm-pack"
        Write-Host "  all   - Run tests and build WASM module"
        Write-Host "  serve - Start python HTTP server to test WASM"
    }
}

Set-Location -Path $PSScriptRoot
