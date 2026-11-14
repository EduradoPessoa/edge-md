# Contribuindo com o EdgeMD

## Reportar problemas e sugerir ideias

Abra uma [issue](https://github.com/EduradoPessoa/edge-md/issues/new/choose) usando um dos formulários.
Procure antes se já existe uma igual. Perguntas de uso vão em
[Discussions](https://github.com/EduradoPessoa/edge-md/discussions).
Falhas de segurança: veja [SECURITY.md](SECURITY.md).

## Ambiente de desenvolvimento

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .[dev]
python tools/fetch_vendor.py
python tools/make_icons.py
python -m pytest tests/ -q
```

## Fluxo de trabalho

1. Parta de uma issue (ou abra uma).
2. Crie uma branch a partir de `main`: `fix/nome-curto` ou `feat/nome-curto`.
3. Faça commits no padrão [Conventional Commits](https://www.conventionalcommits.org/pt-br/):
   `feat: ...`, `fix: ...`, `docs: ...`, `chore: ...`, `ci: ...`, `refactor: ...`, `test: ...`.
   Mudança incompatível: `feat!: ...` ou rodapé `BREAKING CHANGE:`.
4. Abra um Pull Request para `main`. Ninguém comita direto na `main`.
5. A CI precisa passar. No merge (squash), o título do PR vira o commit e entra no changelog.

## Versionamento

[SemVer](https://semver.org/lang/pt-BR/): `fix` → patch, `feat` → minor, mudança incompatível → major.
Versões e `CHANGELOG.md` são gerados a partir dos commits; não edite a versão à mão.

## Como sai uma versão (mantenedor)

1. Cada merge na `main` atualiza o PR **"chore(main): release X.Y.Z"**, aberto pelo release-please.
2. Para publicar, faça o merge desse PR. Como ele é criado com o token do Actions, a CI de testes não roda nele; integre com `gh pr merge <n> --squash --admin`.
3. O merge cria a tag e dispara `release.yml`, que compila os instaladores, gera o `SHA256SUMS.txt` e publica a Release.
