<#
.SYNOPSIS
    Remove as associacoes de arquivo Markdown criadas pelo EdgeMD.

.DESCRIPTION
    Desfaz o que register_file_association.ps1 gravou em HKEY_CURRENT_USER.

    E conservador de proposito: so apaga a associacao padrao do .md se ela
    ainda apontar para o EdgeMD. Se voce trocou o programa padrao depois,
    a sua escolha atual e preservada.

.EXAMPLE
    .\unregister_file_association.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$ProgId     = 'EdgeMD.Document'
$AppName    = 'EdgeMD'
$Extensions = @('.md', '.markdown', '.mdown', '.mkd', '.mkdn')
$CapsPath   = 'Software\EdgeMD\EdgeMD\Capabilities'

$classesKey = 'HKCU:\Software\Classes'

Write-Host ""
Write-Host "EdgeMD - removendo associacoes" -ForegroundColor Cyan
Write-Host ""

# --------------------------------------------------------------------------
# Extensoes
# --------------------------------------------------------------------------
foreach ($ext in $Extensions) {
    $extKey = Join-Path $classesKey $ext

    if (Test-Path -LiteralPath $extKey) {
        $current = (Get-ItemProperty -Path $extKey -Name '(default)' -ErrorAction SilentlyContinue).'(default)'

        if ($current -eq $ProgId) {
            # So limpa se ainda for nosso; caso contrario a escolha do usuario
            # prevalece.
            Remove-ItemProperty -Path $extKey -Name '(default)' -ErrorAction SilentlyContinue
            Write-Host "  padrao liberado: $ext" -ForegroundColor Green
        }
        elseif ($current) {
            Write-Host "  padrao preservado: $ext -> $current" -ForegroundColor DarkGray
        }

        $owpValue = Join-Path $extKey "OpenWithProgids\$ProgId"
        if (Test-Path -LiteralPath $owpValue) {
            Remove-Item -LiteralPath $owpValue -Force
            Write-Host "  removido de Abrir com: $ext" -ForegroundColor Green
        }
    }
}

# --------------------------------------------------------------------------
# ProgID, Capabilities e aplicativos registrados
# --------------------------------------------------------------------------
$progIdKey = Join-Path $classesKey $ProgId
if (Test-Path -LiteralPath $progIdKey) {
    Remove-Item -LiteralPath $progIdKey -Recurse -Force
    Write-Host "  removido: $ProgId" -ForegroundColor Green
}

# Entradas do executavel empacotado, que o app tambem grava.
foreach ($exeName in @('edgemd.exe')) {
    $appKey = Join-Path $classesKey "Applications\$exeName"
    if (Test-Path -LiteralPath $appKey) {
        Remove-Item -LiteralPath $appKey -Recurse -Force
        Write-Host "  removido: Applications\$exeName" -ForegroundColor Green
    }
}

$capsKey = "HKCU:\$CapsPath"
$capsParent = Split-Path -Parent $capsKey
if (Test-Path -LiteralPath $capsKey) {
    Remove-Item -LiteralPath $capsKey -Recurse -Force
    Write-Host "  removido: Capabilities" -ForegroundColor Green
}
if (Test-Path -LiteralPath $capsParent) {
    Remove-Item -LiteralPath $capsParent -Recurse -Force -ErrorAction SilentlyContinue
}

$registeredKey = 'HKCU:\Software\RegisteredApplications'
if (Test-Path -LiteralPath $registeredKey) {
    Remove-ItemProperty -Path $registeredKey -Name $AppName -ErrorAction SilentlyContinue
    Write-Host "  removido de RegisteredApplications" -ForegroundColor Green
}

# --------------------------------------------------------------------------
# Avisar o Explorer
# --------------------------------------------------------------------------
Add-Type -Namespace EdgeMD -Name Shell32 -MemberDefinition @'
[DllImport("shell32.dll", CharSet = CharSet.Auto, SetLastError = true)]
public static extern void SHChangeNotify(int wEventId, int uFlags, System.IntPtr dwItem1, System.IntPtr dwItem2);
'@
[EdgeMD.Shell32]::SHChangeNotify(0x08000000, 0x0000, [System.IntPtr]::Zero, [System.IntPtr]::Zero)

Write-Host ""
Write-Host "Pronto. As associacoes do EdgeMD foram removidas." -ForegroundColor Green
Write-Host "Suas preferencias do app (tema, sessoes) nao foram tocadas." -ForegroundColor DarkGray
