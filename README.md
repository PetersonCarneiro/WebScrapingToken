# WebScrapingToken

Automação em Python para autenticar no portal EQS, monitorar o tráfego de rede do navegador com Selenium 4 e capturar os headers `Authorization`, `ido` e `cookie` da requisição usada pelo relatório **Itens de LPU Por Local**. O projeto também identifica a expiração do JWT, gera saídas em Excel e JSON e, quando configurado, sincroniza o arquivo Excel com o Google Drive.

## Visão geral

Este repositório foi criado para operacionalizar a coleta de credenciais técnicas utilizadas pela aplicação EQS de forma reproduzível e automatizada. A execução ocorre em modo headless com Google Chrome, explorando os logs de rede do Chrome DevTools Protocol expostos pelo Selenium 4.

### O que a automação faz

- realiza login na aplicação EQS com credenciais fornecidas por variáveis de ambiente;
- navega até o menu **Relatórios (CHM)** e abre o relatório **Itens de LPU Por Local**;
- inspeciona os logs de rede até localizar a requisição-alvo;
- extrai os headers `Authorization`, `ido` e `cookie`;
- decodifica o payload do JWT para obter o campo `exp` quando disponível;
- valida se o token ainda está dentro do prazo de expiração;
- salva os dados em `output/Eqs_Tokens.xlsx` e `output/Eqs_Tokens.json`;
- opcionalmente atualiza ou cria o arquivo Excel em uma pasta do Google Drive.

## Arquitetura do projeto

```text
.
├── README.md
├── requirements.txt
└── src/
    └── extract_eqs_tokens.py
```

### Arquivos principais

| Arquivo | Descrição |
| --- | --- |
| `src/extract_eqs_tokens.py` | Script principal responsável pelo login, navegação, captura dos headers, validação do JWT, persistência local e integração com Google Drive. |
| `requirements.txt` | Dependências necessárias para a execução local e em CI. |
| `README.md` | Documentação operacional e técnica do projeto. |

## Requisitos

### Software

- Python 3.12 ou superior;
- Google Chrome instalado;
- ChromeDriver compatível com a versão do Chrome disponível no ambiente;
- acesso à aplicação EQS com permissão para abrir o relatório alvo.

### Dependências Python

Instaladas a partir de `requirements.txt`:

- `pandas`;
- `openpyxl`;
- `selenium`;
- `google-api-python-client`;
- `google-auth`.

## Variáveis de ambiente

### Obrigatórias

| Variável | Finalidade |
| --- | --- |
| `EQS_LOGIN` | Usuário utilizado para autenticação na plataforma EQS. |
| `EQS_PASSWORD` | Senha correspondente ao usuário informado. |

### Opcionais

| Variável | Finalidade |
| --- | --- |
| `OUTPUT_DIR` | Diretório de saída dos arquivos gerados. Padrão: `output`. |
| `CHROME_BINARY` | Caminho explícito para o binário do Google Chrome, útil em ambientes customizados. |
| `CHROMEDRIVER_PATH` | Caminho explícito para o ChromeDriver, caso ele não esteja disponível no `PATH`. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Conteúdo JSON da Service Account usada para autenticação na Google Drive API. |
| `GOOGLE_DRIVE_FOLDER_ID` | ID da pasta de destino no Google Drive para upload do Excel. |

## Como executar localmente

### 1. Criar e ativar o ambiente virtual

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Instalar as dependências

```bash
pip install -r requirements.txt
```

### 3. Exportar as credenciais obrigatórias

```bash
export EQS_LOGIN='seu_login'
export EQS_PASSWORD='sua_senha'
```

### 4. Executar o script

```bash
python src/extract_eqs_tokens.py
```

## Saídas geradas

Ao final de uma execução bem-sucedida, o projeto gera:

- `output/Eqs_Tokens.xlsx`
- `output/Eqs_Tokens.json`

### Estrutura dos dados gravados

O arquivo Excel contém as colunas:

- `Token`
- `Ido`
- `Cookie`
- `TokenExpiracao`

O JSON inclui informações adicionais úteis para diagnóstico:

