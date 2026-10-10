from email.utils import formataddr
from html import unescape
import re
import smtplib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives, get_connection
from django.utils.html import strip_tags

from apps.core.api.exceptions import Conflict

from .models import EmailAccount


SMTP_TIMEOUT_SECONDS = 15


class EmailDeliveryUncertain(Conflict):
    """SMTP 会话异常，调用方不能据此断言邮件一定未被接受。"""


def _fernet_instances():
    configured_keys = getattr(settings, "EMAIL_ACCOUNT_FERNET_KEYS", [])
    if isinstance(configured_keys, str):
        configured_keys = [configured_keys]
    if not configured_keys:
        raise Conflict("邮件账户加密密钥未配置，无法保存或使用 SMTP 授权码。")

    try:
        return [Fernet(key.encode("utf-8") if isinstance(key, str) else key) for key in configured_keys]
    except (TypeError, ValueError) as exc:
        raise Conflict("邮件账户加密密钥格式无效，请检查 EMAIL_ACCOUNT_FERNET_KEYS。") from exc


def encrypt_smtp_password(password: str) -> str:
    if not password or not password.strip():
        raise Conflict("SMTP 授权码不能为空。")
    return _fernet_instances()[0].encrypt(password.encode("utf-8")).decode("utf-8")


def decrypt_smtp_password(account: EmailAccount) -> str:
    for fernet in _fernet_instances():
        try:
            return fernet.decrypt(account.smtp_password_ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            continue
        except UnicodeDecodeError as exc:
            raise Conflict("邮件账户授权码无法解密，请重新填写授权码。") from exc
    raise Conflict("邮件账户授权码无法解密，请重新填写授权码。")


def email_account_snapshot(account: EmailAccount) -> dict:
    """审计和发送历史可使用的安全快照，不包含授权码及其密文。"""

    return {
        "id": str(account.pk),
        "display_name": account.display_name,
        "sender_name": account.sender_name,
        "sender_email": account.sender_email,
        "smtp_host": account.smtp_host,
        "smtp_port": account.smtp_port,
        "smtp_username": account.smtp_username,
        "smtp_security": account.smtp_security,
        "is_enabled": account.is_enabled,
        "is_default": account.is_default,
        "last_test_status": account.last_test_status,
        "last_tested_at": account.last_tested_at,
    }


def default_email_account_for_employee(employee: object) -> EmailAccount:
    if employee is None:
        raise Conflict("当前账户没有有效员工档案，无法使用账户级邮件配置。")
    account = EmailAccount.objects.filter(
        employee=employee,
        is_enabled=True,
        is_default=True,
    ).first()
    if account is None:
        raise Conflict("当前账户未配置启用的默认邮件账户，请先在系统配置中完成设置。")
    return account


def _connection_for(account: EmailAccount):
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=account.smtp_host,
        port=account.smtp_port,
        username=account.smtp_username,
        password=decrypt_smtp_password(account),
        use_tls=account.smtp_security == "STARTTLS",
        use_ssl=account.smtp_security == "SSL",
        timeout=SMTP_TIMEOUT_SECONDS,
        fail_silently=False,
    )


def _from_email(account: EmailAccount) -> str:
    return formataddr((account.sender_name, account.sender_email)) if account.sender_name else account.sender_email


def _plain_text_from_html(value: str) -> str:
    """为富文本邮件生成可读的纯文本备用正文。"""

    with_line_breaks = re.sub(r"<\s*br\s*/?\s*>", "\n", value, flags=re.IGNORECASE)
    with_line_breaks = re.sub(
        r"</\s*(?:p|div|li|h[1-6]|tr)\s*>",
        "\n",
        with_line_breaks,
        flags=re.IGNORECASE,
    )
    plain_text = unescape(strip_tags(with_line_breaks))
    return re.sub(r"\n{3,}", "\n\n", plain_text).strip()


def send_via_email_account(
    *,
    account: EmailAccount,
    subject: str,
    body: str,
    recipient: str,
    cc: list[str] | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
    html_body: str | None = None,
):
    if not account.is_enabled:
        raise Conflict("该邮件账户已停用，无法发送邮件。")

    message_args = {
        "subject": subject,
        "body": _plain_text_from_html(html_body) if html_body is not None else body,
        "from_email": _from_email(account),
        "to": [recipient],
        "cc": cc or [],
        "connection": _connection_for(account),
    }
    message = EmailMultiAlternatives(**message_args) if html_body is not None else EmailMessage(**message_args)
    if html_body is not None:
        message.attach_alternative(html_body, "text/html")
    for attachment in attachments or []:
        message.attach(*attachment)

    try:
        accepted_count = message.send(fail_silently=False)
    except Conflict:
        raise
    except (
        smtplib.SMTPAuthenticationError,
        smtplib.SMTPConnectError,
        smtplib.SMTPHeloError,
        smtplib.SMTPNotSupportedError,
        smtplib.SMTPRecipientsRefused,
        smtplib.SMTPSenderRefused,
    ) as exc:
        raise Conflict("邮件服务明确拒绝了本次发送，请检查账户、发件人和收件人设置。") from exc
    except smtplib.SMTPDataError as exc:
        raise Conflict("邮件服务明确拒绝接收邮件内容，请检查主题、正文和附件。") from exc
    except Exception as exc:
        raise EmailDeliveryUncertain("邮件投递结果无法确认，请先核对发件箱，不能直接重复发送。") from exc
    if accepted_count != 1:
        raise Conflict("邮件服务未确认接受投递，操作未继续执行。")


def send_test_email(*, account: EmailAccount, recipient: str):
    send_via_email_account(
        account=account,
        recipient=recipient,
        subject="Haiqu ERP 邮件账户测试",
        body="这是一封由 Haiqu ERP 发出的邮件账户测试邮件。若您收到此邮件，说明 SMTP 配置可正常投递。",
    )
