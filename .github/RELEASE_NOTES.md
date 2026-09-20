# EdgeMD 0.1.0

Leitor e editor de Markdown para Windows, Linux e macOS. Abre lendo, e entra em
edição com um clique.

## Downloads

| Sistema | Arquivo | Como instalar |
|---|---|---|
| **Windows** 10/11 | `EdgeMD-0.1.0-setup.exe` | Execute o instalador. Instala só para o seu usuário — não pede administrador. |
| **Windows** — pacote MSIX | `EdgeMD-0.1.0-x64.msix` + `EdgeMD-dev.cer` | Confie no certificado (exige administrador) e depois instale. Veja abaixo. |
| **Linux** — Debian, Ubuntu, Mint | `edgemd_0.1.0_amd64.deb` | `sudo apt install ./edgemd_0.1.0_amd64.deb` |
| **Linux** — qualquer distro | `EdgeMD-0.1.0-x86_64.AppImage` | `chmod +x EdgeMD-0.1.0-x86_64.AppImage` e execute |
| **macOS** 11+ | `EdgeMD-0.1.0.dmg` | Abra e arraste o EdgeMD para Aplicativos |

No Windows, **prefira o `.exe`**: não exige assinatura nem administrador. O MSIX
dá instalação e desinstalação mais limpas, mas o Windows só instala um pacote
cujo certificado seja confiável na máquina — e o deste release é autoassinado,
de desenvolvimento:

```powershell
Import-Certificate -FilePath EdgeMD-dev.cer -CertStoreLocation Cert:\LocalMachine\TrustedPeople
Add-AppxPackage EdgeMD-0.1.0-x64.msix
```

Sem esse passo o Windows recusa com o erro `0x800B0109`. Confiar apenas no
usuário atual não basta: o AppX exige confiança em nível de máquina.

Os arquivos têm entre 128 e 191 MB porque carregam o Chromium inteiro dentro
(≈500 MB descompactados). É o preço da renderização fiel: diagramas Mermaid,
fórmulas KaTeX e o CSS do preview funcionam **sem internet**, porque tudo viaja
dentro do executável.

## O que tem nesta versão

**Leitura**

- Modo de leitura como padrão — a edição é sob demanda, com um clique
- Diagramas [Mermaid](https://mermaid.js.org) e fórmulas KaTeX, com ou sem internet
- Realce de sintaxe, tabelas, listas de tarefas, notas de rodapé e citações
- Barra lateral com árvore de arquivos da pasta aberta

**Edição**

- Abas, com marca de alteração não salva
- Localizar e substituir (`Ctrl+F`, `Ctrl+H`), com as ocorrências destacadas
- Inserção de link, imagem e emoji — 376 emojis com busca em português
- Modelos para novos arquivos, editáveis como qualquer `.md`
- Gravação atômica: nunca deixa o arquivo pela metade
- Preserva encoding (UTF-8/UTF-16/Windows-1252) e fim de linha

**Sistema**

- Tema claro e escuro em todo o aplicativo, seguindo o sistema por padrão
- Instância única: dez cliques duplos, uma janela
- Ícone na bandeja, com aviso de alterações pendentes
- Exportação para HTML autônomo e PDF
- Associação de `.md` nas três plataformas, sem administrador

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
