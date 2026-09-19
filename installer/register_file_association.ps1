<#
.SYNOPSIS
    Associa arquivos Markdown ao EdgeMD.

.DESCRIPTION
    Grava as associações em HKEY_CURRENT_USER, então NÃO precisa de
    administrador e não altera nada para outros usuários da máquina.

    São gravadas três coisas:

      1. OpenWithProgids  - coloca o app em "Abrir com", sem mexer no padrão.
      2. ProgID + .md     - torna o app o programa do clique duplo (só com -Default).
      3. Capabilities     - faz o app aparecer em Configurações > Aplicativos
                            padrão, onde o usuário pode promovê-lo sozinho.

    Sem -Default, o script é conservador: adiciona o app às opções e deixa a
    associação atual como está.

.PARAMETER ExePath
    Caminho do executável (ou do run.pyw). Se omitido, procura nesta ordem:
    dist\edgemd.exe, e depois run.pyw na raiz do projeto.

.PARAMETER Default
    Torna o EdgeMD o programa padrão do clique duplo em .md.

.EXAMPLE
    .\register_file_association.ps1
    Adiciona o app a "Abrir com", sem mudar o padrão.

.EXAMPLE
    .\register_file_association.ps1 -Default
    Torna o EdgeMD o programa padrão dos arquivos .md.
#>

[CmdletBinding()]
param(
    [string]$ExePath,
    [switch]$Default
)

$ErrorActionPreference = 'Stop'

$ProgId       = 'EdgeMD.Document'
$FriendlyName = 'Documento Markdown'
$AppName      = 'EdgeMD'
$Extensions   = @('.md', '.markdown', '.mdown', '.mkd', '.mkdn')
$CapsPath     = 'Software\EdgeMD\EdgeMD\Capabilities'

# --------------------------------------------------------------------------
# Descobrir o executável
# --------------------------------------------------------------------------
$projectRoot = Split-Path -Parent $PSScriptRoot

if (-not $ExePath) {
    $candidates = @(
        (Join-Path $projectRoot 'dist\edgemd.exe'),
        (Join-Path $projectRoot 'run.pyw')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { $ExePath = $candidate; break }
    }
}

if (-not $ExePath) {
    throw "Nao encontrei o executavel. Gere o .exe com 'pyinstaller edgemd.spec' ou passe -ExePath."
}

$ExePath = (Resolve-Path -LiteralPath $ExePath).Path

# Para .pyw, o Windows associa ao interpretador certo se usarmos pythonw.exe.
if ($ExePath.EndsWith('.pyw')) {
    $pythonw = Join-Path (Split-Path -Parent (Get-Command python -ErrorAction SilentlyContinue).Source) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw)) {
        $pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
    }
    if (-not $pythonw) {
        throw "Nao encontrei pythonw.exe. Use o .exe empacotado, ou rode a associacao pelo menu Ferramentas do app."
    }
    $command = "`"$pythonw`" `"$ExePath`" `"%1`""
    $iconSource = $null
}
else {
    $command = "`"$ExePath`" `"%1`""
    $iconSource = $ExePath
}

$ico = Join-Path $projectRoot 'src\edgemd\resources\icons\edgemd.ico'
if (Test-Path -LiteralPath $ico) { $iconSource = $ico }

Write-Host ""
Write-Host "EdgeMD - associacao de arquivos" -ForegroundColor Cyan
Write-Host "  progid    : $ProgId"
Write-Host "  extensoes : $($Extensions -join ', ')"
Write-Host "  comando   : $command"
Write-Host "  padrao    : $(if ($Default) { 'SIM' } else { 'nao (apenas Abrir com)' })"
Write-Host ""

# --------------------------------------------------------------------------
# Gravar
# --------------------------------------------------------------------------
$classesKey = 'HKCU:\Software\Classes'

