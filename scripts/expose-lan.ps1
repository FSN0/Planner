# Expone SignaPlan (Caddy en WSL) a la WiFi del PC.
# OBLIGATORIO: PowerShell "Ejecutar como administrador".
#
# Si la polÃ­tica de firmas bloquea el .ps1:
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\scripts\expose-lan.ps1
#
# O copia/pega el bloque de abajo en una ventana Admin.

$ErrorActionPreference = "Stop"
$Distro = "Ubuntu-22.04"

function Get-WslIp {
    $raw = (wsl -d $Distro -- hostname -I 2>$null)
    if (-not $raw) { return $null }
    return ($raw.ToString().Trim().Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)[0])
}

function Get-WifiLanIp {
    # Evitar Hyper-V / WSL / Docker (172.x) y loopback.
    $candidates = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike '127.*' -and
            $_.IPAddress -notlike '169.254.*' -and
            $_.PrefixOrigin -ne 'WellKnown' -and
            $_.IPAddress -notmatch '^172\.(1[6-9]|2[0-9]|3[0-1])\.'
        }

    $wifi = $candidates | Where-Object {
        $_.InterfaceAlias -match 'Wi-?Fi|WLAN|Wireless'
    } | Select-Object -First 1

    if ($wifi) { return $wifi.IPAddress }

    $eth = $candidates | Where-Object {
        $_.InterfaceAlias -match 'Ethernet' -and
        $_.InterfaceAlias -notmatch 'vEthernet|WSL|Hyper-V|Default Switch|Docker'
    } | Select-Object -First 1

    if ($eth) { return $eth.IPAddress }

    $any = $candidates | Select-Object -First 1
    if ($any) { return $any.IPAddress }
    return $null
}

$WslIp = Get-WslIp
if (-not $WslIp) {
    Write-Error "No se ha podido obtener la IP de WSL ($Distro). Â¿EstÃ¡ arrancado?"
}

$LanIp = Get-WifiLanIp
Write-Host "WSL IP : $WslIp"
Write-Host "LAN IP : $(if ($LanIp) { $LanIp } else { '(no detectada)' })"
Write-Host ""

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).
    IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: esta ventana NO es Administrador." -ForegroundColor Red
    Write-Host "Cierra, abre PowerShell con clic derecho -> Ejecutar como administrador, y repite."
    exit 1
}

foreach ($port in @(80, 8080)) {
    netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$port 2>$null | Out-Null
    netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$port connectaddress=$WslIp connectport=$port
    if ($LASTEXITCODE -ne 0) {
        Write-Error "FallÃ³ portproxy en puerto $port (Â¿admin?)."
    }
    Write-Host "OK portproxy 0.0.0.0:$port -> ${WslIp}:$port"
}

netsh advfirewall firewall delete rule name="WSL planner HTTP 80" 2>$null | Out-Null
netsh advfirewall firewall delete rule name="WSL planner HTTP 8080" 2>$null | Out-Null
netsh advfirewall firewall add rule name="WSL planner HTTP 80" dir=in action=allow protocol=TCP localport=80 | Out-Null
netsh advfirewall firewall add rule name="WSL planner HTTP 8080" dir=in action=allow protocol=TCP localport=8080 | Out-Null
Write-Host "OK reglas firewall 80 y 8080"

Write-Host ""
Write-Host "Comprobacion desde este PC:"
foreach ($url in @(
    "http://127.0.0.1:8080/health",
    $(if ($LanIp) { "http://${LanIp}:8080/health" } else { $null })
)) {
    if (-not $url) { continue }
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 4
        Write-Host "  $url -> $($r.StatusCode) $($r.Content)"
    } catch {
        Write-Host "  $url -> FALLA ($($_.Exception.Message))" -ForegroundColor Yellow
    }
}

Write-Host ""
if ($LanIp) {
    Write-Host "En el MOVIL (misma WiFi), abre EXACTAMENTE:" -ForegroundColor Green
    Write-Host "  http://${LanIp}:8080/health"
    Write-Host "  http://${LanIp}:8080/mi/"
    Write-Host ""
    Write-Host "NO uses 172.x (eso es Hyper-V/WSL, el telefono no llega)."
} else {
    Write-Host "No he encontrado IP WiFi. En Windows: ipconfig -> IPv4 de Wi-Fi (suele ser 192.168.x.x)."
    Write-Host "Luego en el movil: http://ESA_IP:8080/mi/"
}
Write-Host ""
if ($LanIp) {
    Write-Host "En el MOVIL (misma WiFi):" -ForegroundColor Green
    Write-Host "  Solo IP -> landing (marketing):"
    Write-Host "    http://${LanIp}:8080/"
    Write-Host "    http://${LanIp}:8080/health"
    Write-Host "  Tenant Paquito (subdominio sslip.io, mismo comportamiento que produccion):"
    Write-Host "    http://paquito.${LanIp}.sslip.io:8080/"
    Write-Host "    http://paquito.${LanIp}.sslip.io:8080/mi/"
    Write-Host ""
    Write-Host "Si Caddy escucha en el puerto 80, quita :8080 de las URLs."
    Write-Host "NO uses 172.x (eso es Hyper-V/WSL, el telefono no llega)."
} else {
    Write-Host "No he encontrado IP WiFi. En Windows: ipconfig -> IPv4 de Wi-Fi (suele ser 192.168.x.x)."
    Write-Host "Landing: http://ESA_IP:8080/  |  Tenant: http://paquito.ESA_IP.sslip.io:8080/mi/"
}
Write-Host ""
Write-Host "Requisitos app: docker compose up -d"
Write-Host "Tras reiniciar WSL, vuelve a ejecutar este script."
