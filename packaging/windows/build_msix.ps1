<#
.SINOPSE
    Gera o pacote MSIX do EdgeMD para Windows.

.DESCRICAO
    Monta a arvore do pacote, gera os icones de tile nos tamanhos exigidos,
    preenche o AppxManifest.xml, empacota com o makeappx e assina com o
    signtool.

    Sobre a assinatura: o MSIX NAO INSTALA sem assinatura. Nao ha modo de
    contornar isso — nem para teste. Um certificado autoassinado serve para
    desenvolvimento e para distribuir a quem aceitar instalar o certificado;
    distribuir publicamente sem aviso exige um certificado de code signing de
    uma autoridade certificadora.

.USO
    # Gera e assina com um certificado autoassinado, instalando a confianca
    # necessaria para testar na propria maquina:
    .\build_msix.ps1 -SelfSigned

    # Gera e assina com um certificado proprio (.pfx):
    .\build_msix.ps1 -Certificate caminho\para\cert.pfx -Password senha

    # So gera, sem assinar. O pacote NAO podera ser instalado, mas serve para
    # conferir o conteudo:
    .\build_msix.ps1

.NOTAS
    Precisa do bundle do PyInstaller em dist\edgemd, gerado antes com
    pyinstaller edgemd.spec.

    O makeappx e o signtool vem do Windows SDK. Quando nao estao no PATH, o
    script procura nas instalacoes conhecidas e tambem no pacote NuGet
    Microsoft.Windows.SDK.BuildTools, que e o caminho leve (~21 MB em vez de
    mais de 1 GB do SDK completo).
#>
[CmdletBinding()]
param(
    [string]$Versao = "0.1.0",
    [string]$Certificate,
    [string]$Password,
    [switch]$SelfSigned,
    [string]$Publisher = "CN=EdgeMD",
    [string]$PublisherDisplay = "Eduardo Mauricio Pessoa de Souza",
    [string]$IdentityName = "io.github.eduradopessoa.edgemd",
    [string]$OutputDirectory = "dist\msix"
)

$ErrorActionPreference = "Stop"

$Raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

# ---------------------------------------------------------------------------
# Versao: o MSIX exige quatro campos. "0.1.0" vira "0.1.0.0".
# ---------------------------------------------------------------------------
if ($Versao -notmatch '^\d') {
    throw "Versao invalida: '$Versao'. Precisa comecar com digito (ex.: 0.1.0)."
}

$partes = @($Versao -split '\.')
while ($partes.Count -lt 4) { $partes += '0' }
$VersaoMsix = ($partes[0..3] -join '.')

