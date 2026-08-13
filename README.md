# TanionPlaning

Десктоп-планировщик задач (Windows, Python, PyQt6). Репозиторий публичный: личных задач, клиентов и токенов в нём нет. При первом запуске создаётся пустой файл `data/tasks.xlsx`.

Это исходники приложения. Чтобы открыть его на другом компьютере в Cursor, поставь программы ниже, клонируй репозиторий и запусти `py -3 -m app`.

## Что понадобится

| Программа | Зачем | Откуда |
|-----------|--------|--------|
| **Git** | клонировать репозиторий | https://git-scm.com/download/win |
| **Python 3.11 или новее** | запуск и правки | https://www.python.org/downloads/windows/ |
| **Cursor** | открыть проект и править код | https://cursor.com |

При установке Python отметь **Add python.exe to PATH**. Проверка в PowerShell:

```powershell
py -3 --version
git --version
```

## Как открыть в Cursor и запустить

1. Клонируй репозиторий (папка может быть любой):

```powershell
git clone https://github.com/Tanion37/TanionPlaningApp.git
```

2. В Cursor: **File → Open Folder** → выбери папку `TanionPlaningApp`.
3. Если Cursor предложит расширение **Python** (`ms-python.python`) – установи его.
4. Открой терминал в Cursor (**Terminal → New Terminal**) и поставь библиотеки:

```powershell
py -3 -m pip install -r requirements.txt
```

Пакеты: [PyQt6](https://pypi.org/project/PyQt6/) (окна) и [openpyxl](https://pypi.org/project/openpyxl/) (файл задач).

5. Запусти приложение одним из способов:

- в терминале: `py -3 -m app`
- или `scripts\start_app.bat`
- или клавиша **F5** (конфигурация «TanionPlaning»)

Задачи пишутся в `data/tasks.xlsx` внутри этой папки. Каталог `data/` в git не входит: чужие задачи в GitHub не уедут.

Ярлык на рабочий стол (по желанию):

```powershell
powershell -File scripts\create_desktop_shortcut.ps1
```

## Как устроен код (если хочешь поменять под себя)

Корень запуска – пакет `app/`. Точка входа: `app/__main__.py` → `app/main_window.py`.

| Файл | Что менять |
|------|------------|
| `app/tags.py` | набор тегов, символы, синонимы |
| `app/lists_store.py` | списки по умолчанию (`DEFAULT_LISTS`) |
| `app/widgets.py` | карточка задачи, диалоги новой/правки |
| `app/main_window.py` | экраны, кнопки, fullscreen |
| `app/day_tasks_board.py` | экран «Задачи дня» |
| `app/sorting.py` | экраны triage / сортировка |
| `app/colors.py` | цвета |
| `app/xlsx_store.py` | колонки таблицы `data/tasks.xlsx` |
| `app/models.py` | поля задачи |

После правки сохрани файл и запусти снова: `py -3 -m app`. Если окно уже открыто – закрой его и запусти ещё раз.

Подсказки для агента Cursor в этом репозитории: [AGENTS.md](AGENTS.md). Как пользоваться экранами: [docs/portable-user-guide.md](docs/portable-user-guide.md).

## Сборка portable (exe без Python у получателя)

На машине, где уже стоит Python и зависимости:

```powershell
py -3 -m pip install pyinstaller
powershell -File scripts\build_portable.ps1
```

Результат: папка `dist\TanionPlaning-portable` (`TanionPlaning.exe` + `_internal` + пустой `data\`). Её можно скопировать целиком на другой ПК.

## Чего в этом репозитории нет

Telegram-бота, секретаря, клиентов и твоих задач. Это только десктоп-приложение.
