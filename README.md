# WebScrepingToken

Automação em Python para capturar os headers `Authorization`, `ido` e `cookie` da aplicação EQS usando Selenium 4 com logs de rede do Chrome DevTools, salvando o resultado em Excel e JSON para uso no GitHub Actions.

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

## Observações

- O script não depende de `google.colab` nem de Google Drive.
- O script usa os logs de rede expostos pelo Chrome DevTools via Selenium 4, evitando a dependência de `selenium-wire` e o erro de `pkg_resources` em ambientes com Python 3.12+.
- Para gravar os tokens em outro destino, altere a variável `OUTPUT_DIR`.
- Se quiser persistir os arquivos em outra plataforma, você pode consumir o artifact do workflow ou adicionar um passo extra para upload.