# ---------------------------------------------------------------------------
# Ferramentas
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Certificado de desenvolvimento
# ---------------------------------------------------------------------------
function New-EdgeMDCertificado {
    <#
    .SINOPSE
        Cria um certificado autoassinado proprio para assinar o MSIX.

    .DESCRICAO
        Usa as classes de criptografia do .NET em vez do cmdlet
        New-SelfSignedCertificate. Aquele depende do modulo PKI, que travou
        nesta maquina sem erro, sem timeout e sem deixar rastro no log — o
        script ficava parado indefinidamente. Com o .NET nao ha dependencia de
        modulo, e o custo e o mesmo.

        O certificado precisa de duas coisas para servir a um MSIX:
          * KeyUsage = DigitalSignature;
          * EnhancedKeyUsage com o OID 1.3.6.1.5.5.7.3.3 (Code Signing).
        Sem a segunda, o Windows instala o pacote mas recusa executa-lo.
    #>
    param([string]$Assunto)

    $rsa = [System.Security.Cryptography.RSA]::Create(2048)

    $pedido = New-Object System.Security.Cryptography.X509Certificates.CertificateRequest(
        $Assunto,
        $rsa,
        [System.Security.Cryptography.HashAlgorithmName]::SHA256,
        [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
    )

    # Nao e uma autoridade certificadora: nao pode emitir outros certificados.
    $basico = New-Object System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension(
        $false, $false, 0, $true)
    $pedido.CertificateExtensions.Add($basico)

    $usoChave = New-Object System.Security.Cryptography.X509Certificates.X509KeyUsageExtension(
        [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature, $true)
    $pedido.CertificateExtensions.Add($usoChave)

    $oids = New-Object System.Security.Cryptography.OidCollection
    $oids.Add((New-Object System.Security.Cryptography.Oid("1.3.6.1.5.5.7.3.3"))) | Out-Null
    $usoEstendido = New-Object System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension(
        $oids, $true)
    $pedido.CertificateExtensions.Add($usoEstendido)

    $inicio = [DateTimeOffset]::Now.AddDays(-1)
    $fim = [DateTimeOffset]::Now.AddYears(5)
    $criado = $pedido.CreateSelfSigned($inicio, $fim)

    # O certificado devolvido por CreateSelfSigned tem a chave privada apenas em
    # memoria, e ela nao sobrevive a exportacao para a loja. Reimportar a partir
    # do PFX, com PersistKeySet, e o que faz a chave ficar utilizavel depois.
    $senha = "edgemd-dev"
    $bytes = $criado.Export(
        [System.Security.Cryptography.X509Certificates.X509ContentType]::Pfx, $senha)
    $persistente = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(
        $bytes,
        $senha,
        ([System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable -bor
         [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::UserKeySet -bor
         [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::PersistKeySet)
    )

    $loja = New-Object System.Security.Cryptography.X509Certificates.X509Store("My", "CurrentUser")
    $loja.Open("ReadWrite")
    try {
        $loja.Add($persistente)
    }
    finally {
        $loja.Close()
    }

    return $persistente
}

function Find-SdkTool {
    param([string]$Nome)
    $noPath = Get-Command $Nome -ErrorAction SilentlyContinue
    if ($noPath) { return $noPath.Source }

    $procurados = @(
        (Join-Path $env:LOCALAPPDATA "edgemd-sdktools\$Nome.exe"),
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin\x64\$Nome.exe",
        "$env:ProgramFiles\Windows Kits\10\bin\x64\$Nome.exe"
    )

    # Instalacoes do SDK guardam os binarios sob a versao do kit.
    $kits = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path $kits) {
        Get-ChildItem $kits -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object {
                $procurados += (Join-Path $_.FullName "x64\$Nome.exe")
            }
    }

    foreach ($caminho in $procurados) {
        if ($caminho -and (Test-Path $caminho)) { return $caminho }
    }
    return $null
}

Write-Host "==> Localizando as ferramentas do SDK"
$makeappx = Find-SdkTool "makeappx"
$signtool = Find-SdkTool "signtool"

if (-not $makeappx) {
    # Here-string com aspas simples de propósito: com aspas duplas, o PowerShell
    # expandiria os "$url" das instruções e elas sairiam vazias.
    throw @'
makeappx.exe nao encontrado.

Ele vem no Windows SDK. Duas formas de obter:

  1. Pacote NuGet, que e o caminho leve (~21 MB em vez de mais de 1 GB):
       $url = 'https://www.nuget.org/api/v2/package/Microsoft.Windows.SDK.BuildTools/10.0.26100.1742'
       Invoke-WebRequest $url -OutFile bt.zip
       Expand-Archive bt.zip bt
       New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\edgemd-sdktools"
       Copy-Item bt\bin\10.0.26100.0\x64\*.exe "$env:LOCALAPPDATA\edgemd-sdktools"

  2. SDK completo: winget install Microsoft.WindowsSDK
'@
}
Write-Host "    makeappx: $makeappx"
if ($signtool) { Write-Host "    signtool: $signtool" }

# ---------------------------------------------------------------------------
# Bundle de origem
# ---------------------------------------------------------------------------
$origem = Join-Path $Raiz "dist\edgemd"
if (-not (Test-Path (Join-Path $origem "edgemd.exe"))) {
    throw "Bundle nao encontrado em $origem. Gere antes: pyinstaller edgemd.spec --noconfirm --clean"
}

$saida = Join-Path $Raiz $OutputDirectory
$arvore = Join-Path $saida "arvore"
$pacote = Join-Path $saida "EdgeMD-$Versao-x64.msix"

Write-Host "==> Preparando a arvore do pacote"
if (Test-Path $arvore) { Remove-Item $arvore -Recurse -Force }
New-Item -ItemType Directory -Force -Path $arvore | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $arvore "Assets") | Out-Null

Write-Host "    copiando o bundle (pode demorar: sao ~500 MB)"

# Copy-Item com curinga no caminho de origem ACHATA a arvore: copiar
# "dist\edgemd\*" para um destino faz o conteudo de _internal\ subir um nivel,
# e o pacote sai com PIL\, numpy\ e PyQt6\ na raiz em vez de dentro de
# _internal\. O executavel entao morre na largada, sem mensagem, porque o
# bootloader do PyInstaller nao encontra as dependencias.
#
# O robocopy preserva a estrutura, e ainda e bem mais rapido com 400 arquivos
# e 500 MB. Os codigos de saida dele sao um bitmask: de 0 a 7 e sucesso
# (1 = arquivos copiados, 2 = extras no destino, 3 = os dois).
$robocopy = Get-Command robocopy -ErrorAction SilentlyContinue
if ($robocopy) {
    $destinoBundle = Join-Path $arvore "edgemd"
    & $robocopy $origem $destinoBundle /E /NFL /NDL /NJH /NJS /NP /R:2 /W:1 | Out-Null
    $codigo = $LASTEXITCODE
    if ($codigo -ge 8) { throw "robocopy falhou com codigo $codigo" }
    Write-Host "    robocopy: codigo $codigo (0-7 e sucesso)"
}
else {
    # Sem robocopy, copiamos o diretorio em si em vez do seu conteudo: assim a
    # arvore e preservada.
    Copy-Item -LiteralPath $origem -Destination $arvore -Recurse -Force
}

# Confere que o layout sobreviveu. Sem esta checagem, um achatamento passa
# despercebido ate alguem instalar o pacote e o programa nao abrir.
$exeEmpacotado = Join-Path $arvore "edgemd\edgemd.exe"
$internos = Join-Path $arvore "edgemd\_internal"
if (-not (Test-Path $exeEmpacotado)) { throw "edgemd.exe nao chegou em $exeEmpacotado" }
if (-not (Test-Path $internos)) {
    throw @'
A copia perdeu o diretorio _internal, entao as dependencias ficaram soltas na
raiz do pacote e o programa nao vai abrir. Isso acontece quando a copia achata
a arvore (Copy-Item com curinga no caminho de origem faz isso).
'@
}
Write-Host "    estrutura preservada (edgemd\edgemd.exe e edgemd\_internal\)"

# ---------------------------------------------------------------------------
# Icones de tile
#
# Cada tamanho e desenhado por conta propria, e nao redimensionado de um so:
# o Windows usa o Square44x44Logo na barra de tarefas e o Square150x150Logo no
# menu Iniciar, e ambos precisam estar nitidos. Alem disso, sem as variantes
# "altform-unplated" o Windows coloca o icone sobre um quadrado colorido, o
# que estraga um icone que ja tem fundo proprio.
# ---------------------------------------------------------------------------
Write-Host "==> Gerando os icones de tile"
$iconeOrigem = Join-Path $Raiz "src\edgemd\resources\icons\edgemd.png"

$python = @"
import sys
from pathlib import Path
from PIL import Image

origem = Path(r"$iconeOrigem")
destino = Path(r"$(Join-Path $arvore 'Assets')")
destino.mkdir(parents=True, exist_ok=True)

if not origem.is_file():
    print(f"AVISO: {origem} nao existe; os tiles ficarao sem icone proprio")
    sys.exit(0)

# Nome do arquivo -> (largura, altura)
tiles = {
    "StoreLogo.png": (50, 50),
    "Square44x44Logo.png": (44, 44),
    "Square71x71Logo.png": (71, 71),
    "Square150x150Logo.png": (150, 150),
    "Square310x310Logo.png": (310, 310),
    "Wide310x150Logo.png": (310, 150),
}

# Variantes sem placa: o Windows desenha o icone direto, sem o quadrado de
# fundo que ele poe por padrao. Sem elas, a barra de tarefas mostra o EdgeMD
# num retangulo azul.
alvos = [44, 150]

with Image.open(origem) as base:
    base = base.convert("RGBA")
    for nome, (largura, altura) in tiles.items():
        if largura == altura:
            quadro = base.resize((largura, altura), Image.LANCZOS)
        else:
            # O tile widescreen tem outro formato; o icone entra centralizado
            # sobre fundo transparente, em vez de esticado.
            quadro = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
            lado = altura
            encaixado = base.resize((lado, lado), Image.LANCZOS)
            quadro.paste(encaixado, ((largura - lado) // 2, 0), encaixado)
        quadro.save(destino / nome, "PNG")

    for alvo in alvos:
        variante = base.resize((alvo, alvo), Image.LANCZOS)
        for sufixo in (f"Square{alvo}x{alvo}Logo.targetsize-{alvo}.png",
                       f"Square{alvo}x{alvo}Logo.targetsize-{alvo}_altform-unplated.png"):
            variante.save(destino / sufixo, "PNG")

gerados = sorted(p.name for p in destino.glob('*.png'))
print(f"    {len(gerados)} arquivos de tile")
"@

$python | python -
if ($LASTEXITCODE -ne 0) { throw "falha ao gerar os tiles" }

# ---------------------------------------------------------------------------
# Manifesto
# ---------------------------------------------------------------------------
Write-Host "==> Montando o AppxManifest.xml"
$modelo = Get-Content (Join-Path $PSScriptRoot "AppxManifest.xml") -Raw -Encoding UTF8
$manifesto = $modelo `
    -replace '\{\{IDENTITY_NAME\}\}', [System.Security.SecurityElement]::Escape($IdentityName) `
    -replace '\{\{PUBLISHER\}\}', [System.Security.SecurityElement]::Escape($Publisher) `
    -replace '\{\{PUBLISHER_DISPLAY\}\}', [System.Security.SecurityElement]::Escape($PublisherDisplay) `
    -replace '\{\{VERSION\}\}', $VersaoMsix

# Sem BOM: o makeappx recusa o manifesto com marca de ordem de bytes.
$utf8SemBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText((Join-Path $arvore "AppxManifest.xml"), $manifesto, $utf8SemBom)

Write-Host "    identidade : $IdentityName"
Write-Host "    publisher  : $Publisher"
Write-Host "    versao     : $VersaoMsix"

# ---------------------------------------------------------------------------
# Empacotamento
# ---------------------------------------------------------------------------
Write-Host "==> Empacotando com o makeappx"
if (Test-Path $pacote) { Remove-Item $pacote -Force }

& $makeappx pack /d $arvore /p $pacote /o
if ($LASTEXITCODE -ne 0) { throw "makeappx falhou com codigo $LASTEXITCODE" }

$tamanho = (Get-Item $pacote).Length / 1MB
Write-Host ("    gerado: {0} ({1:N1} MB)" -f $pacote, $tamanho)

# ---------------------------------------------------------------------------
# Assinatura
# ---------------------------------------------------------------------------
if ($SelfSigned) {
    Write-Host "==> Criando certificado autoassinado"

    # O certificado entra em CurrentUser\My para assinar, e a parte publica vai
    # para TrustedPeople — sem isso o Windows recusa instalar o pacote, mesmo
    # numa maquina com modo desenvolvedor ligado.
    $existente = Get-ChildItem Cert:\CurrentUser\My -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -eq $Publisher -and $_.NotAfter -gt (Get-Date) } |
        Select-Object -First 1

    if ($existente) {
        Write-Host "    reaproveitando o certificado existente ($($existente.Thumbprint))"
        $cert = $existente
    }
    else {
        # Criado com .NET em vez do cmdlet New-SelfSignedCertificate: aquele
        # depende do modulo PKI e travou nesta maquina, sem erro e sem timeout.
        # Aqui nao ha dependencia de modulo nenhum.
        $cert = New-EdgeMDCertificado -Assunto $Publisher
        Write-Host "    criado: $($cert.Thumbprint)"
    }

    # O signtool quer um arquivo, e um PFX com senha e o formato que ele aceita
    # de forma consistente. Exportar o .cer (so a parte publica) nao serviria
    # para assinar.
    $senhaDev = "edgemd-dev"
    $pfx = Join-Path $saida "EdgeMD-dev.pfx"
    [System.IO.File]::WriteAllBytes(
        $pfx, $cert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Pfx, $senhaDev))

    $publico = Join-Path $saida "EdgeMD-dev.cer"
    [System.IO.File]::WriteAllBytes(
        $publico, $cert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert))

    Write-Host "    confiando no certificado (TrustedPeople)"
    $lojaConfianca = New-Object System.Security.Cryptography.X509Certificates.X509Store("TrustedPeople", "CurrentUser")
    $lojaConfianca.Open("ReadWrite")
    try {
        $jaConfiavel = $lojaConfianca.Certificates |
            Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
        if (-not $jaConfiavel) {
            $lojaConfianca.Add($cert)
            Write-Host "    adicionado a TrustedPeople"
        }
        else {
            Write-Host "    ja estava em TrustedPeople"
        }
    }
    finally {
        $lojaConfianca.Close()
    }

    $Certificate = $pfx
    $Password = $senhaDev
    $assinarCom = $cert
}
else {
    $assinarCom = $null
}

if ($Certificate) {
    if (-not $signtool) { throw "signtool.exe nao encontrado; nao da para assinar" }

    Write-Host "==> Assinando"
    $argumentos = @("sign", "/fd", "SHA256", "/f", $Certificate)
    if ($Password) { $argumentos += @("/p", $Password) }
    $argumentos += $pacote

    & $signtool @argumentos
    if ($LASTEXITCODE -ne 0) { throw "signtool falhou com codigo $LASTEXITCODE" }

    Write-Host "==> Conferindo a assinatura"
    & $signtool verify /pa /v $pacote | Select-String -Pattern "Successfully verified|Hash of file|Issued to" |
        ForEach-Object { "    $_" }
}
else {
    Write-Host ""
    Write-Host "AVISO: o pacote NAO foi assinado, entao nao podera ser instalado." -ForegroundColor Yellow
    Write-Host "       Use -SelfSigned para testar, ou -Certificate com um .pfx proprio."
}

Write-Host ""
Write-Host "Pronto: $pacote"
if ($Certificate) {
    Write-Host "Instale com:  Add-AppxPackage '$pacote'"
}
