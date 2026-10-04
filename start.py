"""МедМаршрут: demo stand in one command. Synthetic data only; secrets live in memory of this process."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
DEMO = ROOT / "demo_stand"
HOST = "127.0.0.1"
MARKER = ".medmarshrut-stand"
CLINICS = ("clinic-central", "clinic-partner-1", "clinic-partner-2")
SECRET_NAMES = ("PATH_SHARED_SECRET", "PATH_ADMIN_TOKEN", "PATH_PATIENT_TOKEN", "REVIEWER_TOKEN",
                "CLINIC_SHARED_SECRET", "CLINIC_ADMIN_TOKEN", "CLINIC_STAFF_TOKENS")

# Processes of the stand, in start order. Task 02 adds the gateway here.
SERVICES = [
    {"name": "path", "title": "сервис пути", "port": 8765,
     "script": {"demo": "medmarshrut_path_service/service.py", "real": "medmarshrut_path_service/service.py"},
     "env": lambda s, state: {"PATH_SHARED_SECRET": s["PATH_SHARED_SECRET"], "PATH_ADMIN_TOKEN": s["PATH_ADMIN_TOKEN"],
                              "PATH_PATIENT_TOKEN": s["PATH_PATIENT_TOKEN"], "PATH_DB": str(state / "path.sqlite3"),
                              "PATH_RULES": str(DEMO / "rules.demo.json")},
     "pages": ["/staff", "/patient"]},
    {"name": "clinic", "title": "сервис клиники", "port": 8764,
     "script": {"demo": "medmarshrut_clinic_service/service.py", "real": "medmarshrut_clinic_service/service.py"},
     "env": lambda s, state: {"CLINIC_SHARED_SECRET": s["CLINIC_SHARED_SECRET"], "CLINIC_ADMIN_TOKEN": s["CLINIC_ADMIN_TOKEN"],
                              "CLINIC_STAFF_TOKENS": s["CLINIC_STAFF_TOKENS"], "CLINIC_DB": str(state / "clinic.sqlite3"),
                              "CLINIC_NETWORK": str(DEMO / "network.demo.json")},
     "pages": ["/staff"]},
    {"name": "image", "title": "сервис снимков", "port": 8766,
     "script": {"demo": "demo_stand/image_demo_runner.py", "real": "medmarshrut_image_service/service.py"},
     "env": lambda s, state: {"REVIEWER_TOKEN": s["REVIEWER_TOKEN"], "PATH_SHARED_SECRET": s["PATH_SHARED_SECRET"],
                              "ROUTER_URL": "http://127.0.0.1:8765/v1/reports",
                              "DEMO_STUDY_INDEX": str(state / "kit" / "index.json")},
     "pages": []},
]


def say(text: str = "") -> None:
    print(text, flush=True)


def make_secrets() -> dict[str, str]:
    values = {name: secrets.token_urlsafe(32) for name in SECRET_NAMES if name != "CLINIC_STAFF_TOKENS"}
    values["CLINIC_STAFF_TOKENS"] = json.dumps({secrets.token_urlsafe(32): clinic for clinic in CLINICS})
    return values


def base_env(image_mode: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in SECRET_NAMES and k not in {"ENABLE_TEST_BACKEND", "ROUTER_URL", "PATH_DB", "CLINIC_DB",
                                                   "PATH_RULES", "CLINIC_NETWORK", "DEMO_STUDY_INDEX"}}
    if image_mode == "demo":
        env.pop("MODEL_CONFIG", None)
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    return env


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex((HOST, port)) == 0:
            return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            return True
    return False


def prepare_state(state: Path, keep: bool) -> None:
    state = state.resolve()
    if state == ROOT or ROOT in state.parents:
        raise SystemExit(f"Папка состояния {state} лежит внутри репозитория: базы и архивы DICOM попадут в git. "
                         f"Укажите папку вне репозитория в --state-dir.")
    if state.exists() and not keep:
        if any(state.iterdir()) and not (state / MARKER).exists():
            raise SystemExit(f"Папка {state} не похожа на папку стенда, и стенд не будет её очищать. "
                             f"Укажите пустую или новую папку в --state-dir.")
        shutil.rmtree(state)
    (state / "logs").mkdir(parents=True, exist_ok=True)
    (state / MARKER).write_text("Папка состояния демо-стенда МедМаршрута. Её можно удалить.\n", encoding="utf-8")


def tail(path: Path, lines: int = 25) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(журнал пуст)"
    return "\n".join(text[-lines:]) or "(журнал пуст)"


class Stand:
    def __init__(self, state: Path, image_mode: str, values: dict[str, str]):
        self.state, self.image_mode, self.values = state, image_mode, values
        self.procs: list[tuple[dict, subprocess.Popen, Path]] = []

    def tool_env(self) -> dict[str, str]:
        return {**base_env(self.image_mode), **self.values, "DEMO_STATE_DIR": str(self.state),
                "DEMO_IMAGE_MODE": self.image_mode}

    def start(self) -> bool:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        for service in SERVICES:
            err = self.state / "logs" / f"{service['name']}.err.log"
            out = self.state / "logs" / f"{service['name']}.out.log"
            with open(out, "wb") as stdout, open(err, "wb") as stderr:
                proc = subprocess.Popen([sys.executable, "-B", str(ROOT / service["script"][self.image_mode])],
                                        cwd=ROOT, env={**base_env(self.image_mode), **service["env"](self.values, self.state)},
                                        stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, creationflags=flags)
            self.procs.append((service, proc, err))
        for service, proc, err in self.procs:
            if not self.wait_health(service, proc):
                say(f"Не удалось запустить {service['title']} (порт {service['port']}). Последние строки его журнала ошибок:")
                say(tail(err))
                say(f"Полный журнал: {err}")
                return False
            say(f"  {service['title']}: http://{HOST}:{service['port']}")
        return True

    @staticmethod
    def wait_health(service: dict, proc: subprocess.Popen, timeout: float = 20) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return False
            try:
                with urlopen(f"http://{HOST}:{service['port']}/health", timeout=1) as response:
                    if response.status == 200:
                        return True
            except (URLError, OSError):
                pass
            time.sleep(0.2)
        return False

    def run_tool(self, script: str) -> int:
        return subprocess.run([sys.executable, "-B", str(DEMO / script)], cwd=DEMO, env=self.tool_env()).returncode

    def dead(self) -> tuple[dict, Path] | None:
        for service, proc, err in self.procs:
            if proc.poll() is not None:
                return service, err
        return None

    def stop(self) -> None:
        for _, proc, _ in reversed(self.procs):
            if proc.poll() is None:
                proc.terminate()
        for _, proc, _ in self.procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.procs.clear()


def print_secrets(values: dict[str, str]) -> None:
    say("Секреты этого запуска (PowerShell). Живут, пока работает стенд; никому не пересылайте:")
    for name in SECRET_NAMES:
        say(f"$env:{name} = '{values[name]}'")
    say()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Демо-стенд МедМаршрута: три сервиса и учебные данные одной командой.")
    parser.add_argument("--state-dir", type=Path, default=Path(tempfile.gettempdir()) / "medmarshrut-stand",
                        help="папка состояния: базы, учебные архивы, журналы (по умолчанию во временном каталоге)")
    parser.add_argument("--keep", action="store_true", help="не очищать папку состояния; наполнение при этом не запускается")
    parser.add_argument("--no-seed", action="store_true", help="не наполнять стенд учебными случаями")
    parser.add_argument("--smoke", action="store_true", help="чистый стенд, наполнение, смоук-проверка, остановка")
    parser.add_argument("--image", choices=("demo", "real"), default="demo",
                        help="demo — сценарный backend снимков; real — настоящий сервис снимков (MODEL_CONFIG, если задан)")
    parser.add_argument("--print-secrets", action="store_true", help="напечатать секреты для ручной работы с API")
    args = parser.parse_args()
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.default_int_handler)  # Ctrl+Break stops the stand like Ctrl+C
    if args.smoke and (args.keep or args.image == "real"):
        parser.error("--smoke проверяет чистый стенд со сценарным backend: не сочетается с --keep и --image real")

    busy = [s for s in SERVICES if port_busy(s["port"])]
    if busy:
        for service in busy:
            say(f"Порт {service['port']} занят: на нём уже что-то работает (нужен для: {service['title']}).")
        say("Скорее всего, стенд уже запущен в другом окне. Остановите его (Ctrl+C в том окне) или закройте "
            "программу, которая держит порт, и запустите снова.")
        return 1

    state = args.state_dir.resolve()
    prepare_state(state, args.keep)
    kit_index = state / "kit" / "index.json"
    if not kit_index.exists():
        generated = subprocess.run([sys.executable, "-B", str(DEMO / "synthetic_dicom.py"), "--out", str(state / "kit")],
                                   cwd=DEMO, env=base_env(args.image))
        if generated.returncode != 0:
            say("Не удалось сгенерировать учебные исследования. Проверьте, что установлены pydicom и numpy: "
                "python -m pip install -r medmarshrut_image_service/requirements.txt")
            return 1

    values = make_secrets()
    stand = Stand(state, args.image, values)
    mode = "сценарный backend, демо" if args.image == "demo" else "настоящий сервис снимков"
    say(f"Запускаю стенд ({mode}). Папка состояния: {state}")
    try:
        if not stand.start():
            return 1
        if args.print_secrets:
            print_secrets(values)
        if args.keep:
            say("Флаг --keep: базы сохранены, наполнение пропущено. Задания сервиса снимков живут в памяти "
                "и после перезапуска пропали; studies.json мог устареть.")
        elif not args.no_seed:
            say("Наполняю стенд учебными случаями…")
            if stand.run_tool("seed.py") != 0:
                say("Наполнение не прошло: подробности выше.")
                if args.smoke:
                    return 1
        if args.smoke:
            say("Запускаю смоук-проверку…")
            return stand.run_tool("smoke.py")
        say()
        for service in SERVICES:
            for page in service["pages"]:
                say(f"  встроенная страница ({service['title']}): http://{HOST}:{service['port']}{page}")
        say("Стенд работает. Остановить — Ctrl+C.")
        while True:
            time.sleep(0.5)
            failed = stand.dead()
            if failed:
                service, err = failed
                say(f"{service['title']} неожиданно остановился. Последние строки журнала ошибок:")
                say(tail(err))
                return 1
    except KeyboardInterrupt:
        say("\nОстанавливаю стенд…")
        return 0
    finally:
        stand.stop()


if __name__ == "__main__":
    sys.exit(main())
