"""Окно входа: почта и пароль. Без отметки «Запомнить меня» приложение не открывается."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
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
    def __init__(
        self,
        parent=None,
        *,
        notice: str = "",
        email: str = "",
        allow_local: bool = True,
    ) -> None:
        super().__init__(parent)
        self.local_only = False
        self.setWindowTitle("Вход")
        self.setModal(True)
        self.resize(380, 300 if notice else 260)
        root = QVBoxLayout(self)
        if notice:
            hint = QLabel(notice)
            hint.setWordWrap(True)
            root.addWidget(hint)
        form = QFormLayout()
        self.email = QLineEdit()
        self.email.setPlaceholderText("почта")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("пароль")
        if email:
            self.email.setText(email)
        form.addRow("Почта", self.email)
        form.addRow("Пароль", self.password)
        root.addLayout(form)
        self.remember = QCheckBox("Запомнить меня")
        self.remember.setChecked(True)
        self.remember.setToolTip(
            "После закрытия приложения вход сохранится на этом компьютере. "
            "Пароль не записывается, сессия обновляется сама."
        )
        root.addWidget(self.remember)
        if allow_local:
            local = QPushButton("Работать локально")
            local.setToolTip(
                "Открыть задачи на этом компьютере. В Supabase они не уйдут, пока не нажмёте «Синхронизация»."
            )
            local.clicked.connect(self._work_local)
            root.addWidget(local)
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
            login(email, password, remember=self.remember.isChecked())
        except Exception as exc:
            self.error.setText(_login_error(exc))
            return
        self.accept()

    def _work_local(self) -> None:
        self.local_only = True
        self.accept()


def ensure_login() -> str:
    """«sync» — вошли или запомнены, «local» — без аккаунта, «» — окно закрыли.

    Сеть здесь не проверяется: сохранённая отметка пускает в локальную книгу.
    """
    from .supa import remembered, remembered_email

    if remembered():
        return "sync"
    dialog = LoginDialog(email=remembered_email())
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return ""
    if dialog.local_only:
        return "local"
    return "sync"
