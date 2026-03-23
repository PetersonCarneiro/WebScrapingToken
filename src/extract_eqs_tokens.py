import base64
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


# ============================================================
# UTILITÁRIOS DE LOG
# ============================================================

def print_banner(title: str, icon: str = "ℹ", width: int = 70) -> None:
    separator = "=" * width
    print(f"\n{separator}")
    print(f"{icon} {title}")
    print(separator)


def print_step(message: str) -> None:
    print(f"► {message}")


def print_success(message: str) -> None:
    print(f"✔ {message}")


def print_warning(message: str) -> None:
    print(f"⚠ {message}")


def print_error(message: str) -> None:
    print(f"✖ {message}")


def mask_value(value: str | None, visible_chars: int = 50) -> str:
    if not value:
        return "ausente"
    if len(value) <= visible_chars:
        return value
    return f"{value[:visible_chars]}..."


# ============================================================
# UTILITÁRIOS DE TOKEN / TEMPO
# ============================================================

def extract_token_expiration(token: str) -> int | None:
    if not token:
        return None

    token_parts = token.split(".")
    if len(token_parts) != 3:
        return None

    payload = token_parts[1]
    padding = "=" * (-len(payload) % 4)

    try:
        decoded_payload = base64.urlsafe_b64decode(payload + padding)
        payload_data = json.loads(decoded_payload)
    except (ValueError, json.JSONDecodeError) as exc:
        print_warning(f"Não foi possível decodificar o payload do JWT: {exc}")
        return None

    expiration = payload_data.get("exp")
    if expiration is None:
        return None

    try:
        return int(expiration)
    except (TypeError, ValueError):
        return None


def get_token_status(token: str) -> tuple[bool, int | None]:
    expiration = extract_token_expiration(token)
    if expiration is None:
        return False, None

    remaining_seconds = expiration - int(time.time())
    return remaining_seconds > 0, remaining_seconds


def format_expiration(token_expiration: int | None) -> str:
    if not token_expiration:
        return "não identificada"
    return f"{token_expiration} ({datetime.fromtimestamp(token_expiration, timezone.utc).isoformat()})"


# ============================================================
# SELENIUM / CAPTURA DE REDE
# ============================================================

def build_driver() -> webdriver.Chrome:
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

    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_cdp_cmd("Network.enable", {})
    return driver


def get_matching_request_headers(driver: webdriver.Chrome) -> dict[str, str] | None:
    request_urls: dict[str, str] = {}

    for entry in driver.get_log("performance"):
        message = json.loads(entry["message"])["message"]
        method = message.get("method")
        params = message.get("params", {})
        request_id = params.get("requestId")

        if method == "Network.requestWillBeSent":
            request = params.get("request", {})
            if request_id and request.get("url"):
                request_urls[request_id] = request["url"]
            continue

        if method != "Network.requestWillBeSentExtraInfo":
            continue

        request_url = request_urls.get(request_id, "")
        if REQUEST_URL_FRAGMENT not in request_url:
            continue

        headers = params.get("headers", {})
        associated_cookies = params.get("associatedCookies", [])

        if associated_cookies and "Cookie" not in headers and "cookie" not in headers:
            headers["Cookie"] = "; ".join(
                f"{item['cookie']['name']}={item['cookie']['value']}"
                for item in associated_cookies
                if item.get("cookie")
            )

        return headers

    return None


def wait_for_target_request(driver: webdriver.Chrome, timeout: int = DEFAULT_TIMEOUT) -> dict[str, str]:
    end_time = time.time() + timeout
    while time.time() < end_time:
        headers = get_matching_request_headers(driver)
        if headers:
            return headers
        time.sleep(1)

    raise RuntimeError("Não foi possível localizar a requisição alvo nos logs de rede.")


