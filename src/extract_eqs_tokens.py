import base64
import json
import os
from pathlib import Path
import time
from importlib import import_module, util
from typing import Any

import pandas as pd
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
DEFAULT_GOOGLE_DRIVE_DIR = Path("/content/drive/My Drive/BI-Qlik")


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
    token_expiracao = get_token_expiration(data["token"])

    df = pd.DataFrame(
        {
            "Token": [data["token"]],
            "Ido": [data["ido"]],
            "Cookie": [data.get("cookie")],
            "TokenExpiracao": [token_expiracao],
        }
    )
    df.to_excel(OUTPUT_XLSX, index=False)
    OUTPUT_JSON.write_text(
        json.dumps(
            {
                **data,
                "token_expiracao": token_expiracao,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Arquivos salvos em: {OUTPUT_XLSX} e {OUTPUT_JSON}")

    google_drive_dir = get_google_drive_dir()
    if google_drive_dir:
        save_excel_to_google_drive(df, google_drive_dir)

    print("\n" + "=" * 55)
    print("  RESUMO")
    print("=" * 55)
    print(f"  Token:          {data['token'][:50]}...")
    print(f"  Ido:            {data['ido']}")
    print(f"  Cookie:         {'presente' if data.get('cookie') else 'ausente'}")
    print(f"  Expira em (Unix): {token_expiracao}")
    print("=" * 55)


def get_google_drive_dir() -> Path | None:
    google_drive_dir = os.getenv("GOOGLE_DRIVE_DIR")
    if google_drive_dir:
        return Path(google_drive_dir).expanduser()

    mount_google_drive_if_available()

    if DEFAULT_GOOGLE_DRIVE_DIR.parent.exists():
        return DEFAULT_GOOGLE_DRIVE_DIR

    return None


def mount_google_drive_if_available() -> None:
    if not is_google_colab_available():
        return

    print("\n► Montando o Google Drive...")
    drive_module: Any = import_module("google.colab.drive")
    drive_module.mount("/content/drive")


def is_google_colab_available() -> bool:
    return util.find_spec("google.colab") is not None


def save_excel_to_google_drive(df: pd.DataFrame, google_drive_dir: Path) -> None:
    file_path = google_drive_dir / OUTPUT_XLSX.name
    google_drive_dir.mkdir(parents=True, exist_ok=True)

    if file_path.exists():
        file_path.unlink()
        print(f"► Arquivo anterior removido: {file_path}")

    df.to_excel(file_path, index=False)
    print(f"✔ Tokens salvos em: {file_path}")


def get_token_expiration(token_header: str) -> int | None:
    token = token_header.removeprefix("Bearer ").strip()
    parts = token.split(".")
    if len(parts) != 3:
        return None

    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded_payload = json.loads(
            base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8")
        )
    except (ValueError, json.JSONDecodeError):
        return None

    return decoded_payload.get("exp")


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
