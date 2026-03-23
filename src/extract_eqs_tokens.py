import json
import os
from pathlib import Path
import time

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


if __name__ == "__main__":
    login = os.getenv("EQS_LOGIN")
    password = os.getenv("EQS_PASSWORD")

    if not login or not password:
        raise SystemExit(
            "Defina as variáveis de ambiente EQS_LOGIN e EQS_PASSWORD antes de executar o script."
        )

    extracted = extract_tokens(login=login, password=password)
    save_outputs(extracted)
