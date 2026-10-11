# -*- coding: utf-8 -*-
import os
import sys
import time
import traceback
import subprocess

if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

os.makedirs("logs", exist_ok=True)


def _write_crash(prefix: str = "") -> None:
    path = os.path.join("logs", "error.txt")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 72 + "\n")
        f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
        if prefix:
            f.write(prefix + "\n")
        traceback.print_exc(file=f)
    print("Падение записано в logs\\error.txt", file=sys.stderr)


def _ensure_deps() -> None:
    try:
        import requests  # noqa: F401
        return
    except Exception:
        pass
    req = os.path.join(os.getcwd(), "requirements.txt")
    log_path = os.path.join("logs", "pip_install.txt")
    cmd = [sys.executable, "-m", "pip", "install", "-r", req]
    with open(log_path, "a", encoding="utf-8") as log:
        log.write("\n%s auto-install\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        core = [
            sys.executable, "-m", "pip", "install",
            "requests", "urllib3", "pyTelegramBotAPI", "beautifulsoup4",
            "colorama", "psutil", "requests-toolbelt", "python-dotenv", "pysocks",
        ]
        subprocess.check_call(core)


try:
    _ensure_deps()
except Exception:
    _write_crash("Не удалось поставить пакеты Python")
    raise

import Utils.cardinal_tools
import Utils.config_loader as cfg_loader
from first_setup import first_setup
from Utils.logger import configure_logging
from Utils.brand import APP_NAME, VERSION
from Utils.console_ui import enable_windows_console, print_splash
import logging
import colorama
from cardinal import Cardinal
import Utils.exceptions as excs
from locales.localizer import Localizer

def print_banner() -> None:
    print_splash("main")


Utils.cardinal_tools.set_console_title(f"{APP_NAME} v{VERSION}")

if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(__file__))

folders = ["configs", "logs", "storage", "storage/cache", "storage/plugins", "storage/products", "plugins"]
for i in folders:
    if not os.path.exists(i):
        os.makedirs(i)

files = ["configs/auto_delivery.cfg", "configs/auto_response.cfg"]
for i in files:
    if not os.path.exists(i):
        with open(i, "w", encoding="utf-8") as f:
            pass

enable_windows_console()
colorama.init(autoreset=False, convert=True)
configure_logging()


def _excepthook(exc_type, exc, tb):
    try:
        path = os.path.join("logs", "error.txt")
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 72 + "\n")
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
            traceback.print_exception(exc_type, exc, tb, file=f)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = _excepthook
logging.raiseExceptions = False
logger = logging.getLogger("main")
logger.debug("------------------------------------------------------------------")

print_banner()

if not os.path.exists("configs/_main.cfg"):
    first_setup()
    sys.exit()

if sys.platform == "linux" and os.getenv("FPC_IS_RUNNIG_AS_SERVICE", "0") == "1":
    import getpass
    pid = str(os.getpid())
    pidFile = open(f"/run/FunPayCardinal/{getpass.getuser()}/FunPayCardinal.pid", "w")
    pidFile.write(pid)
    pidFile.close()
    logger.info(f"$GREENPID файл создан, PID процесса: {pid}")

try:
    logger.info("$MAGENTAЗагружаю конфиг _main.cfg...")
    MAIN_CFG = cfg_loader.load_main_config("configs/_main.cfg")
    localizer = Localizer(MAIN_CFG["Other"]["language"])
    _ = localizer.translate

    logger.info("$MAGENTAЗагружаю конфиг auto_response.cfg...")
    AR_CFG = cfg_loader.load_auto_response_config("configs/auto_response.cfg")
    RAW_AR_CFG = cfg_loader.load_raw_auto_response_config("configs/auto_response.cfg")

    logger.info("$MAGENTAЗагружаю конфиг auto_delivery.cfg...")
    AD_CFG = cfg_loader.load_auto_delivery_config("configs/auto_delivery.cfg")
except excs.ConfigParseError as e:
    logger.error(e)
    logger.error("Завершаю программу...")
    time.sleep(5)
    sys.exit()
except UnicodeDecodeError:
    logger.error("Произошла ошибка при расшифровке UTF-8. Убедитесь, что кодировка файла = UTF-8, "
                 "а формат конца строк = LF.")
    logger.error("Завершаю программу...")
    time.sleep(5)
    sys.exit()
except Exception:
    logger.critical("Произошла непредвиденная ошибка.")
    logger.warning("TRACEBACK", exc_info=True)
    logger.error("Завершаю программу...")
    time.sleep(5)
    sys.exit()

localizer = Localizer(MAIN_CFG["Other"]["language"])

logger.info("$GREENконфиги готовы  ·  поднимаю FunPay и Telegram")

try:
    Cardinal(MAIN_CFG, AD_CFG, AR_CFG, RAW_AR_CFG, VERSION).init().run()
except KeyboardInterrupt:
    logger.info("Завершаю программу...")
    sys.exit()
except Exception:
    logger.critical("При работе Кардинала произошла необработанная ошибка.")
    logger.warning("TRACEBACK", exc_info=True)
    logger.critical("Завершаю программу...")
    _write_crash("Необработанная ошибка Cardinal")
    time.sleep(5)
    sys.exit()
