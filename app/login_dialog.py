"""Окно входа: почта и пароль. Без сессии приложение не открывается."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


def _login_error(exc: Exception) -> str:
    message = str(exc).strip() or "Не удалось войти."
    low = message.casefold()
    if "invalid login" in low or "invalid credentials" in low:
        return "Неверная почта или пароль."
    if "email not confirmed" in low:
        return "Почта ещё не подтверждена."
    if "network" in low or "timed out" in low or "connection" in low:
        return "Нет связи с Supabase."
    return message


class LoginDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Вход")
        self.setModal(True)
        self.resize(380, 180)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.email = QLineEdit()
        self.email.setPlaceholderText("почта")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("пароль")
        form.addRow("Почта", self.email)
        form.addRow("Пароль", self.password)
        root.addLayout(form)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #9b2c2c;")
        root.addWidget(self.error)
        row = QHBoxLayout()
        cancel = QPushButton("Отмена")
        ok = QPushButton("Войти")
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._submit)
        self.email.returnPressed.connect(self._submit)
        self.password.returnPressed.connect(self._submit)
        row.addWidget(cancel)
        row.addWidget(ok)
        root.addLayout(row)

    def _submit(self) -> None:
        from .supa import login

        email = self.email.text().strip()
        password = self.password.text()
        if not email or not password:
            self.error.setText("Введите почту и пароль.")
            return
        self.error.setText("")
        try:
            login(email, password)
        except Exception as exc:
            self.error.setText(_login_error(exc))
            return
        self.accept()


def ensure_login() -> bool:
    """Восстановить сессию или спросить почту и пароль. False — пользователь закрыл окно."""
    from .supa import restore_session

    try:
        if restore_session():
            return True
    except Exception:
        pass
    dialog = LoginDialog()
    return dialog.exec() == QDialog.DialogCode.Accepted