def navigate_to_target_report(driver: webdriver.Chrome) -> None:
    print_step("Expandindo menu 'Relatórios (CHM)'...")
    relatorios_menu = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
        EC.presence_of_element_located((By.XPATH, "//span[text()='Relatórios (CHM)']/.."))
    )
    driver.execute_script("arguments[0].click();", relatorios_menu)
    print_success("Menu 'Relatórios (CHM)' expandido.")

    print_step("Clicando em 'Itens de LPU Por Local'...")
    lpu_local_menu = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
        EC.presence_of_element_located((By.XPATH, "//span[text()='Itens de LPU Por Local']/.."))
    )
    driver.execute_script("arguments[0].click();", lpu_local_menu)
    print_success("Relatório 'Itens de LPU Por Local' aberto.")


def perform_login(driver: webdriver.Chrome, login: str, password: str) -> None:
    print_step(f"Abrindo página de login: {LOGIN_URL}")
    driver.get(LOGIN_URL)

    print_step("Preenchendo credenciais...")
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "login"))).send_keys(login)
    driver.find_element(By.ID, "senha").send_keys(password)
    print_success("Campos de login preenchidos.")

    print_step("Enviando formulário de login...")
    driver.find_element(By.TAG_NAME, "button").click()

    WebDriverWait(driver, 20).until_not(EC.url_to_be(LOGIN_URL))
    print_success("Login realizado com sucesso.")


def extract_headers_payload(headers: dict[str, str]) -> dict[str, Any]:
    token = headers.get("Authorization") or headers.get("authorization")
    ido = headers.get("ido") or headers.get("Ido") or headers.get("IDO")
    cookie = headers.get("Cookie") or headers.get("cookie")
    token_expiration = extract_token_expiration(token)
    token_valid, remaining_seconds = get_token_status(token) if token else (False, None)

    return {
        "token": token,
        "ido": ido,
        "cookie": cookie,
        "token_expiration": token_expiration,
        "token_valid": token_valid,
        "remaining_seconds": remaining_seconds,
    }


def print_capture_details(data: dict[str, Any]) -> None:
    print_banner("HEADERS CAPTURADOS", icon="🔎")
    print(f"Token:             {mask_value(data.get('token'))}")
    print(f"Ido:               {data.get('ido') or 'ausente'}")
    print(f"Cookie:            {'presente' if data.get('cookie') else 'ausente'}")
    print(f"Expiração JWT:     {format_expiration(data.get('token_expiration'))}")

    remaining_seconds = data.get("remaining_seconds")
    if remaining_seconds is None:
        print("Validade do token: não foi possível validar")
    elif remaining_seconds > 0:
        print(
            "Validade do token: "
            f"válido por mais {remaining_seconds} segundos (~{remaining_seconds // 60} min)"
        )
    else:
        print(f"Validade do token: expirado há {-remaining_seconds} segundos")


# ============================================================
# FLUXO PRINCIPAL
# ============================================================

def extract_tokens(login: str, password: str, max_attempts: int = MAX_ATTEMPTS) -> dict[str, Any]:
    for attempt in range(1, max_attempts + 1):
        driver = None
        print_banner(f"TENTATIVA {attempt}/{max_attempts}", icon="🚀")

        try:
            print_step("Inicializando Chrome headless e habilitando logs de rede...")
            driver = build_driver()
            print_success("Driver inicializado.")

            perform_login(driver, login=login, password=password)
            navigate_to_target_report(driver)

            print_step(
                "Aguardando a requisição alvo nos logs de rede: "
                f".../{REQUEST_URL_FRAGMENT}"
            )
            headers = wait_for_target_request(driver)
            print_success("Requisição alvo encontrada nos logs de rede.")

            data = extract_headers_payload(headers)
            print_capture_details(data)

            if not data["token"] or not data["ido"]:
                raise RuntimeError("Não foi possível capturar token e ido.")

            if not data["token_valid"]:
                raise RuntimeError("O token capturado está inválido ou expirado.")

            print_success("Captura concluída com sucesso.")
            return data

        except Exception as exc:
            print_error(f"Falha na tentativa {attempt}: {exc}")
            if attempt == max_attempts:
                raise RuntimeError(
                    "Todas as tentativas falharam. Verifique credenciais, conectividade e o fluxo da página."
                ) from exc
            print_warning("Nova tentativa será iniciada em instantes...")
            time.sleep(2)
        finally:
            if driver:
                driver.quit()
                print_step("Driver encerrado.")

    raise RuntimeError("Fluxo encerrado sem retorno de dados.")


