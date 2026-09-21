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
    [string]$OutputDirectory = "dist\msix",
    # Confia no certificado de desenvolvimento tambem na maquina, e nao so no
    # usuario. Exige administrador, e existe por dois motivos: a instalacao de
    # um MSIX pelo AppX so aceita certificado confiavel em nivel de maquina, e
    # o signtool verify so aprova a cadeia se o certificado estiver numa raiz
    # confiavel. Num runner de CI, que e descartavel, isso e inofensivo; numa
    # maquina de trabalho, nao deve acontecer sem querer.
    [switch]$TrustMachine
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

function Test-SdkTool {
    <#
    .SINOPSE
        Confere que a ferramenta existe E executa.

    .DESCRICAO
        A checagem por presenca nao basta. O makeappx depende de um assembly
        lado-a-lado que fica na pasta do SDK: copiar o .exe para outro lugar o
        deixa presente e quebrado, e o erro so aparece quando ele e executado:

            The application has failed to start because its side-by-side
            configuration is incorrect.

        Executar aqui e o que distingue "esta la" de "funciona". O makeappx sem
        argumentos imprime o cabecalho e sai com codigo diferente de zero, o
        que e esperado; o que reprova e nao conseguir iniciar.
    #>
    param([string]$Caminho)

    if (-not $Caminho -or -not (Test-Path $Caminho)) { return $false }

    # O $ErrorActionPreference = "Stop" deste script faz o PowerShell tratar
    # qualquer escrita em stderr de um programa externo como erro terminal.
    # O makeappx escreve o uso em stdout, mas o signtool escreve em stderr —
    # então sem baixar a preferência aqui, o signtool seria reprovado mesmo
    # funcionando. Foi o que aconteceu na primeira versão desta função.
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # Out-String junta stdout e stderr: qual dos dois traz o texto do uso
        # varia entre as ferramentas do SDK.
        $saida = & $Caminho 2>&1 | Out-String
    }
    catch {
        return $false
    }
    finally {
        $ErrorActionPreference = $anterior
    }

    return ($saida -match 'MakeAppx|SignTool|Usage')
}

