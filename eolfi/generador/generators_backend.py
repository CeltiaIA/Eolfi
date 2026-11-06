"""Backends FastAPI y Express con persistencia y autenticación opcionales.

Opciones de la especificación (spec["options"]):
- db: "memory" (por defecto) o "sqlite". SQLite usa solo la librería estándar
  (`sqlite3` en Python, `node:sqlite` en Node ≥ 22.13): sin dependencias nuevas.
- auth: True para exigir sesión en las escrituras (POST/PUT/DELETE). Registro e
  inicio de sesión con contraseña derivada con PBKDF2-SHA256 (sal aleatoria,
  210 000 iteraciones), tokens aleatorios con caducidad y comparación en tiempo
  constante. Las lecturas siguen siendo públicas.
"""
from __future__ import annotations

import json
import re
from typing import Any

from eolfi.generador.generators import SECURITY_HEADERS, Writer, _write_static_site


def _opts(spec: dict[str, Any]) -> tuple[str, bool]:
    o = spec.get("options") or {}
    return ("sqlite" if o.get("db") == "sqlite" else "memory"), bool(o.get("auth"))


def _ident(r: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", r.lower())


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------
PY_STORE_MEMORY = '''"""Almacén en memoria, seguro entre hilos (se pierde al reiniciar). Usa --db sqlite para persistir."""
from __future__ import annotations

import threading
from itertools import count


class Store:
    def __init__(self, name: str) -> None:
        self.name = name
        self._data: dict[int, dict] = {}
        self._ids = count(1)
        self._lock = threading.Lock()

    def list(self) -> list[dict]:
        with self._lock:
            return list(self._data.values())

    def get(self, item_id: int) -> dict | None:
        with self._lock:
            return self._data.get(item_id)

    def create(self, data: dict) -> dict:
        with self._lock:
            item = {"id": next(self._ids), **data}
            self._data[item["id"]] = item
            return item

    def update(self, item_id: int, data: dict) -> dict | None:
        with self._lock:
            if item_id not in self._data:
                return None
            self._data[item_id] = {"id": item_id, **data}
            return self._data[item_id]

    def delete(self, item_id: int) -> bool:
        with self._lock:
            return self._data.pop(item_id, None) is not None

    def empty(self) -> bool:
        with self._lock:
            return not self._data
'''

PY_STORE_SQLITE = '''"""Persistencia en SQLite (librería estándar). Ruta: variable APP_DB (por defecto data/app.db)."""
from __future__ import annotations

import os
import re
import sqlite3
import threading
from pathlib import Path

# Único lock (reentrante) para TODA la conexión compartida: almacén y autenticación.
_lock = threading.RLock()


def db_path() -> str:
    return os.environ.get("APP_DB", str(Path(__file__).resolve().parent.parent / "data" / "app.db"))


def connect() -> sqlite3.Connection:
    path = db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    """Conexión única; la primera vez aplica las migraciones pendientes (migrations/)."""
    global _conn
    with _lock:
        if _conn is None:
            from app.migrate import apply

            c = connect()
            apply(c)
            _conn = c
    return _conn


class Store:
    """Una tabla por recurso; el nombre de tabla está validado (nunca viene del usuario)."""

    def __init__(self, name: str) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", name):
            raise ValueError(f"nombre de tabla inválido: {name}")
        self.table = "res_" + name     # prefijo: nunca choca con las tablas de autenticación
        conn()                         # crea/migra el esquema si hace falta (la tabla la define migrations/)

    @staticmethod
    def _row(r: sqlite3.Row | None) -> dict | None:
        return None if r is None else {"id": r["id"], "name": r["name"], "description": r["description"]}

    def list(self) -> list[dict]:
        with _lock:
            return [self._row(r) for r in conn().execute(f"SELECT * FROM {self.table} ORDER BY id")]

    def get(self, item_id: int) -> dict | None:
        with _lock:
            return self._row(conn().execute(f"SELECT * FROM {self.table} WHERE id = ?", (item_id,)).fetchone())

    def create(self, data: dict) -> dict:
        with _lock:
            cur = conn().execute(f"INSERT INTO {self.table} (name, description) VALUES (?, ?)",
                                 (data["name"], data.get("description")))
            conn().commit()
            new_id = cur.lastrowid
        return self.get(new_id)

    def update(self, item_id: int, data: dict) -> dict | None:
        with _lock:
            cur = conn().execute(f"UPDATE {self.table} SET name = ?, description = ? WHERE id = ?",
                                 (data["name"], data.get("description"), item_id))
            conn().commit()
            if not cur.rowcount:
                return None
        return self.get(item_id)

    def delete(self, item_id: int) -> bool:
        with _lock:
            cur = conn().execute(f"DELETE FROM {self.table} WHERE id = ?", (item_id,))
            conn().commit()
            return cur.rowcount > 0

    def empty(self) -> bool:
        with _lock:
            return conn().execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()[0] == 0
'''

PY_AUTH = '''"""Autenticación: registro, inicio de sesión y token Bearer para las escrituras.

- Contraseñas: PBKDF2-SHA256, sal aleatoria de 16 bytes, 210 000 iteraciones.
- Tokens: 32 bytes aleatorios, caducan a las 12 h; se guarda solo su hash SHA-256.
- Comparaciones en tiempo constante.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import OrderedDict

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

ITERATIONS = 210_000
TOKEN_TTL = 12 * 3600
router = APIRouter(prefix="/api/auth", tags=["auth"])
_lock = threading.Lock()
{backend}


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=200, pattern=r"^[^@\\s]+@[^@\\s]+$")
    password: str = Field(min_length=8, max_length=200)


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS).hex()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


MAX_FAILURES = 5
FAILURE_WINDOW = 15 * 60
IP_LIMIT = 30            # peticiones de registro/inicio de sesión por IP y minuto (cada una cuesta un PBKDF2)
IP_WINDOW = 60
MAX_TRACKED = 10_000     # tope de correos/IP recordados: los más antiguos se olvidan (LRU)
_failures: OrderedDict[str, list[float]] = OrderedDict()
_ip_hits: OrderedDict[str, list[float]] = OrderedDict()
_failures_lock = threading.Lock()


def _touch(store: OrderedDict, key: str, window: float, now: float) -> list[float]:
    recent = [t for t in store.pop(key, []) if now - t < window]
    store[key] = recent
    while len(store) > MAX_TRACKED:
        store.popitem(last=False)
    return recent


def limit_ip(request: Request) -> None:
    """Ventana deslizante por IP para /register y /login."""
    ip = request.client.host if request.client else "?"
    now = time.time()
    with _failures_lock:
        hits = _touch(_ip_hits, ip, IP_WINDOW, now)
        if len(hits) >= IP_LIMIT:
            raise HTTPException(status_code=429, detail="Demasiadas peticiones: espera un minuto",
                                headers={"Retry-After": str(IP_WINDOW)})
        hits.append(now)


def _email(data: Credentials) -> str:
    return data.email.strip().lower()


def _too_many_failures(email: str) -> bool:
    now = time.time()
    with _failures_lock:
        return len(_touch(_failures, email, FAILURE_WINDOW, now)) >= MAX_FAILURES


def _record_failure(email: str, ok: bool) -> None:
    with _failures_lock:
        if ok:
            _failures.pop(email, None)
        else:
            _touch(_failures, email, FAILURE_WINDOW, time.time()).append(time.time())


@router.post("/register", status_code=status.HTTP_201_CREATED, dependencies=[Depends(limit_ip)])
def register(data: Credentials) -> dict:
    # Misma respuesta si el correo ya existía: no se revela qué correos están registrados.
    salt = secrets.token_bytes(16)
    _create_user(_email(data), salt.hex(), _hash_password(data.password, salt))
    return {"email": _email(data)}


@router.post("/login", dependencies=[Depends(limit_ip)])
def login(data: Credentials) -> dict:
    if _too_many_failures(_email(data)):
        raise HTTPException(status_code=429, detail="Demasiados intentos: espera unos minutos")
    user = _get_user(_email(data))
    # Se calcula el hash aunque el usuario no exista, para no revelar qué correos están registrados.
    salt = bytes.fromhex(user["salt"]) if user else b"\\x00" * 16
    ok = hmac.compare_digest(_hash_password(data.password, salt), user["password"] if user else "0" * 64)
    _record_failure(_email(data), bool(user and ok))
    if not user or not ok:
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")
    token = secrets.token_urlsafe(32)
    _save_token(_token_hash(token), user["email"], time.time() + TOKEN_TTL)
    return {"token": token, "expires_in": TOKEN_TTL}


def require_user(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Inicia sesión para hacer cambios",
                            headers={"WWW-Authenticate": "Bearer"})
    email = _check_token(_token_hash(authorization[7:].strip()))
    if not email:
        raise HTTPException(status_code=401, detail="Sesión caducada o inválida",
                            headers={"WWW-Authenticate": "Bearer"})
    return email


@router.get("/me")
def me(email: str = Depends(require_user)) -> dict:
    return {"email": email}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(email: str = Depends(require_user), authorization: str | None = Header(default=None)) -> None:
    _delete_token(_token_hash((authorization or "")[7:].strip()))
'''

PY_AUTH_MEMORY = '''
_users: dict[str, dict] = {}
_tokens: dict[str, tuple[str, float]] = {}


def _create_user(email: str, salt: str, password: str) -> bool:
    with _lock:
        if email in _users:
            return False
        _users[email] = {"email": email, "salt": salt, "password": password}
        return True


def _get_user(email: str) -> dict | None:
    with _lock:
        return _users.get(email)


def _save_token(token_hash: str, email: str, expires: float) -> None:
    with _lock:
        _tokens[token_hash] = (email, expires)


def _delete_token(token_hash: str) -> None:
    with _lock:
        _tokens.pop(token_hash, None)
        now = time.time()
        for k in [k for k, (_e, exp) in _tokens.items() if exp < now]:
            _tokens.pop(k, None)   # purga de tokens caducados


def _check_token(token_hash: str) -> str | None:
    with _lock:
        hit = _tokens.get(token_hash)
        if not hit or hit[1] < time.time():
            _tokens.pop(token_hash, None)
            return None
        return hit[0]
'''

PY_AUTH_SQLITE = '''
import sqlite3

from app.store import _lock, conn   # mismo lock que el almacén: commits sin mezclar transacciones

conn()   # las tablas auth_users y auth_tokens las crea la migración inicial


def _create_user(email: str, salt: str, password: str) -> bool:
    with _lock:
        try:
            conn().execute("INSERT INTO auth_users (email, salt, password) VALUES (?, ?, ?)", (email, salt, password))
            conn().commit()
            return True
        except sqlite3.IntegrityError:
            return False


def _get_user(email: str) -> dict | None:
    with _lock:
        r = conn().execute("SELECT email, salt, password FROM auth_users WHERE email = ?", (email,)).fetchone()
        return dict(r) if r else None


def _save_token(token_hash: str, email: str, expires: float) -> None:
    with _lock:
        conn().execute("DELETE FROM auth_tokens WHERE expires < ?", (time.time(),))
        conn().execute("INSERT INTO auth_tokens (token_hash, email, expires) VALUES (?, ?, ?)", (token_hash, email, expires))
        conn().commit()


def _delete_token(token_hash: str) -> None:
    with _lock:
        conn().execute("DELETE FROM auth_tokens WHERE token_hash = ? OR expires < ?", (token_hash, time.time()))
        conn().commit()


def _check_token(token_hash: str) -> str | None:
    with _lock:
        r = conn().execute("SELECT email, expires FROM auth_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
        return r["email"] if r and r["expires"] >= time.time() else None
'''


PY_MIGRATE = '"""Migraciones de esquema SQLite (sin dependencias).\n\n    python -m app.migrate            aplica las pendientes\n    python -m app.migrate status     lista aplicadas y pendientes\n    python -m app.migrate new NOMBRE crea migrations/NNNN_nombre.sql vacía\n\nCada archivo migrations/NNNN_*.sql se aplica una vez, en orden y dentro de una\ntransacción. Se guarda su huella SHA-256: si se edita una migración ya aplicada,\nse avisa (crea una nueva en lugar de modificar la antigua).\n"""\nfrom __future__ import annotations\n\nimport hashlib\nimport os\nimport re\nimport sqlite3\nimport sys\nfrom pathlib import Path\n\nMIGRATIONS = Path(os.environ.get("APP_MIGRATIONS", Path(__file__).resolve().parent.parent / "migrations"))\n_FILE = re.compile(r"^(\\d{4})_[a-z0-9_]+\\.sql$")\n\n\nclass MigrationError(RuntimeError):\n    pass\n\n\ndef _files() -> list[Path]:\n    files = sorted(f for f in MIGRATIONS.glob("*.sql") if _FILE.match(f.name))\n    seen: dict[str, str] = {}\n    for f in files:\n        if f.name[:4] in seen:\n            raise MigrationError(f"Número de migración repetido: {seen[f.name[:4]]} y {f.name}")\n        seen[f.name[:4]] = f.name\n    return files\n\n\ndef _checksum(sql: str) -> str:\n    # Sin depender de CRLF/LF (git autocrlf en Windows no debe parecer una edición).\n    return hashlib.sha256(sql.replace("\\r\\n", "\\n").encode("utf-8")).hexdigest()\n\n\ndef _applied(conn: sqlite3.Connection) -> dict[str, str]:\n    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, name TEXT NOT NULL, "\n                 "checksum TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")\n    conn.commit()\n    return {v: c for v, c in conn.execute("SELECT version, checksum FROM schema_migrations")}\n\n\ndef apply(conn: sqlite3.Connection) -> list[str]:\n    applied = _applied(conn)\n    done = []\n    for f in _files():\n        version = f.name[:4]\n        sql = f.read_text(encoding="utf-8")\n        checksum = _checksum(sql)\n        if re.search(r"^\\s*(BEGIN|COMMIT|ROLLBACK)\\b", sql, re.I | re.M):\n            raise MigrationError(f"{f.name}: no uses BEGIN/COMMIT; cada migración ya va en su transacción")\n        if version in applied:\n            if applied[version] != checksum:\n                raise MigrationError(f"La migración {f.name} cambió después de aplicarse: crea una nueva en lugar de editarla")\n            continue\n        try:\n            conn.executescript("BEGIN;\\n" + sql + "\\n;INSERT INTO schema_migrations (version, name, checksum) "\n                               f"VALUES (\'{version}\', \'{f.name}\', \'{checksum}\');\\nCOMMIT;")\n        except sqlite3.Error as exc:\n            if conn.in_transaction:\n                conn.execute("ROLLBACK")\n            raise MigrationError(f"Falló {f.name}: {exc}") from exc\n        done.append(f.name)\n    return done\n\n\ndef status(conn: sqlite3.Connection) -> list[tuple[str, bool]]:\n    applied = _applied(conn)\n    return [(f.name, f.name[:4] in applied) for f in _files()]\n\n\ndef new(name: str) -> Path:\n    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "cambio"\n    last = max((int(f.name[:4]) for f in _files()), default=0)\n    path = MIGRATIONS / f"{last + 1:04d}_{slug}.sql"\n    path.write_text(f"-- {path.name}: describe aquí el cambio de esquema.\\n"\n                    "-- Ejemplo: ALTER TABLE res_items ADD COLUMN price REAL;\\n", encoding="utf-8")\n    return path\n\n\nif __name__ == "__main__":\n    from app.store import connect\n\n    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"\n    if cmd == "new":\n        print(new(" ".join(sys.argv[2:]) or "cambio"))\n    elif cmd == "status":\n        for name, ok in status(connect()):\n            print(("✓ " if ok else "· ") + name)\n    else:\n        done = apply(connect())\n        print("\\n".join(done) if done else "No hay migraciones pendientes.")\n'


def _initial_migration(resources: list[str], auth: bool) -> str:
    out = ["-- 0001_init.sql: esquema inicial generado por Eolfi. No la edites: crea migraciones nuevas."]
    for r in resources:
        out.append(f"CREATE TABLE res_{_ident(r)} (\n    id INTEGER PRIMARY KEY AUTOINCREMENT,\n    name TEXT NOT NULL,\n"
                   f"    description TEXT,\n    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n);")
    if auth:
        out.append("CREATE TABLE auth_users (\n    email TEXT PRIMARY KEY,\n    salt TEXT NOT NULL,\n    password TEXT NOT NULL\n);")
        out.append("CREATE TABLE auth_tokens (\n    token_hash TEXT PRIMARY KEY,\n    email TEXT NOT NULL,\n    expires REAL NOT NULL\n);")
    return "\n\n".join(out) + "\n"


def gen_fastapi(spec: dict[str, Any], w: Writer) -> None:
    resources = spec["api"]["resources"] or ["items"]
    db, auth = _opts(spec)
    # httpx2: el cliente de pruebas de Starlette 1.x lo pide en lugar de httpx (evita el aviso de obsolescencia).
    w("requirements.txt", "fastapi\nuvicorn[standard]\nhttpx2\npytest\n")
    w("app/__init__.py", "")
    w("app/store.py", PY_STORE_SQLITE if db == "sqlite" else PY_STORE_MEMORY)
    if db == "sqlite":
        w("app/migrate.py", PY_MIGRATE)
        w("migrations/0001_init.sql", _initial_migration(resources, auth))
    w("app/models.py", '''from pydantic import BaseModel, Field


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class Item(ItemIn):
    id: int
''')
    if auth:
        w("app/auth.py", PY_AUTH.replace("{backend}", PY_AUTH_SQLITE if db == "sqlite" else PY_AUTH_MEMORY))
    w("app/routers/__init__.py", "")
    guard_import = "from fastapi import APIRouter, Depends, HTTPException, status\n\nfrom app.auth import require_user\n" \
        if auth else "from fastapi import APIRouter, HTTPException, status\n"
    guard = ", _user: str = Depends(require_user)" if auth else ""
    for r in resources:
        f = _ident(r)
        w(f"app/routers/{f}.py", f'''{guard_import}from app.models import Item, ItemIn
from app.store import Store

router = APIRouter(prefix="/api/{r}", tags=["{r}"])
store = Store("{f}")
if store.empty():
    store.create({{"name": "Primer elemento de {r}", "description": "Dato de ejemplo"}})


@router.get("", response_model=list[Item])
def list_{f}() -> list[dict]:
    return store.list()


@router.post("", response_model=Item, status_code=status.HTTP_201_CREATED)
def create_{f}(data: ItemIn{guard}) -> dict:
    return store.create(data.model_dump())


@router.get("/{{item_id}}", response_model=Item)
def get_{f}(item_id: int) -> dict:
    item = store.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No encontrado")
    return item


@router.put("/{{item_id}}", response_model=Item)
def update_{f}(item_id: int, data: ItemIn{guard}) -> dict:
    item = store.update(item_id, data.model_dump())
    if item is None:
        raise HTTPException(status_code=404, detail="No encontrado")
    return item


@router.delete("/{{item_id}}", status_code=status.HTTP_204_NO_CONTENT)
def delete_{f}(item_id: int{guard}) -> None:
    if not store.delete(item_id):
        raise HTTPException(status_code=404, detail="No encontrado")
''')
    imports = "\n".join(f"from app.routers import {_ident(r)}" for r in resources)
    includes = "\n".join(f"app.include_router({_ident(r)}.router)" for r in resources)
    w("app/main.py", f'''"""API de {spec["title"]}. Arranque: uvicorn app.main:app --reload"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

{"from app import auth" + chr(10) if auth else ""}{imports}

app = FastAPI(title={spec["title"]!r}, version="0.1.0")

SECURITY_HEADERS = {SECURITY_HEADERS!r}


@app.middleware("http")
async def security_headers(request, call_next):
    \"\"\"Cabeceras de seguridad en TODAS las respuestas (API y frontend estático).\"\"\"
    response = await call_next(request)
    for key, value in SECURITY_HEADERS.items():
        # /docs (Swagger) carga recursos de un CDN: se le deja su propia política.
        if key == "Content-Security-Policy" and request.url.path in ("/docs", "/redoc"):
            continue
        response.headers.setdefault(key, value)
    return response

{"app.include_router(auth.router)" + chr(10) if auth else ""}{includes}


@app.get("/api/health")
def health() -> dict:
    return {{"ok": True, "db": {db!r}, "auth": {auth!r}}}


# Frontend estático (debe ir lo último: captura el resto de rutas).
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
''')
    _write_static_site(spec, w, "app/static/", resources)
    first = resources[0]
    w("tests/__init__.py", "")
    w("tests/conftest.py", '''import os
import tempfile

# Base de datos temporal para las pruebas (no toca data/app.db).
os.environ["APP_DB"] = os.path.join(tempfile.mkdtemp(prefix="app-test-"), "test.db")
''')
    auth_helpers = '''

def auth_headers() -> dict:
    client.post("/api/auth/register", json={"email": "ana@example.com", "password": "contraseña-segura"})
    token = client.post("/api/auth/login", json={"email": "ana@example.com", "password": "contraseña-segura"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}
''' if auth else '''

def auth_headers() -> dict:
    return {}
'''
    auth_tests = f'''


def test_writes_require_login():
    assert client.post("/api/{first}", json={{"name": "x"}}).status_code == 401
    assert client.post("/api/{first}", json={{"name": "x"}}, headers={{"Authorization": "Bearer nada"}}).status_code == 401


def test_login_rejects_wrong_password():
    client.post("/api/auth/register", json={{"email": "luis@example.com", "password": "otra-contraseña"}})
    assert client.post("/api/auth/login", json={{"email": "luis@example.com", "password": "mal-contraseña"}}).status_code == 401
    # Registrar de nuevo un correo existente responde igual (sin enumeración) y no cambia la contraseña.
    assert client.post("/api/auth/register", json={{"email": "luis@example.com", "password": "cambiada-123"}}).status_code == 201
    assert client.post("/api/auth/login", json={{"email": "luis@example.com", "password": "cambiada-123"}}).status_code == 401


def test_logout_revokes_token():
    h = auth_headers()
    assert client.get("/api/auth/me", headers=h).status_code == 200
    assert client.post("/api/auth/logout", headers=h).status_code == 204
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_too_many_failures_returns_429():
    client.post("/api/auth/register", json={{"email": "eva@example.com", "password": "contraseña-eva"}})
    codes = [client.post("/api/auth/login", json={{"email": "eva@example.com", "password": "mal-mal-mal"}}).status_code
             for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
''' if auth else ""
    db_tests = f'''


def test_migrations_applied_and_tamper_detected(tmp_path, monkeypatch):
    import shutil
    import sqlite3
    from app import migrate
    from app.store import connect, db_path
    applied = [n for n, ok in migrate.status(connect()) if ok]
    assert "0001_init.sql" in applied
    # Una migración nueva se aplica una sola vez y añade la columna.
    original = migrate.MIGRATIONS
    mig = tmp_path / "migrations"
    shutil.copytree(original, mig)
    monkeypatch.setattr(migrate, "MIGRATIONS", mig)
    (mig / "0002_add_price.sql").write_text("ALTER TABLE res_{_ident(first)} ADD COLUMN price REAL;", encoding="utf-8")
    c = sqlite3.connect(str(tmp_path / "m.db"))
    assert migrate.apply(c) == ["0001_init.sql", "0002_add_price.sql"]
    assert migrate.apply(c) == []
    assert "price" in [r[1] for r in c.execute("PRAGMA table_info(res_{_ident(first)})")]
    (mig / "0001_init.sql").write_text("-- editada", encoding="utf-8")
    try:
        migrate.apply(c)
        raise AssertionError("debía detectar la migración editada")
    except migrate.MigrationError as exc:
        assert "cambió" in str(exc)
    # Una migración con error no deja nada a medias.
    (mig / "0001_init.sql").unlink()
    shutil.copy(original / "0001_init.sql", mig / "0001_init.sql")
    (mig / "0003_roto.sql").write_text("CREATE TABLE nueva (x INT); SELECT * FROM no_existe;", encoding="utf-8")
    try:
        migrate.apply(c)
    except migrate.MigrationError:
        pass
    assert not c.execute("SELECT name FROM sqlite_master WHERE name = 'nueva'").fetchone()


def test_data_persists_in_sqlite():
    import sqlite3
    from app.store import db_path
    h = auth_headers()
    client.post("/api/{first}", json={{"name": "persistente"}}, headers=h)
    rows = sqlite3.connect(db_path()).execute("SELECT name FROM res_{_ident(first)}").fetchall()
    assert ("persistente",) in rows
''' if db == "sqlite" else ""
    w("tests/test_api.py", f'''from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app){auth_helpers}

def test_health():
    assert client.get("/api/health").json()["ok"] is True


def test_crud_{_ident(first)}():
    h = auth_headers()
    created = client.post("/api/{first}", json={{"name": "prueba"}}, headers=h)
    assert created.status_code == 201
    item = created.json()
    assert client.get(f"/api/{first}/{{item['id']}}").json()["name"] == "prueba"
    assert client.put(f"/api/{first}/{{item['id']}}", json={{"name": "cambio"}}, headers=h).json()["name"] == "cambio"
    assert any(i["id"] == item["id"] for i in client.get("/api/{first}").json())
    assert client.delete(f"/api/{first}/{{item['id']}}", headers=h).status_code == 204
    assert client.get(f"/api/{first}/{{item['id']}}").status_code == 404


def test_validation():
    assert client.post("/api/{first}", json={{"name": ""}}, headers=auth_headers()).status_code == 422


def test_frontend():
    r = client.get("/")
    assert r.status_code == 200 and "<main>" in r.text{auth_tests}{db_tests}
''')
    w(".gitignore.extra", "data/\n")


# ---------------------------------------------------------------------------
# Express
# ---------------------------------------------------------------------------
JS_STORE_MEMORY = '''// Almacén en memoria (se pierde al reiniciar). Usa --db sqlite para persistir.
export function createStore(_name) {
  const data = new Map();
  let next = 1;
  return {
    list: () => [...data.values()],
    get: (id) => data.get(id),
    create: (item) => { const row = { id: next++, ...item }; data.set(row.id, row); return row; },
    update: (id, item) => (data.has(id) ? (data.set(id, { id, ...item }), data.get(id)) : undefined),
    remove: (id) => data.delete(id),
    empty: () => data.size === 0,
  };
}
'''

JS_STORE_SQLITE = '''// Persistencia en SQLite con node:sqlite (Node ≥ 22.13, sin dependencias). Ruta: APP_DB (data/app.db).
import { DatabaseSync } from "node:sqlite";
import { applyMigrations } from "./migrate.js";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export function connect() {
  const path = process.env.APP_DB ?? resolve(dirname(fileURLToPath(import.meta.url)), "../data/app.db");
  if (path !== ":memory:") mkdirSync(dirname(path), { recursive: true });
  const conn = new DatabaseSync(path);
  conn.exec("PRAGMA journal_mode = WAL");
  return conn;
}

let db;
export function database() {
  if (!db) {
    db = connect();
    applyMigrations(db);   // esquema definido en migrations/
  }
  return db;
}

export function createStore(name) {
  if (!/^[a-z][a-z0-9_]{0,40}$/.test(name)) throw new Error(`nombre de tabla inválido: ${name}`);
  const d = database();
  name = "res_" + name;   // prefijo: nunca choca con las tablas de autenticación (la tabla la crea migrations/)
  const row = (r) => (r ? { id: Number(r.id), name: r.name, description: r.description ?? undefined } : undefined);
  const q = {
    list: d.prepare(`SELECT * FROM ${name} ORDER BY id`),
    get: d.prepare(`SELECT * FROM ${name} WHERE id = ?`),
    insert: d.prepare(`INSERT INTO ${name} (name, description) VALUES (?, ?)`),
    update: d.prepare(`UPDATE ${name} SET name = ?, description = ? WHERE id = ?`),
    remove: d.prepare(`DELETE FROM ${name} WHERE id = ?`),
    count: d.prepare(`SELECT COUNT(*) AS n FROM ${name}`),
  };
  return {
    list: () => q.list.all().map(row),
    get: (id) => row(q.get.get(id)),
    create: (item) => row(q.get.get(q.insert.run(item.name, item.description ?? null).lastInsertRowid)),
    update: (id, item) => (q.update.run(item.name, item.description ?? null, id).changes ? row(q.get.get(id)) : undefined),
    remove: (id) => q.remove.run(id).changes > 0,
    empty: () => q.count.get().n === 0,
  };
}
'''

JS_AUTH = '''// Autenticación: registro, inicio de sesión y token Bearer para las escrituras.
// PBKDF2-SHA256 (sal de 16 bytes, 210 000 iteraciones); tokens aleatorios de 32 bytes,
// caducan a las 12 h y se guarda solo su hash; comparaciones en tiempo constante.
import { Router } from "express";
import { createHash, pbkdf2, randomBytes, timingSafeEqual } from "node:crypto";
import { promisify } from "node:util";
{backend_import}
const ITERATIONS = 210_000;
const TOKEN_TTL = 12 * 3600 * 1000;
// Asíncrono: pbkdf2Sync bloquearía el event loop ~100-200 ms por login.
const hashPassword = (password, salt) => promisify(pbkdf2)(password, salt, ITERATIONS, 32, "sha256");
const MAX_FAILURES = 5;
const FAILURE_WINDOW = 15 * 60 * 1000;
const IP_LIMIT = 30;            // peticiones de registro/inicio de sesión por IP y minuto (cada una cuesta un PBKDF2)
const IP_WINDOW = 60 * 1000;
const MAX_TRACKED = 10_000;      // tope de correos/IP recordados: los más antiguos se olvidan (LRU)
const failures = new Map();
const ipHits = new Map();
// Un Map recuerda el orden de inserción: borrar y volver a insertar lo marca como reciente.
function touch(store, key, window) {
  const recent = (store.get(key) ?? []).filter((t) => Date.now() - t < window);
  store.delete(key);
  store.set(key, recent);
  while (store.size > MAX_TRACKED) store.delete(store.keys().next().value);
  return recent;
}
const tooManyFailures = (email) => touch(failures, email, FAILURE_WINDOW).length >= MAX_FAILURES;
const recordFailure = (email, ok) => (ok ? failures.delete(email) : touch(failures, email, FAILURE_WINDOW).push(Date.now()));
function limitIp(req, res, next) {
  const hits = touch(ipHits, req.ip ?? "?", IP_WINDOW);
  if (hits.length >= IP_LIMIT) {
    res.set("Retry-After", String(IP_WINDOW / 1000));
    return res.status(429).json({ error: "Demasiadas peticiones: espera un minuto" });
  }
  hits.push(Date.now());
  next();
}
const tokenHash = (t) => createHash("sha256").update(t).digest("hex");
{backend}
function parseCredentials(body) {
  const email = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
  const password = typeof body?.password === "string" ? body.password : "";
  if (!/^[^@\\s]+@[^@\\s]+$/.test(email) || email.length > 200) return { error: "correo inválido" };
  if (password.length < 8 || password.length > 200) return { error: "la contraseña necesita 8-200 caracteres" };
  return { email, password };
}

export const authRouter = Router();

authRouter.post("/register", limitIp, async (req, res) => {
  const c = parseCredentials(req.body);
  if (c.error) return res.status(422).json({ error: c.error });
  const salt = randomBytes(16);
  // Misma respuesta si el correo ya existía: no se revela qué correos están registrados.
  users.create(c.email, salt.toString("hex"), (await hashPassword(c.password, salt)).toString("hex"));
  res.status(201).json({ email: c.email });
});

authRouter.post("/login", limitIp, async (req, res) => {
  const c = parseCredentials(req.body);
  if (c.error) return res.status(401).json({ error: "Correo o contraseña incorrectos" });
  if (tooManyFailures(c.email)) return res.status(429).json({ error: "Demasiados intentos: espera unos minutos" });
  const user = users.get(c.email);
  // Se calcula el hash aunque el usuario no exista, para no revelar qué correos están registrados.
  const salt = user ? Buffer.from(user.salt, "hex") : Buffer.alloc(16);
  const given = await hashPassword(c.password, salt);
  const stored = user ? Buffer.from(user.password, "hex") : Buffer.alloc(32);
  const ok = !!user && stored.length === given.length && timingSafeEqual(given, stored);
  recordFailure(c.email, ok);
  if (!ok) return res.status(401).json({ error: "Correo o contraseña incorrectos" });
  const token = randomBytes(32).toString("base64url");
  tokens.save(tokenHash(token), user.email, Date.now() + TOKEN_TTL);
  res.json({ token, expires_in: TOKEN_TTL / 1000 });
});

export function requireUser(req, res, next) {
  const header = req.get("authorization") ?? "";
  if (!/^bearer /i.test(header)) return res.status(401).set("WWW-Authenticate", "Bearer").json({ error: "Inicia sesión para hacer cambios" });
  const email = tokens.check(tokenHash(header.slice(7).trim()));
  if (!email) return res.status(401).set("WWW-Authenticate", "Bearer").json({ error: "Sesión caducada o inválida" });
  req.user = email;
  next();
}

authRouter.get("/me", requireUser, (req, res) => res.json({ email: req.user }));

authRouter.post("/logout", requireUser, (req, res) => {
  tokens.remove(tokenHash(req.get("authorization").slice(7).trim()));
  res.status(204).end();
});
'''

JS_AUTH_MEMORY = '''const userMap = new Map();
const tokenMap = new Map();
const users = {
  create: (email, salt, password) => (userMap.has(email) ? false : (userMap.set(email, { email, salt, password }), true)),
  get: (email) => userMap.get(email),
};
const tokens = {
  save: (hash, email, expires) => tokenMap.set(hash, { email, expires }),
  remove: (hash) => {
    tokenMap.delete(hash);
    for (const [k, t] of tokenMap) if (t.expires < Date.now()) tokenMap.delete(k);   // purga
  },
  check: (hash) => {
    const t = tokenMap.get(hash);
    if (!t || t.expires < Date.now()) { tokenMap.delete(hash); return undefined; }
    return t.email;
  },
};
'''

JS_AUTH_SQLITE = '''const d = database();   // auth_users y auth_tokens los crea la migración inicial
const users = {
  create: (email, salt, password) => {
    try { d.prepare("INSERT INTO auth_users (email, salt, password) VALUES (?, ?, ?)").run(email, salt, password); return true; }
    catch { return false; }
  },
  get: (email) => d.prepare("SELECT email, salt, password FROM auth_users WHERE email = ?").get(email),
};
const tokens = {
  save: (hash, email, expires) => {
    d.prepare("DELETE FROM auth_tokens WHERE expires < ?").run(Date.now());
    d.prepare("INSERT INTO auth_tokens (token_hash, email, expires) VALUES (?, ?, ?)").run(hash, email, expires);
  },
  remove: (hash) => d.prepare("DELETE FROM auth_tokens WHERE token_hash = ? OR expires < ?").run(hash, Date.now()),
  check: (hash) => {
    const t = d.prepare("SELECT email, expires FROM auth_tokens WHERE token_hash = ?").get(hash);
    return t && t.expires >= Date.now() ? t.email : undefined;
  },
};
'''


JS_MIGRATE = '// Migraciones de esquema SQLite (node:sqlite, sin dependencias).\n//   node src/migrate.js            aplica las pendientes\n//   node src/migrate.js status     lista aplicadas y pendientes\n//   node src/migrate.js new NOMBRE crea migrations/NNNN_nombre.sql vacía\n// Cada migrations/NNNN_*.sql se aplica una vez, en orden y en una transacción; se guarda su\n// huella SHA-256 y se avisa si alguien edita una migración ya aplicada.\nimport { createHash } from "node:crypto";\nimport { readdirSync, readFileSync, writeFileSync } from "node:fs";\nimport { dirname, join, resolve } from "node:path";\nimport { fileURLToPath } from "node:url";\n\nexport const MIGRATIONS = process.env.APP_MIGRATIONS ?? resolve(dirname(fileURLToPath(import.meta.url)), "../migrations");\nconst FILE = /^(\\d{4})_[a-z0-9_]+\\.sql$/;\n\nexport class MigrationError extends Error {}\n\nfunction files(dir) {\n  const list = readdirSync(dir).filter((f) => FILE.test(f)).sort();\n  const seen = new Map();\n  for (const f of list) {\n    if (seen.has(f.slice(0, 4))) throw new MigrationError(`Número de migración repetido: ${seen.get(f.slice(0, 4))} y ${f}`);\n    seen.set(f.slice(0, 4), f);\n  }\n  return list;\n}\n\n// Sin depender de CRLF/LF (git autocrlf en Windows no debe parecer una edición).\nconst checksumOf = (sql) => createHash("sha256").update(sql.replace(/\\r\\n/g, "\\n")).digest("hex");\n\nfunction applied(db) {\n  db.exec(`CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, name TEXT NOT NULL,\n    checksum TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)`);\n  return new Map(db.prepare("SELECT version, checksum FROM schema_migrations").all().map((r) => [r.version, r.checksum]));\n}\n\nexport function applyMigrations(db, dir = MIGRATIONS) {\n  const done = [];\n  const seen = applied(db);\n  for (const name of files(dir)) {\n    const version = name.slice(0, 4);\n    const sql = readFileSync(join(dir, name), "utf8");\n    const checksum = checksumOf(sql);\n    if (/^\\s*(BEGIN|COMMIT|ROLLBACK)\\b/im.test(sql)) throw new MigrationError(`${name}: no uses BEGIN/COMMIT; cada migración ya va en su transacción`);\n    if (seen.has(version)) {\n      if (seen.get(version) !== checksum) throw new MigrationError(`La migración ${name} cambió después de aplicarse: crea una nueva en lugar de editarla`);\n      continue;\n    }\n    db.exec("BEGIN");\n    try {\n      db.exec(sql);\n      db.prepare("INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)").run(version, name, checksum);\n      db.exec("COMMIT");\n    } catch (e) {\n      db.exec("ROLLBACK");\n      throw new MigrationError(`Falló ${name}: ${e.message}`);\n    }\n    done.push(name);\n  }\n  return done;\n}\n\nexport function migrationStatus(db, dir = MIGRATIONS) {\n  const seen = applied(db);\n  return files(dir).map((name) => [name, seen.has(name.slice(0, 4))]);\n}\n\nexport function newMigration(name, dir = MIGRATIONS) {\n  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "cambio";\n  const last = Math.max(0, ...files(dir).map((f) => Number(f.slice(0, 4))));\n  const file = join(dir, `${String(last + 1).padStart(4, "0")}_${slug}.sql`);\n  writeFileSync(file, `-- ${file.split(/[\\\\/]/).pop()}: describe aquí el cambio de esquema.\\n-- Ejemplo: ALTER TABLE res_items ADD COLUMN price REAL;\\n`);\n  return file;\n}\n\nif (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {\n  // Sin await de nivel superior: store.js importa este módulo y se bloquearían mutuamente.\n  const [cmd, ...rest] = process.argv.slice(2);\n  if (cmd === "new") console.log(newMigration(rest.join(" ")));\n  else import("./store.js").then(({ connect, database }) => {\n    if (cmd === "status") for (const [name, ok] of migrationStatus(connect())) console.log(`${ok ? "✓" : "·"} ${name}`);\n    else { database(); console.log("Migraciones al día."); }\n  });\n}\n'


def gen_express(spec: dict[str, Any], w: Writer) -> None:
    resources = spec["api"]["resources"] or ["items"]
    db, auth = _opts(spec)
    pkg: dict[str, Any] = {
        "name": spec["name"], "version": "0.1.0", "private": True, "type": "module",
        "scripts": {"start": "node src/server.js", "dev": "node --watch src/server.js", "test": "node --test"},
        "dependencies": {"express": "latest"},
    }
    if db == "sqlite":
        pkg["engines"] = {"node": ">=22.13"}
        pkg["scripts"]["migrate"] = "node src/migrate.js"
        pkg["scripts"]["migrate:status"] = "node src/migrate.js status"
        pkg["scripts"]["migrate:new"] = "node src/migrate.js new"
    w("package.json", json.dumps(pkg, indent=2))
    w("src/store.js", JS_STORE_SQLITE if db == "sqlite" else JS_STORE_MEMORY)
    if db == "sqlite":
        w("src/migrate.js", JS_MIGRATE)
        w("migrations/0001_init.sql", _initial_migration(resources, auth))
    w("src/validate.js", """// Validación mínima de entrada (sin dependencias).
export function parseItem(body) {
  if (!body || typeof body.name !== "string" || !body.name.trim() || body.name.length > 200) {
    return { error: "name es obligatorio (1-200 caracteres)" };
  }
  if (body.description !== undefined && (typeof body.description !== "string" || body.description.length > 2000)) {
    return { error: "description debe ser texto (máx. 2000)" };
  }
  return { value: { name: body.name.trim(), description: body.description } };
}
""")
    if auth:
        w("src/auth.js", JS_AUTH
          .replace("{backend_import}", 'import { database } from "./store.js";\n' if db == "sqlite" else "")
          .replace("{backend}", JS_AUTH_SQLITE if db == "sqlite" else JS_AUTH_MEMORY))
    guard = "requireUser, " if auth else ""
    for r in resources:
        w(f"src/routes/{r}.js", f"""import {{ Router }} from "express";
import {{ createStore }} from "../store.js";
import {{ parseItem }} from "../validate.js";
{'import { requireUser } from "../auth.js";' + chr(10) if auth else ''}
export const store = createStore("{_ident(r)}");
if (store.empty()) store.create({{ name: "Primer elemento de {r}", description: "Dato de ejemplo" }});
export const router = Router();

router.get("/", (_req, res) => res.json(store.list()));

router.post("/", {guard}(req, res) => {{
  const {{ value, error }} = parseItem(req.body);
  if (error) return res.status(422).json({{ error }});
  res.status(201).json(store.create(value));
}});

router.get("/:id", (req, res) => {{
  const item = store.get(Number(req.params.id));
  item ? res.json(item) : res.status(404).json({{ error: "No encontrado" }});
}});

router.put("/:id", {guard}(req, res) => {{
  const {{ value, error }} = parseItem(req.body);
  if (error) return res.status(422).json({{ error }});
  const item = store.update(Number(req.params.id), value);
  item ? res.json(item) : res.status(404).json({{ error: "No encontrado" }});
}});

router.delete("/:id", {guard}(req, res) => {{
  store.remove(Number(req.params.id)) ? res.status(204).end() : res.status(404).json({{ error: "No encontrado" }});
}});
""")
    camel = lambda s: s.replace("-", "_") + "Router"  # noqa: E731
    imports = "\n".join(f'import {{ router as {camel(r)} }} from "./routes/{r}.js";' for r in resources)
    uses = "\n".join(f'  app.use("/api/{r}", {camel(r)});' for r in resources)
    w("src/app.js", f"""import express from "express";
import {{ fileURLToPath }} from "node:url";
{imports}
{'import { authRouter } from "./auth.js";' + chr(10) if auth else ''}
export function createApp() {{
  const app = express();
  app.disable("x-powered-by");
  app.use((_req, res, next) => {{   // cabeceras de seguridad en todas las respuestas
    res.set({json.dumps(SECURITY_HEADERS)});
    next();
  }});
  app.use(express.json({{ limit: "100kb" }}));
  app.get("/api/health", (_req, res) => res.json({{ ok: true, db: "{db}", auth: {str(auth).lower()} }}));
{'  app.use("/api/auth", authRouter);' + chr(10) if auth else ''}{uses}
  app.use(express.static(fileURLToPath(new URL("../public", import.meta.url))));
  app.use((_req, res) => res.status(404).json({{ error: "No encontrado" }}));
  // Errores (JSON mal formado, cuerpo demasiado grande…): JSON sin traza, nunca la página HTML de Express.
  app.use((err, _req, res, _next) => {{
    const status = Number.isInteger(err?.status) && err.status >= 400 && err.status < 500 ? err.status : 500;
    if (status === 500) console.error(err);
    res.status(status).json({{ error: status === 500 ? "Error interno" : (err.type === "entity.parse.failed" ? "JSON inválido" : "Petición inválida") }});
  }});
  return app;
}}
""")
    w("src/server.js", """import { createApp } from "./app.js";

const port = Number(process.env.PORT ?? 8000);
createApp().listen(port, () => console.log(`Escuchando en http://localhost:${port}`));
""")
    _write_static_site(spec, w, "public/", resources)
    first = resources[0]
    setup_db = ('import { mkdtempSync } from "node:fs";\nimport { tmpdir } from "node:os";\nimport { join } from "node:path";\n'
                'process.env.APP_DB = join(mkdtempSync(join(tmpdir(), "app-test-")), "test.db");\n') if db == "sqlite" else ""
    auth_setup = """
let headers = { "Content-Type": "application/json" };
async function login() {
  await fetch(base + "/api/auth/register", { method: "POST", headers, body: JSON.stringify({ email: "ana@example.com", password: "contraseña-segura" }) });
  const r = await fetch(base + "/api/auth/login", { method: "POST", headers, body: JSON.stringify({ email: "ana@example.com", password: "contraseña-segura" }) });
  headers = { ...headers, Authorization: `Bearer ${(await r.json()).token}` };
}
""" if auth else '\nlet headers = { "Content-Type": "application/json" };\nasync function login() {}\n'
    auth_tests = f"""
test("las escrituras exigen sesión", async () => {{
  const r = await fetch(base + "/api/{first}", {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify({{ name: "x" }}) }});
  assert.equal(r.status, 401);
  const bad = await fetch(base + "/api/auth/login", {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify({{ email: "ana@example.com", password: "incorrecta-1" }}) }});
  assert.equal(bad.status, 401);
}});

test("sin enumeración, cierre de sesión y límite de intentos", async () => {{
  const j = {{ "Content-Type": "application/json" }};
  const post = (path, body, h = j) => fetch(base + path, {{ method: "POST", headers: h, body: JSON.stringify(body) }});
  await post("/api/auth/register", {{ email: "luis@example.com", password: "otra-contraseña" }});
  assert.equal((await post("/api/auth/register", {{ email: "luis@example.com", password: "cambiada-123" }})).status, 201);
  assert.equal((await post("/api/auth/login", {{ email: "luis@example.com", password: "cambiada-123" }})).status, 401);
  const {{ token }} = await (await post("/api/auth/login", {{ email: "luis@example.com", password: "otra-contraseña" }})).json();
  const h = {{ ...j, Authorization: `Bearer ${{token}}` }};
  assert.equal((await fetch(base + "/api/auth/me", {{ headers: h }})).status, 200);
  assert.equal((await post("/api/auth/logout", {{}}, h)).status, 204);
  assert.equal((await fetch(base + "/api/auth/me", {{ headers: h }})).status, 401);
  await post("/api/auth/register", {{ email: "eva@example.com", password: "contraseña-eva" }});
  const codes = [];
  for (let i = 0; i < 6; i++) codes.push((await post("/api/auth/login", {{ email: "eva@example.com", password: "mal-mal-mal" }})).status);
  assert.deepEqual(codes, [401, 401, 401, 401, 401, 429]);
}});
""" if auth else ""
    db_tests = f"""
test("migraciones: se aplican una vez, detectan ediciones y no dejan nada a medias", async () => {{
  const {{ DatabaseSync }} = await import("node:sqlite");
  const fs = await import("node:fs");
  const {{ join }} = await import("node:path");
  const {{ tmpdir }} = await import("node:os");
  const {{ applyMigrations, migrationStatus, MigrationError, MIGRATIONS }} = await import("../src/migrate.js");
  const {{ database }} = await import("../src/store.js");
  assert.ok(migrationStatus(database()).some(([n, ok]) => n === "0001_init.sql" && ok));
  const dir = fs.mkdtempSync(join(tmpdir(), "mig-"));
  fs.cpSync(MIGRATIONS, dir, {{ recursive: true }});
  fs.writeFileSync(join(dir, "0002_add_price.sql"), "ALTER TABLE res_{_ident(first)} ADD COLUMN price REAL;");
  const db = new DatabaseSync(join(dir, "m.db"));
  assert.deepEqual(applyMigrations(db, dir), ["0001_init.sql", "0002_add_price.sql"]);
  assert.deepEqual(applyMigrations(db, dir), []);
  assert.ok(db.prepare("PRAGMA table_info(res_{_ident(first)})").all().some((c) => c.name === "price"));
  fs.writeFileSync(join(dir, "0003_roto.sql"), "CREATE TABLE nueva (x INT); SELECT * FROM no_existe;");
  assert.throws(() => applyMigrations(db, dir), MigrationError);
  assert.equal(db.prepare("SELECT name FROM sqlite_master WHERE name = 'nueva'").get(), undefined);
  fs.unlinkSync(join(dir, "0003_roto.sql"));
  fs.writeFileSync(join(dir, "0001_init.sql"), "-- editada");
  assert.throws(() => applyMigrations(db, dir), /cambió/);
}});

test("los datos se guardan en SQLite", async () => {{
  await json("POST", "/api/{first}", {{ name: "persistente" }});
  const {{ database }} = await import("../src/store.js");
  const rows = database().prepare("SELECT name FROM res_{_ident(first)}").all().map((r) => r.name);
  assert.ok(rows.includes("persistente"));
}});
""" if db == "sqlite" else ""
    w("test/api.test.js", f"""{setup_db}import {{ test, before, after }} from "node:test";
import assert from "node:assert/strict";

const {{ createApp }} = await import("../src/app.js");
let server;
let base;
before(async () => {{
  server = createApp().listen(0);
  await new Promise((r) => server.once("listening", r));
  base = `http://127.0.0.1:${{server.address().port}}`;
  await login();
}});
after(() => server.close());
{auth_setup}
const json = (method, path, body) => fetch(base + path, {{ method, headers, body: body && JSON.stringify(body) }});

test("health", async () => {{
  assert.equal((await (await fetch(base + "/api/health")).json()).ok, true);
}});

test("CRUD de {first}", async () => {{
  const created = await json("POST", "/api/{first}", {{ name: "prueba" }});
  assert.equal(created.status, 201);
  const item = await created.json();
  assert.equal((await (await fetch(`${{base}}/api/{first}/${{item.id}}`)).json()).name, "prueba");
  assert.equal((await (await json("PUT", `/api/{first}/${{item.id}}`, {{ name: "cambio" }})).json()).name, "cambio");
  assert.equal((await json("DELETE", `/api/{first}/${{item.id}}`)).status, 204);
  assert.equal((await fetch(`${{base}}/api/{first}/${{item.id}}`)).status, 404);
}});

test("validación", async () => {{
  assert.equal((await json("POST", "/api/{first}", {{ name: "" }})).status, 422);
}});

test("frontend", async () => {{
  assert.match(await (await fetch(base + "/")).text(), /<main>/);
}});
{auth_tests}{db_tests}""")
    w(".gitignore.extra", "data/\n")
