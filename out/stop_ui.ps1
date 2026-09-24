# Stop the TRENCHNET desk UI server on port 8788
$conn = Get-NetTCPConnection -LocalPort 8788 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
  Stop-Process -Id $conn.OwningProcess -Force
  Write-Output ("stopped pid " + $conn.OwningProcess)
} else {
  Write-Output "no listener on 8788"
}