function Find-SdkTool {
    param([string]$Nome)

    # A ordem importa. O PATH vem primeiro porque foi o usuario que o montou.
    # Em seguida as pastas do SDK, que e onde a ferramenta funciona: ela precisa
    # dos assemblies que ficam ao lado. A pasta local vem por ultimo, porque um
    # .exe copiado para la pode estar quebrado — foi o que aconteceu na CI, e
    # por isso cada candidato e testado antes de ser aceito.
    $candidatos = @()

    $noPath = Get-Command $Nome -ErrorAction SilentlyContinue
    if ($noPath) { $candidatos += $noPath.Source }

    $kits = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path $kits) {
        # Da versao mais recente para a mais antiga.
        Get-ChildItem $kits -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { $candidatos += (Join-Path $_.FullName "x64\$Nome.exe") }
    }
    $candidatos += "${env:ProgramFiles(x86)}\Windows Kits\10\bin\x64\$Nome.exe"
    $candidatos += "$env:ProgramFiles\Windows Kits\10\bin\x64\$Nome.exe"
    $candidatos += (Join-Path $env:LOCALAPPDATA "edgemd-sdktools\$Nome.exe")

    foreach ($caminho in $candidatos) {
        if (Test-SdkTool -Caminho $caminho) { return $caminho }
    }

    # Nenhum funcionou. Se algum existe mas nao roda, dizemos isso, porque a
    # mensagem "nao encontrado" mandaria o usuario procurar no lugar errado.
    $existeMasNaoRoda = $candidatos | Where-Object { $_ -and (Test-Path $_) }
    if ($existeMasNaoRoda) {
        Write-Host "    AVISO: $Nome existe mas nao executa em:" -ForegroundColor Yellow
        $existeMasNaoRoda | Select-Object -First 3 | ForEach-Object { Write-Host "      $_" }
        Write-Host "    (copia-lo para fora da pasta do SDK quebra os assemblies)" -ForegroundColor Yellow
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
    $lojas = @(@{ Nome = "TrustedPeople"; Escopo = "CurrentUser" })

    if ($TrustMachine) {
        # Nivel de maquina. Faz diferenca por dois motivos, os dois verificados
        # na pratica: o AppX so instala um MSIX cujo certificado seja confiavel
        # na maquina (CurrentUser da erro 0x800B0109), e o signtool verify so
        # aprova a cadeia se o certificado estiver numa raiz confiavel.
        $admin = ([Security.Principal.WindowsPrincipal] `
            [Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

        if (-not $admin) {
            throw "-TrustMachine exige administrador, e o processo atual nao esta elevado."
        }
        $lojas += @{ Nome = "TrustedPeople"; Escopo = "LocalMachine" }
        $lojas += @{ Nome = "Root"; Escopo = "LocalMachine" }
    }

    foreach ($loja in $lojas) {
        $store = New-Object System.Security.Cryptography.X509Certificates.X509Store(
            $loja.Nome, $loja.Escopo)
        $store.Open("ReadWrite")
        try {
            $jaConfiavel = $store.Certificates |
                Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
            if (-not $jaConfiavel) {
                $store.Add($cert)
                Write-Host "    adicionado a $($loja.Escopo)\$($loja.Nome)"
            }
            else {
                Write-Host "    ja estava em $($loja.Escopo)\$($loja.Nome)"
            }
        }
        catch {
            # A loja Root do usuario pede confirmacao interativa, e num contexto
            # sem interface isso vira excecao. Nao e fatal: sem ela a assinatura
            # continua valida, so a conferencia da cadeia falha.
            Write-Host "    nao foi possivel gravar em $($loja.Escopo)\$($loja.Nome): $($_.Exception.Message)" -ForegroundColor Yellow
        }
        finally {
            $store.Close()
        }
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

    # O signtool escreve mensagens em stderr mesmo quando da tudo certo — o
    # "SignTool Error:" da conferencia da cadeia e o caso mais visivel. Com o
    # $ErrorActionPreference = "Stop" deste script, isso vira excecao terminal e
    # interrompe o script antes de a mensagem poder ser avaliada. Por isso as
    # duas chamadas ao signtool rodam com a preferencia baixada.
    function Invoke-SignTool {
        param([string[]]$Argumentos)
        $anterior = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            return (& $signtool @Argumentos 2>&1 | Out-String)
        }
        finally {
            $ErrorActionPreference = $anterior
        }
    }

    Write-Host "==> Assinando"
    $argumentos = @("sign", "/fd", "SHA256", "/f", $Certificate)
    if ($Password) { $argumentos += @("/p", $Password) }
    $argumentos += $pacote

    $saidaSign = Invoke-SignTool $argumentos
    if ($saidaSign -notmatch 'Successfully signed|Number of files successfully Signed') {
        throw "o signtool nao conseguiu assinar:`n$($saidaSign.Trim())"
    }
    Write-Host "    assinado"

    # A conferencia distingue dois casos que o signtool reporta igual no codigo
    # de saida, mas que sao bem diferentes:
    #
    #   * a cadeia nao termina numa raiz confiavel — esperado num certificado
    #     autoassinado, e nao significa que a assinatura esteja errada;
    #   * qualquer outro erro — assinatura ausente, arquivo alterado depois de
    #     assinar, algoritmo invalido. Isso e falha de verdade.
    Write-Host "==> Conferindo a assinatura"
    $texto = Invoke-SignTool @("verify", "/pa", "/v", $pacote)

    $cadeiaNaoConfiavel = $texto -match 'terminated in a root|not trusted'
    $temAssinatura = $texto -match 'Issued to:'
    $aprovada = $texto -match 'Successfully verified'

    if ($aprovada) {
        Write-Host "    verificada" -ForegroundColor Green
    }
    elseif ($temAssinatura -and $cadeiaNaoConfiavel) {
        Write-Host "    assinatura presente; cadeia autoassinada, que e o esperado" -ForegroundColor Yellow
        Write-Host "    sem certificado de autoridade certificadora, /pa nao aprova a cadeia" -ForegroundColor Yellow
        if ($TrustMachine) {
            Write-Host "    ATENCAO: -TrustMachine foi usado e a cadeia ainda nao valida" -ForegroundColor Yellow
        }
    }
    else {
        throw "a assinatura do pacote nao pode ser conferida:`n$($texto.Trim())"
    }
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
