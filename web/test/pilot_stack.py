"""Run the browser checks against a disposable database in the local Compose stack."""

import os
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from contextlib import ExitStack, closing
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
PYTHON = ROOT / ".venv/bin/python"
DOCKER = ["docker", "compose", "exec", "-T", "db"]


def port():
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return str(sock.getsockname()[1])


def wait_ready(process, url):
    for _ in range(160):
        if process.poll() is not None:
            raise RuntimeError(f"Local server exited before serving {url}")
        try:
            with urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(0.15)
    raise RuntimeError(f"Local service did not respond at {url}")


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    db = "cre_browser_" + uuid.uuid4().hex
    subprocess.run(
        ["docker", "compose", "up", "-d", "--wait", "db"], cwd=ROOT, check=True
    )
    with ExitStack() as stack:
        subprocess.run(
            DOCKER + ["createdb", "-U", "cre_owner", db], cwd=ROOT, check=True
        )
        stack.callback(
            subprocess.run,
            DOCKER + ["dropdb", "-U", "cre_owner", db],
            cwd=ROOT,
            check=True,
        )
        temp = Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix="cre-browser-"))
        )
        runtime, worker, owner = [
            "postgresql+psycopg://cre_"
            + role
            + ":local-"
            + role
            + "@127.0.0.1:55439/"
            + db
            for role in ["runtime", "worker", "owner"]
        ]
        api_port = web_port = port()
        while web_port == api_port:
            web_port = port()
        environment = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("CRE_", "OPENAI_", "AWS_"))
        }
        environment.update(
            CRE_DEMO_MODE="true",
            CRE_MIGRATION_URL=owner,
            DATABASE_URL=runtime,
            CRE_WORKER_URL=worker,
            CRE_STORAGE_DIR=str(temp / "objects"),
            CRE_RESEARCH_PROVIDER="disabled",
            CRE_API_URL=f"http://127.0.0.1:{api_port}",
            CRE_WEB_TEST_URL=f"http://127.0.0.1:{web_port}",
            NEXT_TELEMETRY_DISABLED="1",
        )
        if os.getenv("CRE_TEST_BROWSER_CHANNEL"):
            environment["CRE_TEST_BROWSER_CHANNEL"] = os.environ[
                "CRE_TEST_BROWSER_CHANNEL"
            ]

        def run(*args, env=environment, cwd=ROOT):
            subprocess.run(args, cwd=cwd, env=env, check=True)

        run(str(ROOT / ".venv/bin/alembic"), "upgrade", "head")
        run(str(PYTHON), "-m", "cre.admin", "grant")
        run(str(PYTHON), "-m", "cre.admin", "demo")
        run(
            str(PYTHON),
            "-m",
            "cre.ingestion",
            "demo",
            "--count",
            "6",
            env={**environment, "DATABASE_URL": owner},
        )
        run("npm", "run", "build", cwd=WEB)

        def start(*args, cwd=ROOT, env=environment):
            proc = subprocess.Popen(args, cwd=cwd, env=env)
            stack.callback(stop, proc)
            return proc

        api = start(str(PYTHON), "-m", "uvicorn", "cre.main:app", "--port", api_port)
        wait_ready(api, environment["CRE_API_URL"] + "/health/ready")
        start(
            str(PYTHON),
            "-m",
            "cre.workflows.worker",
            env={**environment, "DATABASE_URL": worker},
        )
        # Use the same standalone + static layout as the production web container.
        bundle = temp / "web"
        shutil.copytree(WEB / ".next/standalone", bundle)
        shutil.copytree(
            WEB / ".next/static", bundle / ".next/static", dirs_exist_ok=True
        )
        web = start(
            "node",
            "server.js",
            cwd=bundle,
            env={**environment, "PORT": web_port, "HOSTNAME": "127.0.0.1"},
        )
        wait_ready(web, environment["CRE_WEB_TEST_URL"] + "/config")
        run("npm", "run", "test:browser", cwd=WEB)


if __name__ == "__main__":
    main()
