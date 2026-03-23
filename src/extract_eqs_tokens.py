import json
import os
from pathlib import Path
import time
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


def wait_for_target_request(driver: webdriver.Chrome, timeout: int = 30) -> dict[str, str]:
    end_time = time.time() + timeout
    while time.time() < end_time:
        headers = get_matching_request_headers(driver)
        if headers:
            return headers
        time.sleep(1)

    raise RuntimeError("Não foi possível localizar a requisição alvo nos logs de rede.")


def extract_tokens(login: str, password: str) -> dict:
    driver = build_driver()

    try:
        print("Iniciando a automação de login...")
        driver.get(LOGIN_URL)

        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "login"))
        ).send_keys(login)
        driver.find_element(By.ID, "senha").send_keys(password)
        driver.find_element(By.TAG_NAME, "button").click()

        WebDriverWait(driver, 20).until_not(EC.url_to_be(LOGIN_URL))
        print("Login bem-sucedido!")

        relatorios_menu = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, "//span[text()='Relatórios (CHM)']/.."))
        )
        driver.execute_script("arguments[0].click();", relatorios_menu)

        lpu_local_menu = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, "//span[text()='Itens de LPU Por Local']/.."))
        )
        driver.execute_script("arguments[0].click();", lpu_local_menu)

        headers = wait_for_target_request(driver)
        token = headers.get("Authorization") or headers.get("authorization")
        ido = headers.get("ido") or headers.get("Ido") or headers.get("IDO")
        cookie = headers.get("Cookie") or headers.get("cookie")
        print("Requisição alvo encontrada. Headers capturados.")

        if not token or not ido:
            raise RuntimeError("Não foi possível capturar token e ido.")

        return {
            "token": token,
            "ido": ido,
            "cookie": cookie,
        }
    finally:
        driver.quit()
        print("Automação finalizada.")


def save_outputs(data: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(
        {
            "Token": [data["token"]],
            "Ido": [data["ido"]],
            "Cookie": [data.get("cookie")],
        }
    )
    df.to_excel(OUTPUT_XLSX, index=False)
    OUTPUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Arquivos salvos em: {OUTPUT_XLSX} e {OUTPUT_JSON}")

    if is_google_drive_upload_configured():
        upload_excel_to_google_drive(OUTPUT_XLSX)

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
        print(f"✔ Arquivo atualizado no Google Drive: {file_path.name}")
        return

    service.files().create(
        body={
            "name": file_path.name,
            "parents": [folder_id],
        },
        media_body=media,
        fields="id",
    ).execute()
    print(f"✔ Arquivo enviado ao Google Drive: {file_path.name}")


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


def print_summary(data: dict) -> None:
    print("\n" + "=" * 55)
    print("  RESUMO")
    print("=" * 55)
    print(f"  Token:          {data['token'][:50]}...")
    print(f"  Ido:            {data['ido']}")
    print(f"  Cookie:         {'presente' if data.get('cookie') else 'ausente'}")
    print("=" * 55)


if __name__ == "__main__":
    login = os.getenv("EQS_LOGIN")
    password = os.getenv("EQS_PASSWORD")

    if not login or not password:
        raise SystemExit(
            "Defina as variáveis de ambiente EQS_LOGIN e EQS_PASSWORD antes de executar o script."
        )

    try:
        extracted = extract_tokens(login=login, password=password)
        save_outputs(extracted)
    except RuntimeError as exc:
        print("\n✖ Tokens não capturados. O arquivo Excel NÃO foi atualizado.")
        print("  Verifique os logs acima e tente novamente.")
        raise SystemExit(str(exc))
