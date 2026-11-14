## Downloads

Confira a integridade com o `SHA256SUMS.txt` anexo: `sha256sum -c SHA256SUMS.txt` (Linux/macOS) ou `Get-FileHash` no PowerShell.

| Sistema | Arquivo | Como instalar |
|---|---|---|
| **Windows** 10/11 | `EdgeMD-{{VERSAO}}-setup.exe` | Execute o instalador. Instala só para o seu usuário — não pede administrador. |
| **Windows** — pacote MSIX | `EdgeMD-{{VERSAO}}-x64.msix` + `EdgeMD-dev.cer` | Confie no certificado (exige administrador) e depois instale. Veja abaixo. |
| **Linux** — Debian, Ubuntu, Mint | `edgemd_{{VERSAO}}_amd64.deb` | `sudo apt install ./edgemd_{{VERSAO}}_amd64.deb` |
| **Linux** — qualquer distro | `EdgeMD-{{VERSAO}}-x86_64.AppImage` | `chmod +x EdgeMD-{{VERSAO}}-x86_64.AppImage` e execute |
| **macOS** 11+ | `EdgeMD-{{VERSAO}}.dmg` | Abra e arraste o EdgeMD para Aplicativos |

No Windows, **prefira o `.exe`**: não exige assinatura nem administrador. O MSIX
dá instalação e desinstalação mais limpas, mas o Windows só instala um pacote
cujo certificado seja confiável na máquina — e o deste release é autoassinado,
de desenvolvimento:

```powershell
Import-Certificate -FilePath EdgeMD-dev.cer -CertStoreLocation Cert:\LocalMachine\TrustedPeople
Add-AppxPackage EdgeMD-{{VERSAO}}-x64.msix
```

Sem esse passo o Windows recusa com o erro `0x800B0109`. Confiar apenas no
usuário atual não basta: o AppX exige confiança em nível de máquina.

Os arquivos têm entre 128 e 191 MB porque carregam o Chromium inteiro dentro
(≈500 MB descompactados). É o preço da renderização fiel: diagramas Mermaid,
fórmulas KaTeX e o CSS do preview funcionam **sem internet**, porque tudo viaja
dentro do executável.

## Um aviso honesto sobre assinaturas

Nem o `.exe` nem o `.dmg` são assinados — não tenho certificado de
desenvolvedor. Na prática:

- **Windows**: o SmartScreen vai avisar que o programa é de editor desconhecido.
  Clique em "Mais informações" → "Executar assim mesmo".
- **macOS**: o Gatekeeper vai bloquear na primeira abertura. Use Ajustes →
  Privacidade e Segurança → "Abrir assim mesmo", ou clique com o botão direito
  no app → Abrir.
- **Linux**: nenhum aviso; os pacotes se instalam normalmente.

## Requisitos

- Windows 10 ou 11, Linux x86-64, ou macOS 11 ou superior
- Uma GPU com driver minimamente atualizado (o Chromium usa aceleração quando
  disponível e cai para software quando não há)
