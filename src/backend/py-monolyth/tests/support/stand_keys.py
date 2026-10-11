"""Ключи JWT стенда N3: пара генерируется на машине запуска и в репозиторий не попадает (ADR-013).

`make stand-up` создаёт файл пары (если его нет) и передаёт стенду только публичный ключ
(`JWT_PUBLIC_KEYS`); тесты `n_instances` подписывают access-токены приватным ключом из файла.

Использование:
    python -m tests.support.stand_keys ensure .stand/jwt-keys.json
    python -m tests.support.stand_keys public .stand/jwt-keys.json
"""

import json
import sys
from pathlib import Path

from tests.support.jwt_keys import SigningKeyPair, generate_signing_key_pair


DEFAULT_PATH = Path(".stand/jwt-keys.json")


def ensure(path: Path) -> SigningKeyPair:
    """Пара из файла; если файла нет — новая пара записывается в него (права 600)."""
    if path.exists():
        return load(path)
    pair = generate_signing_key_pair()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pair.__dict__), encoding="utf-8")
    path.chmod(0o600)
    return pair


def load(path: Path = DEFAULT_PATH) -> SigningKeyPair:
    """Пара ключей стенда из файла."""
    return SigningKeyPair(**json.loads(path.read_text(encoding="utf-8")))


def main(argv: list[str]) -> int:
    """`ensure <path>` — создать пару; `public <path>` — напечатать `JWT_PUBLIC_KEYS` стенда."""
    command, path = argv[0], Path(argv[1])
    pair = ensure(path)
    if command == "public":
        print(json.dumps({pair.kid: pair.public_pem}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