- `token`
- `ido`
- `cookie`
- `token_expiration`
- `token_valid`
- `remaining_seconds`

## Fluxo operacional

1. O script valida a presença de `EQS_LOGIN` e `EQS_PASSWORD`.
2. O navegador Chrome é iniciado em modo headless com logging de performance habilitado.
3. A automação acessa a tela de login do EQS e envia as credenciais.
4. Após autenticação, o fluxo navega até o relatório **Itens de LPU Por Local**.
5. Os eventos de rede são analisados até encontrar a URL que contém o fragmento `chamado/rel-reembolsavel-chamado-estacao/listar`.
6. Os headers da requisição são consolidados e transformados em payload estruturado.
7. O JWT é decodificado localmente para leitura do campo `exp`.
8. O resultado é salvo em Excel e JSON.
9. Se a integração com Google Drive estiver configurada, o Excel é atualizado ou criado na pasta indicada.

## Integração com Google Drive

O upload é opcional e depende da configuração das variáveis `GOOGLE_SERVICE_ACCOUNT_JSON` e `GOOGLE_DRIVE_FOLDER_ID`.

### Configuração recomendada

1. Crie uma **Service Account** no Google Cloud.
2. Habilite a **Google Drive API** no projeto correspondente.
3. Gere uma chave JSON para a Service Account.
4. Compartilhe a pasta de destino no Google Drive com o e-mail da Service Account com permissão de **Editor**.
5. Armazene o conteúdo completo do JSON na variável `GOOGLE_SERVICE_ACCOUNT_JSON`.
6. Defina o ID da pasta na variável `GOOGLE_DRIVE_FOLDER_ID`.

### Comportamento do upload

- se o arquivo `Eqs_Tokens.xlsx` já existir na pasta informada, ele será atualizado;
- se o arquivo não existir, um novo item será criado;
- o JSON continua sendo salvo apenas localmente.

## Boas práticas de segurança

- nunca versione credenciais reais, cookies ou tokens capturados;
- prefira variáveis de ambiente ou secrets do provedor de CI/CD;
- restrinja o acesso à pasta do Google Drive apenas às contas necessárias;
- trate o arquivo Excel gerado como dado sensível, pois ele pode conter credenciais de acesso temporárias.

## Observações técnicas

- a captura de rede usa os logs do Chrome DevTools via Selenium 4, evitando dependências adicionais como `selenium-wire`;
- o script executa até `3` tentativas por padrão antes de encerrar com erro;
- a validade do token é verificada localmente com base no campo `exp` do JWT;
- o processo falha propositalmente quando não consegue capturar `token` e `ido`, ou quando o token retornado já está inválido/expirado.

## Solução de problemas

### O script não faz login

Verifique:

- se `EQS_LOGIN` e `EQS_PASSWORD` estão corretos;
- se a página de login continua usando os mesmos seletores (`#login`, `#senha` e `button`);
- se há bloqueios de rede, VPN ou MFA que impeçam a automação.

### O relatório não abre ou a navegação falha

Verifique se os textos dos menus permanecem os mesmos na interface:

- `Relatórios (CHM)`
- `Itens de LPU Por Local`

Mudanças no front-end do EQS podem exigir atualização dos seletores XPath.

### A requisição-alvo não é encontrada

Possíveis causas:

- a aplicação alterou o endpoint monitorado;
- a navegação não chegou ao relatório correto;
- a requisição ocorre em outro momento do fluxo e o timeout atual não é suficiente.

### O upload para o Google Drive falha

Confirme:

- se o JSON da Service Account está íntegro;
- se a Google Drive API está habilitada;
- se a pasta foi compartilhada corretamente com a Service Account;
- se o `GOOGLE_DRIVE_FOLDER_ID` pertence à pasta esperada.

## Próximos passos sugeridos

- adicionar testes automatizados para funções puras, como extração e validação do JWT;
- documentar o workflow de GitHub Actions quando ele for versionado neste repositório;
- incluir mascaramento adicional em logs para ambientes compartilhados;
- registrar métricas de execução e falhas para acompanhamento operacional.
