import base64
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

LOGIN_URL = "https://eqs.arenanet.com.br/dist/#/login"
REQUEST_URL_FRAGMENT = "chamado/rel-reembolsavel-chamado-estacao/listar"
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
OUTPUT_XLSX = OUTPUT_DIR / "Eqs_Tokens.xlsx"
OUTPUT_JSON = OUTPUT_DIR / "Eqs_Tokens.json"
GOOGLE_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT = 30

# Lê credenciais do ambiente (evita hardcode de usuário/senha no código).
login = os.getenv("EQS_LOGIN")
password = os.getenv("EQS_PASSWORD")

if not login or not password:
    raise SystemExit("Defina EQS_LOGIN e EQS_PASSWORD antes de executar o script.")

print("\n" + "=" * 70)
print("🤖 AUTOMAÇÃO EQS - CAPTURA DE TOKEN")
print("=" * 70)

captured_data = None
last_error = None

# Repete o fluxo inteiro até MAX_ATTEMPTS vezes para lidar com falhas transitórias.
for attempt in range(1, MAX_ATTEMPTS + 1):
    driver = None
    # Mapa requestId -> URL para associar os headers extraídos no evento ExtraInfo.
    request_urls = {}

    print("\n" + "=" * 70)
    print(f"🚀 Tentativa {attempt}/{MAX_ATTEMPTS}")
    print("=" * 70)

    try:
        # Configuração base do Chrome em modo headless para execução em servidor/CI.
        chrome_options = Options()
        for arg in [
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1920,1080",
        ]:
            chrome_options.add_argument(arg)

        chrome_binary = os.getenv("CHROME_BINARY")
        if chrome_binary:
            chrome_options.binary_location = chrome_binary

        chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

        chromedriver_path = os.getenv("CHROMEDRIVER_PATH")
        service = Service(chromedriver_path) if chromedriver_path else None

        print("► Inicializando Chrome...")
        driver = webdriver.Chrome(service=service, options=chrome_options)
        # Habilita captura de eventos de rede para ler headers de requisições.
        driver.execute_cdp_cmd("Network.enable", {})

        # 1) Login na aplicação.
        print(f"► Abrindo login: {LOGIN_URL}")
        driver.get(LOGIN_URL)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "login"))).send_keys(login)
        driver.find_element(By.ID, "senha").send_keys(password)
        driver.find_element(By.TAG_NAME, "button").click()
        WebDriverWait(driver, 20).until_not(EC.url_to_be(LOGIN_URL))
        print("✔ Login OK")

        # 2) Navega até a tela que dispara a requisição com token/ido.
        print("► Abrindo menu de relatório...")
        relatorios_menu = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
            EC.presence_of_element_located((By.XPATH, "//span[text()='Relatórios (CHM)']/.."))
        )
        driver.execute_script("arguments[0].click();", relatorios_menu)

        lpu_local_menu = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
            EC.presence_of_element_located((By.XPATH, "//span[text()='Itens de LPU Por Local']/.."))
        )
        driver.execute_script("arguments[0].click();", lpu_local_menu)
        print("✔ Relatório aberto")

        # 3) Faz polling dos logs de performance até achar a requisição alvo.
        print(f"► Buscando headers da URL com trecho: {REQUEST_URL_FRAGMENT}")
        end_time = time.time() + DEFAULT_TIMEOUT
        headers = None

        while time.time() < end_time and not headers:
            for entry in driver.get_log("performance"):
                message = json.loads(entry["message"])["message"]
                method = message.get("method")
                params = message.get("params", {})
                request_id = params.get("requestId")

                if method == "Network.requestWillBeSent":
                    request = params.get("request", {})
                    url = request.get("url")
                    if request_id and url:
                        request_urls[request_id] = url
                    continue

                if method != "Network.requestWillBeSentExtraInfo":
                    continue

                request_url = request_urls.get(request_id, "")
                if REQUEST_URL_FRAGMENT not in request_url:
                    continue

                # Captura headers completos da requisição de interesse.
                headers = params.get("headers", {})
                associated_cookies = params.get("associatedCookies", [])

                # Alguns cenários trazem cookie separado; unifica no header Cookie.
                if associated_cookies and "Cookie" not in headers and "cookie" not in headers:
                    headers["Cookie"] = "; ".join(
                        f"{item['cookie']['name']}={item['cookie']['value']}"
                        for item in associated_cookies
                        if item.get("cookie")
                    )
                break

            if not headers:
                time.sleep(1)

        if not headers:
            raise RuntimeError("Não encontrou a requisição alvo nos logs de rede.")

        token = headers.get("Authorization") or headers.get("authorization")
        ido = headers.get("ido") or headers.get("Ido") or headers.get("IDO")
        cookie = headers.get("Cookie") or headers.get("cookie")

        if not token or not ido:
            raise RuntimeError("Não foi possível capturar token e ido.")

        token_parts = token.split(".")
        token_expiration = None

        # JWT: decodifica o payload (parte 2) e extrai claim 'exp' se existir.
        if len(token_parts) == 3:
            payload = token_parts[1]
            padding = "=" * (-len(payload) % 4)
            try:
                payload_data = json.loads(base64.urlsafe_b64decode(payload + padding))
                if payload_data.get("exp") is not None:
                    token_expiration = int(payload_data["exp"])
            except Exception:
                token_expiration = None

        remaining_seconds = None
        token_valid = False
        # Considera válido apenas se houver exp e ela estiver no futuro.
        if token_expiration:
            remaining_seconds = token_expiration - int(time.time())
            token_valid = remaining_seconds > 0

        if not token_valid:
            raise RuntimeError("Token inválido ou expirado.")

        print("\n" + "=" * 70)
        print("🔎 HEADERS CAPTURADOS")
        print("=" * 70)
        print(f"Token:             {token[:50] + '...' if len(token) > 50 else token}")
        print(f"Ido:               {ido}")
        print(f"Cookie:            {'presente' if cookie else 'ausente'}")
        print(
            "Expiração JWT:     "
            f"{token_expiration} ({datetime.fromtimestamp(token_expiration, timezone.utc).isoformat()})"
        )
        print(
            f"Validade do token: válido por mais {remaining_seconds} segundos "
            f"(~{remaining_seconds // 60} min)"
        )

        captured_data = {
            "token": token,
            "ido": ido,
            "cookie": cookie,
            "token_expiration": token_expiration,
            "token_valid": token_valid,
            "remaining_seconds": remaining_seconds,
        }

        print("✔ Captura concluída")
        break

    except Exception as exc:
        last_error = exc
        print(f"✖ Falha na tentativa {attempt}: {exc}")
        if attempt < MAX_ATTEMPTS:
            print("⚠ Nova tentativa em 2 segundos...")
            time.sleep(2)
    finally:
        if driver:
            driver.quit()
            print("► Driver encerrado")

