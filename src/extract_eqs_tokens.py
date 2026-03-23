import json
import os
from pathlib import Path

import pandas as pd
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from seleniumwire import webdriver
from webdriver_manager.chrome import ChromeDriverManager

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

    service = Service(ChromeDriverManager().install())
    seleniumwire_options = {
        "request_storage": "memory",
        "request_storage_max_size": 200,
    }
    return webdriver.Chrome(
        service=service,
        options=chrome_options,
        seleniumwire_options=seleniumwire_options,
    )


def extract_tokens(login: str, password: str) -> dict:
    driver = build_driver()
    token = ido = cookie = None

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

        WebDriverWait(driver, 30).until(
            lambda drv: any(REQUEST_URL_FRAGMENT in req.url for req in drv.requests)
        )

        for request in driver.requests:
            if REQUEST_URL_FRAGMENT in request.url:
                headers = request.headers
                token = headers.get("Authorization") or headers.get("authorization")
                ido = headers.get("ido") or headers.get("Ido") or headers.get("IDO")
                cookie = headers.get("Cookie") or headers.get("cookie")
                print("Requisição alvo encontrada. Headers capturados.")
                break

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
