# WebScrepingToken

Automação em Python para capturar os headers `Authorization`, `ido` e `cookie` da aplicação EQS usando Selenium 4 com logs de rede do Chrome DevTools. O script também extrai o tempo de expiração do token JWT (`exp`) e salva o resultado em Excel e JSON localmente e, no GitHub Actions, também no Google Drive via Service Account.

## Arquivos principais

- `src/extract_eqs_tokens.py`: executa o login, navega até o relatório e captura os headers da requisição alvo.
- `.github/workflows/extract-eqs-tokens.yml`: workflow para rodar manualmente ou em agenda no GitHub Actions.
- `requirements.txt`: dependências Python necessárias para a automação.

## Secrets necessários no GitHub

No repositório do GitHub, configure estes secrets:

- `EQS_LOGIN`
- `EQS_PASSWORD`
- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `GOOGLE_DRIVE_FOLDER_ID`

## Como funciona no GitHub Actions

1. Faz checkout do repositório.
2. Configura Python 3.12.
3. Instala o Google Chrome.
4. Instala as dependências do projeto.
5. Executa `python src/extract_eqs_tokens.py`.
6. Publica a pasta `output/` como artifact do workflow.

## Execução local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export EQS_LOGIN='seu_login'
export EQS_PASSWORD='sua_senha'
python src/extract_eqs_tokens.py
```

Os arquivos gerados ficarão em `output/Eqs_Tokens.xlsx` e `output/Eqs_Tokens.json`.

O Excel passa a incluir as colunas:

- `Token`
- `Ido`
- `Cookie`
- `TokenExpiracao` (timestamp Unix em segundos, lido do campo `exp` do JWT quando disponível)

### Salvando também no Google Drive pelo GitHub Actions

Para enviar o Excel gerado para o Google Drive a partir do GitHub Actions:

1. Crie uma **Service Account** no Google Cloud.
2. Ative a **Google Drive API** no projeto.
3. Gere uma chave JSON da Service Account.
4. Compartilhe a pasta do Drive com o e-mail da Service Account com permissão de **Editor**.
5. Salve o conteúdo completo do JSON no secret `GOOGLE_SERVICE_ACCOUNT_JSON`.
6. Salve o ID da pasta do Drive no secret `GOOGLE_DRIVE_FOLDER_ID`.

Quando esses dois secrets estiverem configurados, o script procura um arquivo chamado `Eqs_Tokens.xlsx` dentro da pasta informada:

- se já existir, ele atualiza o arquivo;
- se não existir, ele cria um novo.

O JSON continua sendo salvo localmente em `output/Eqs_Tokens.json`.

## Observações

- O script continua funcionando mesmo sem os secrets do Google Drive; nesse caso ele salva apenas em `output/`.
- O script usa os logs de rede expostos pelo Chrome DevTools via Selenium 4, evitando a dependência de `selenium-wire` e o erro de `pkg_resources` em ambientes com Python 3.12+.
- A expiração do token é extraída localmente a partir do payload do JWT, sem necessidade de chamada adicional à API.
- Para gravar os tokens em outro destino local, altere a variável `OUTPUT_DIR`.
- O upload para o Drive usa Google Drive API com Service Account, o que é compatível com execução não interativa no GitHub Actions.
