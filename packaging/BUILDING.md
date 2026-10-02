# Сборка WT Flight для Windows x64

Проверенная среда: Python 3.14, PySide6 6.11.2, PyInstaller 6.22.3, Inno Setup 6.7.3.

1. Создать `.venv`, установить `requirements.txt` и `pyinstaller==6.22.3`.
2. Установить [Inno Setup](https://jrsoftware.org/isdl.php) в `.tools\inno` или изменить путь компилятора в `build.ps1`.
3. Выполнить `powershell -ExecutionPolicy Bypass -File packaging\build.ps1` из каталога проекта.

Результат: `release\WT-Flight-Setup-<версия>.exe`. Версия читается из `wtflight/__init__.py`. Установщик по умолчанию обновляет `D:\WT Flight`. Папка `dist\WT Flight` содержит переносимую версию: копировать нужно всю папку, включая `_internal`.

Подпись установщика выполняется при наличии сертификата: задайте `WT_SIGNTOOL`, `WT_CERTIFICATE` и `WT_TIMESTAMP_URL` перед запуском `build.ps1`. Без сертификата установщик собирается корректно, но Windows SmartScreen может показать предупреждение о неизвестном издателе.

Установщик работает для текущего пользователя, не требует администратора и не перезаписывает настройки из `%APPDATA%\WTFlightAssistant`. Обновление использует постоянный AppId. База самолётов, фон и значок включаются из `data`; стандартные звуки создаются автоматически при первом запуске.

Скрипт ограничивает PATH на время сборки, чтобы не включить несовместимые ICU/UCRT DLL из сторонних инструментов, и использует runtime из установленного PySide6. Перед компиляцией установщика автоматически выполняется проверка упакованного EXE. Подробности зависимостей Qt: [Qt for Windows — Deployment](https://doc.qt.io/qt-6/windows-deployment.html).

## Проверка

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m unittest test_hud_desktop.DesktopTests.test_tooltip_persists_during_viewport_hover_and_hides_on_leave -v
Remove-Item Env:QT_QPA_PLATFORM
& '.\dist\WT Flight\WT Flight.exe' --self-check '.\audit_artifacts\frozen-check'
```

Проверку горячих клавиш запускать при закрытой обычной копии программы. `--self-check` использует временные настройки, проверяет базу, фон, загрузку звуков и меню, записывает JSON/снимок окна в заданный каталог и завершает приложение.

Сборка не подписана сертификатом издателя. Для публичного распространения подпись добавляется отдельно.
