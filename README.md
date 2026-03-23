# WebScrepingToken

Automação em Python para capturar os headers `Authorization`, `ido` e `cookie` da aplicação EQS usando Selenium 4 com logs de rede do Chrome DevTools, salvando o resultado em Excel e JSON localmente e, no Colab, também no Google Drive na pasta `BI-Qlik`.

## Arquivos principais

- `src/extract_eqs_tokens.py`: executa o login, navega até o relatório e captura os headers da requisição alvo.
- `.github/workflows/extract-eqs-tokens.yml`: workflow para rodar manualmente ou em agenda no GitHub Actions.
- `requirements.txt`: dependências Python necessárias para a automação.

## Secrets necessários no GitHub

No repositório do GitHub, configure estes secrets:

- `EQS_LOGIN`
- `EQS_PASSWORD`

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

### Salvando também no Google Drive

O script agora segue mais de perto o fluxo original:

1. **No Colab**: se `google.colab` estiver disponível, ele executa `drive.mount('/content/drive')`.
2. Depois grava o Excel em `/content/drive/My Drive/BI-Qlik/Eqs_Tokens.xlsx`.
3. Se já existir um arquivo anterior, ele remove antes de salvar o novo.
4. O Excel inclui as colunas `Token`, `Ido`, `Cookie` e `TokenExpiracao`.
5. Se quiser usar outra pasta no Drive, defina `GOOGLE_DRIVE_DIR`.

Exemplo no Colab:

```python
from google.colab import drive
drive.mount('/content/drive')
```

Exemplo com variável de ambiente:

```bash
export GOOGLE_DRIVE_DIR='/content/drive/MyDrive/minha-pasta'
python src/extract_eqs_tokens.py
```

## Observações

- O script continua funcionando fora do Colab e fora do Google Drive.
- O script usa os logs de rede expostos pelo Chrome DevTools via Selenium 4, evitando a dependência de `selenium-wire` e o erro de `pkg_resources` em ambientes com Python 3.12+.
- Para gravar os tokens em outro destino local, altere a variável `OUTPUT_DIR`.
- O JSON local também passa a registrar `token_expiracao` para facilitar depuração.
- Se o Google Drive não estiver disponível e `GOOGLE_DRIVE_DIR` não estiver definida, o script salva apenas na pasta local `output/`.