def save_outputs(data: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print_banner("SALVANDO ARQUIVOS", icon="💾")
    print_step(f"Garantindo diretório de saída: {OUTPUT_DIR}")

    df = pd.DataFrame(
        {
            "Token": [data["token"]],
            "Ido": [data["ido"]],
            "Cookie": [data.get("cookie")],
            "TokenExpiracao": [data.get("token_expiration")],
        }
    )
    df.to_excel(OUTPUT_XLSX, index=False)
    OUTPUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print_success(f"Excel salvo em: {OUTPUT_XLSX}")
    print_success(f"JSON salvo em: {OUTPUT_JSON}")

    if is_google_drive_upload_configured():
        print_step("Configuração de upload para Google Drive detectada.")
        upload_excel_to_google_drive(OUTPUT_XLSX)
    else:
        print_warning("Upload para Google Drive não configurado; salvando apenas localmente.")

    print_summary(data)


def is_google_drive_upload_configured() -> bool:
    return bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") and os.getenv("GOOGLE_DRIVE_FOLDER_ID"))


def upload_excel_to_google_drive(file_path: Path) -> None:
    folder_id = os.environ["GOOGLE_DRIVE_FOLDER_ID"]
    service = build_google_drive_service(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    existing_file_id = find_existing_drive_file_id(
        service=service,
        folder_id=folder_id,
        file_name=file_path.name,
    )

    media = MediaFileUpload(
        str(file_path),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        resumable=False,
    )

    if existing_file_id:
        service.files().update(
            fileId=existing_file_id,
            media_body=media,
        ).execute()
        print_success(f"Arquivo atualizado no Google Drive: {file_path.name}")
        return

    service.files().create(
        body={
            "name": file_path.name,
            "parents": [folder_id],
        },
        media_body=media,
        fields="id",
    ).execute()
    print_success(f"Arquivo enviado ao Google Drive: {file_path.name}")


def build_google_drive_service(service_account_json: str) -> Any:
    credentials_info = json.loads(service_account_json)
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=GOOGLE_DRIVE_SCOPES,
    )
    return build("drive", "v3", credentials=credentials)


def find_existing_drive_file_id(service: Any, folder_id: str, file_name: str) -> str | None:
    response = service.files().list(
        q=(
            f"'{folder_id}' in parents and name = '{file_name}' "
            "and trashed = false"
        ),
        spaces="drive",
        fields="files(id, name)",
        pageSize=1,
    ).execute()
    files = response.get("files", [])
    if not files:
        return None
    return files[0]["id"]


def print_summary(data: dict[str, Any]) -> None:
    print_banner("RESUMO FINAL", icon="📋")
    print(f"Token:             {mask_value(data.get('token'))}")
    print(f"Ido:               {data.get('ido')}")
    print(f"Cookie:            {'presente' if data.get('cookie') else 'ausente'}")
    print(f"Expiração JWT:     {format_expiration(data.get('token_expiration'))}")
    print(f"Arquivo Excel:     {OUTPUT_XLSX}")
    print(f"Arquivo JSON:      {OUTPUT_JSON}")


def main() -> None:
    login = os.getenv("EQS_LOGIN")
    password = os.getenv("EQS_PASSWORD")

    if not login or not password:
        raise SystemExit(
            "Defina as variáveis de ambiente EQS_LOGIN e EQS_PASSWORD antes de executar o script."
        )

    print_banner("AUTOMAÇÃO EQS - CAPTURA DE TOKEN", icon="🤖")
    print_step("Credenciais e ambiente detectados. Iniciando fluxo...")

    try:
        extracted = extract_tokens(login=login, password=password)
        save_outputs(extracted)
        print_success("Fluxo concluído sem erros.")
    except RuntimeError as exc:
        print_error("Tokens não capturados. O arquivo Excel NÃO foi atualizado.")
        print_warning("Revise os logs acima e tente novamente.")
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
