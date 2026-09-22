from __future__ import annotations

import hashlib
import os

import psycopg


DATABASE_URL = ("postgresql://postgres:gFeEfyZpDSRbAuyEVXdZgfmqnnoksiJF@mainline.proxy.rlwy.net:23793/railway")


PASSWORDS = {
    "Юля": "TVnFTFN41p",
    "Ирина": "fz7VH1Fit8",
    "Настя Колоколова": "lD8Dp02tQW",
    "Оля Макарова": "b6KhmoNpdK",
    "Яна": "mqRbFr44Ma",
    "Лена": "YbCMRV02Gh",
    "Денис": "yX3pUDdvFC",
    "Женя": "FovzOMlnFl",
    "Рита": "rFuIqn8CVT",
    "Альбина": "kMuF3hSks6",
    "Саша": "ZIvJJzqrrc",
    "Фаниля": "hA7pgm6t2T",
    "Сергей": "qE8gcttiF1",
    "Олег": "uapKkOlAPg",
    "Настя С": "LBPaHDTrzw",
    "Наташа": "nG1qNgc0lj",
    "Надя": "cvmKH8JpYt",
    "Кантемир": "wbPHdbb03U",
    "Вика": "EMue1Wprew",
    "Инга": "9ZTGEh5ONE",
    "Нина": "JQTNEqRewm",
    "Оля": "ZST4VxP1pS",
    "Алена": "5QLWyOAhyN",
    "Кира": "9WzjJPKt86",
    "Паша": "abRKRVhOun",
    "Тоня": "4iW5DwMw2b",
    "Лёша": "M4bio3U5UE",
    "Маша": "5OWiYZM24q",
    "Вероника": "ZgnlNLx76A",
}


def hash_password(password: str) -> str:
    salt = os.urandom(16)

    password_hash = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
    )

    return (
        "scrypt$"
        + salt.hex()
        + "$"
        + password_hash.hex()
    )


def main() -> None:
    if not DATABASE_URL:
        raise SystemExit("Не задан DATABASE_URL")

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for username, password in PASSWORDS.items():
                password_hash = hash_password(password)

                cur.execute(
                    """
                    UPDATE accounts
                    SET password_hash = %s
                    WHERE username = %s
                    """,
                    (password_hash, username),
                )

                if cur.rowcount == 0:
                    print(f"⚠️ Не найден пользователь: {username}")
                else:
                    print(f"✅ Пароль установлен: {username}")

        conn.commit()

    print()
    print("Готово. Пароли сохранены в виде хэшей.")


if __name__ == "__main__":
    main()