# 1. ProgID
$progIdKey = Join-Path $classesKey $ProgId
New-Item -Path $progIdKey -Force | Out-Null
Set-ItemProperty -Path $progIdKey -Name '(default)' -Value $FriendlyName
Set-ItemProperty -Path $progIdKey -Name 'FriendlyTypeName' -Value $FriendlyName

if ($iconSource) {
    $iconKey = Join-Path $progIdKey 'DefaultIcon'
    New-Item -Path $iconKey -Force | Out-Null
    Set-ItemProperty -Path $iconKey -Name '(default)' -Value "$iconSource,0"
}

$cmdKey = Join-Path $progIdKey 'shell\open\command'
New-Item -Path $cmdKey -Force | Out-Null
Set-ItemProperty -Path $cmdKey -Name '(default)' -Value $command

# 2. Extensoes
foreach ($ext in $Extensions) {
    $extKey = Join-Path $classesKey $ext
    New-Item -Path $extKey -Force | Out-Null

    # OpenWithProgids: registro binario vazio, e o que o Explorer procura.
    $owpKey = Join-Path $extKey 'OpenWithProgids'
    New-Item -Path $owpKey -Force | Out-Null
    New-ItemProperty -Path $owpKey -Name $ProgId -PropertyType None -Value ([byte[]]@()) -Force | Out-Null

    if ($Default) {
        Set-ItemProperty -Path $extKey -Name '(default)' -Value $ProgId
        Write-Host "  [padrao] $ext -> $ProgId" -ForegroundColor Green
    }
    else {
        Write-Host "  [abrir com] $ext" -ForegroundColor DarkGray
    }
}

# 3. Capabilities (Configuracoes > Aplicativos padrao)
$capsKey = "HKCU:\$CapsPath"
New-Item -Path $capsKey -Force | Out-Null
Set-ItemProperty -Path $capsKey -Name '(default)' -Value $AppName
Set-ItemProperty -Path $capsKey -Name 'ApplicationName' -Value $AppName

$fileAssocKey = Join-Path $capsKey 'FileAssociations'
New-Item -Path $fileAssocKey -Force | Out-Null
foreach ($ext in $Extensions) {
    Set-ItemProperty -Path $fileAssocKey -Name $ext -Value $ProgId
}

$registeredKey = 'HKCU:\Software\RegisteredApplications'
New-Item -Path $registeredKey -Force | Out-Null
Set-ItemProperty -Path $registeredKey -Name $AppName -Value $CapsPath

# --------------------------------------------------------------------------
# Avisar o Explorer
# --------------------------------------------------------------------------
# Sem isto, icones e o programa padrao so mudam depois de reiniciar o Explorer.
Add-Type -Namespace EdgeMD -Name Shell32 -MemberDefinition @'
[DllImport("shell32.dll", CharSet = CharSet.Auto, SetLastError = true)]
public static extern void SHChangeNotify(int wEventId, int uFlags, System.IntPtr dwItem1, System.IntPtr dwItem2);
'@
[EdgeMD.Shell32]::SHChangeNotify(0x08000000, 0x0000, [System.IntPtr]::Zero, [System.IntPtr]::Zero)

Write-Host ""
Write-Host "Pronto." -ForegroundColor Green

if (-not $Default) {
    Write-Host ""
    Write-Host "O app foi adicionado a 'Abrir com', sem alterar o padrao atual." -ForegroundColor Yellow
    Write-Host "Para torna-lo padrao de verdade:" -ForegroundColor Yellow
    Write-Host "  * rode este script com -Default, ou"
    Write-Host "  * botao direito no .md > Abrir com > Escolher outro aplicativo"
    Write-Host "    (e marque 'Sempre usar este aplicativo')"
}
else {
    Write-Host ""
    Write-Host "O Windows pode pedir uma confirmacao na primeira vez que voce" -ForegroundColor Yellow
    Write-Host "abrir um .md, para validar a troca de programa padrao." -ForegroundColor Yellow
}
