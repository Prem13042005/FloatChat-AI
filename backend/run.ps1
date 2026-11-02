
$ErrorActionPreference = "Stop"

# Configure Java
$env:JAVA_HOME = "C:\Program Files\Java\jdk-22"
$env:Path = "$env:JAVA_HOME\bin;$env:Path"

# Load environment variables from root .env
$envFile = Join-Path $PSScriptRoot "..\.env"

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()

        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            $key = $parts[0].Trim()
            $val = $parts[1].Trim().Trim('"').Trim("'")

            [System.Environment]::SetEnvironmentVariable(
                $key,
                $val,
                [System.EnvironmentVariableTarget]::Process
            )
        }
    }
}
else {
    throw "Root .env file not found: $envFile"
}

# Start backend from its own directory
Write-Host "Starting FloatChat Spring Boot Backend on http://localhost:8080..." -ForegroundColor Cyan

Push-Location $PSScriptRoot

try {
    if (-not (Test-Path ".\mvnw.cmd")) {
        throw "Maven wrapper not found in backend directory."
    }

    if (-not $env:JWT_SECRET) {
        throw "JWT_SECRET is missing or empty in root .env."
    }

    .\mvnw.cmd spring-boot:run
}
finally {
    Pop-Location
}