if not captured_data:
    raise SystemExit(f"Todas as tentativas falharam: {last_error}")

# Salva resultado local (sempre), mesmo quando upload do Drive estiver desligado.
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

df = pd.DataFrame(
    {
        "Token": [captured_data["token"]],
        "Ido": [captured_data["ido"]],
        "Cookie": [captured_data.get("cookie")],
        "TokenExpiracao": [captured_data.get("token_expiration")],
    }
)
df.to_excel(OUTPUT_XLSX, index=False)
OUTPUT_JSON.write_text(json.dumps(captured_data, ensure_ascii=False, indent=2), encoding="utf-8")

print("\n" + "=" * 70)
print("💾 ARQUIVOS SALVOS")
print("=" * 70)
print(f"✔ Excel: {OUTPUT_XLSX}")
print(f"✔ JSON:  {OUTPUT_JSON}")

service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

# Upload é opcional: só executa quando JSON da conta e pasta estão definidos.
if service_account_json and folder_id:
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(service_account_json),
        scopes=GOOGLE_DRIVE_SCOPES,
    )
    drive = build("drive", "v3", credentials=credentials)

    response = drive.files().list(
        q=f"'{folder_id}' in parents and name = '{OUTPUT_XLSX.name}' and trashed = false",
        spaces="drive",
        fields="files(id, name)",
        pageSize=1,
    ).execute()

    media = MediaFileUpload(
        str(OUTPUT_XLSX),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        resumable=False,
    )

    files = response.get("files", [])
    # Atualiza se já existir arquivo com mesmo nome; senão cria novo.
    if files:
        drive.files().update(fileId=files[0]["id"], media_body=media).execute()
        print(f"✔ Google Drive: arquivo atualizado ({OUTPUT_XLSX.name})")
    else:
        drive.files().create(
            body={"name": OUTPUT_XLSX.name, "parents": [folder_id]},
            media_body=media,
            fields="id",
        ).execute()
        print(f"✔ Google Drive: arquivo enviado ({OUTPUT_XLSX.name})")
else:
    print("⚠ Upload Google Drive não configurado")

print("\n" + "=" * 70)
print("📋 RESUMO FINAL")
print("=" * 70)
print(f"Token:             {captured_data['token'][:50] + '...' if len(captured_data['token']) > 50 else captured_data['token']}")
print(f"Ido:               {captured_data['ido']}")
print(f"Cookie:            {'presente' if captured_data.get('cookie') else 'ausente'}")
print(
    "Expiração JWT:     "
    f"{captured_data['token_expiration']} "
    f"({datetime.fromtimestamp(captured_data['token_expiration'], timezone.utc).isoformat()})"
)
print(f"Arquivo Excel:     {OUTPUT_XLSX}")
print(f"Arquivo JSON:      {OUTPUT_JSON}")
print("✔ Fluxo concluído sem erros")
