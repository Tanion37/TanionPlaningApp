# Cursor: TanionPlaningApp

Публичный десктоп-планировщик. Личных данных, токенов и клиентов в репозитории нет.

## Запуск

1. Python 3.11+ (`py -3 --version`).
2. `py -3 -m pip install -r requirements.txt`
3. Из корня репозитория: `py -3 -m app`

Данные: `data/tasks.xlsx` (создаётся пустым при первом запуске). Каталог `data/` не коммитить.

## Правки

Исходники – пакет `app/`. Теги: `app/tags.py`. Списки по умолчанию: `app/lists_store.py`. UI: `app/main_window.py`, `app/widgets.py`. Хранение: `app/xlsx_store.py`.

После правки – снова `py -3 -m app`. Не подмешивать секреты, `config.json`, чужие xlsx/json с задачами.
