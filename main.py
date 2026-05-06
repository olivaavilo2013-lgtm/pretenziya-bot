import os
import re
import uuid
import html
import tempfile
import requests
from datetime import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ========= НАСТРОЙКИ =========
TELEGRAM_TOKEN = "8719512116:AAFsGkV5eRr37PWqVvIGbOMkPexouGuyYEs"
DADATA_TOKEN = "4a8ee3cca7f2b9c83ff42fbd7a709839c66bc5d2"

COMPANY_SITE = "http://Sovet-consult.ru"
COMPANY_PHONE = "+7 981 906-99-99"

CLAIMANT_INN, DEFENDANT_INN, AMOUNT, REASON, CONTRACT, DEADLINE = range(6)


# ========= МЕНЮ =========
def main_menu():
    return ReplyKeyboardMarkup(
        [
            ["📄 Создать претензию"],
            ["ℹ️ Помощь", "📞 Контакты"],
        ],
        resize_keyboard=True,
    )


def site_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Перейти на сайт", url=COMPANY_SITE)]
    ])


# ========= ОЧИСТКА ТЕКСТА =========
def clean_text(text) -> str:
    if text is None:
        return ""

    text = str(text)

    replacements = {
        "\u00A0": " ",
        "\u200B": "",
        "\u200C": "",
        "\u200D": "",
        "\ufeff": "",
        "\t": " ",
        "—": "-",
        "–": "-",
        "−": "-",
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',
        "»": '"',
        "’": "'",
        "‘": "'",
        "₽": "руб.",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text.strip()


def p(text) -> str:
    """
    Подготовка текста для ReportLab Paragraph:
    чистим символы и экранируем HTML.
    """
    return html.escape(clean_text(text)).replace("\n", "<br/>")


# ========= ШРИФТ =========
def register_font():
    paths = [
        "DejaVuSans.ttf",
        "./DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    for path in paths:
        if os.path.exists(path):
            pdfmetrics.registerFont(TTFont("MainFont", path))
            return "MainFont"

    raise RuntimeError(
        "Не найден шрифт DejaVuSans.ttf. "
        "Положи файл DejaVuSans.ttf рядом с bot.py или main.py"
    )


FONT = register_font()


# ========= ПРОВЕРКИ =========
def is_valid_inn(inn: str) -> bool:
    inn = inn.strip()
    return bool(re.fullmatch(r"\d{10}|\d{12}", inn))


def parse_amount(text: str) -> float:
    cleaned = (
        text.replace(" ", "")
        .replace(",", ".")
        .replace("₽", "")
        .replace("руб.", "")
        .replace("руб", "")
        .strip()
    )

    amount = float(cleaned)

    if amount <= 0:
        raise ValueError

    return amount


def money_format(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",")


# ========= DADATA =========
def get_company_by_inn(inn: str):
    try:
        if not DADATA_TOKEN:
            print("DADATA_TOKEN не задан")
            return None

        url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"

        headers = {
            "Authorization": f"Token {DADATA_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        response = requests.post(
            url,
            json={"query": inn},
            headers=headers,
            timeout=15,
        )

        print("DADATA status:", response.status_code)

        response.raise_for_status()
        result = response.json()

        suggestions = result.get("suggestions", [])

        if not suggestions:
            return None

        item = suggestions[0]
        data = item.get("data", {})

        name = (
            data.get("name", {}).get("full_with_opf")
            or data.get("name", {}).get("short_with_opf")
            or item.get("value")
            or "Не найдено"
        )

        address = (
            data.get("address", {}).get("unrestricted_value")
            or data.get("address", {}).get("value")
            or "Не найдено"
        )

        ogrn = data.get("ogrn") or "Не найдено"
        kpp = data.get("kpp") or "Не найдено"

        return {
            "inn": inn,
            "name": clean_text(name),
            "address": clean_text(address),
            "ogrn": clean_text(ogrn),
            "kpp": clean_text(kpp),
        }

    except Exception as e:
        print("DADATA ERROR:", e)
        return None


# ========= PDF =========
def create_pdf(data: dict) -> str:
    file_path = os.path.join(
        tempfile.gettempdir(),
        f"pretenzia_{uuid.uuid4().hex}.pdf"
    )

    doc = SimpleDocTemplate(
        file_path,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Title"],
        fontName=FONT,
        fontSize=16,
        leading=22,
        alignment=TA_CENTER,
        spaceAfter=14,
    )

    normal_style = ParagraphStyle(
        "NormalStyle",
        parent=styles["Normal"],
        fontName=FONT,
        fontSize=11,
        leading=16,
        alignment=TA_LEFT,
        spaceAfter=8,
    )

    small_style = ParagraphStyle(
        "SmallStyle",
        parent=styles["Normal"],
        fontName=FONT,
        fontSize=9,
        leading=12,
        alignment=TA_LEFT,
        spaceAfter=6,
    )

    today = datetime.now().strftime("%d.%m.%Y")
    story = []

    story.append(Paragraph("<b>ДОСУДЕБНАЯ ПРЕТЕНЗИЯ</b>", title_style))
    story.append(Paragraph("о погашении задолженности", title_style))
    story.append(Spacer(1, 8))

    story.append(Paragraph(f"<b>Дата составления:</b> {p(today)}", normal_style))
    story.append(Spacer(1, 8))

    story.append(Paragraph("<b>Истец / кредитор:</b>", normal_style))
    story.append(Paragraph(
        f"{p(data['claimant_name'])}<br/>"
        f"ИНН: {p(data['claimant_inn'])}<br/>"
        f"КПП: {p(data['claimant_kpp'])}<br/>"
        f"ОГРН: {p(data['claimant_ogrn'])}<br/>"
        f"Адрес: {p(data['claimant_address'])}",
        normal_style,
    ))

    story.append(Spacer(1, 8))

    story.append(Paragraph("<b>Ответчик / должник:</b>", normal_style))
    story.append(Paragraph(
        f"{p(data['defendant_name'])}<br/>"
        f"ИНН: {p(data['defendant_inn'])}<br/>"
        f"КПП: {p(data['defendant_kpp'])}<br/>"
        f"ОГРН: {p(data['defendant_ogrn'])}<br/>"
        f"Адрес: {p(data['defendant_address'])}",
        normal_style,
    ))

    story.append(Spacer(1, 12))

    story.append(Paragraph(
        f"Между Истцом и Ответчиком возникли обязательственные отношения "
        f"на основании следующего документа: <b>{p(data['contract'])}</b>.",
        normal_style,
    ))

    story.append(Paragraph(
        f"Основание возникновения задолженности: <b>{p(data['reason'])}</b>.",
        normal_style,
    ))

    story.append(Paragraph(
        f"По состоянию на дату составления настоящей претензии задолженность "
        f"Ответчика перед Истцом составляет "
        f"<b>{p(money_format(data['amount']))} руб.</b>",
        normal_style,
    ))

    story.append(Paragraph(
        "В соответствии со статьями 309, 310, 314 и 395 Гражданского кодекса РФ "
        "обязательства должны исполняться надлежащим образом в соответствии "
        "с условиями обязательства и требованиями закона. Односторонний отказ "
        "от исполнения обязательства не допускается.",
        normal_style,
    ))

    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>ТРЕБУЮ:</b>", normal_style))
    story.append(Paragraph(
        f"Погасить задолженность в размере "
        f"<b>{p(money_format(data['amount']))} руб.</b> "
        f"в срок: <b>{p(data['deadline'])}</b>.",
        normal_style,
    ))

    story.append(Paragraph(
        "В случае непогашения задолженности в указанный срок Истец оставляет "
        "за собой право обратиться в суд с требованием о взыскании суммы "
        "задолженности, процентов за пользование чужими денежными средствами, "
        "неустойки при наличии оснований, судебных расходов, расходов на "
        "представителя и иных убытков.",
        normal_style,
    ))

    story.append(Spacer(1, 22))

    story.append(Paragraph("Подпись Истца: ___________________________", normal_style))
    story.append(Paragraph("Расшифровка: _____________________________", normal_style))

    story.append(Spacer(1, 18))

    story.append(Paragraph(
        "Документ сформирован автоматически. Перед направлением претензии "
        "рекомендуется проверить документ у юриста.",
        small_style,
    ))

    doc.build(story)
    return file_path


# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Здравствуйте 👋\n\n"
        "Этот бот помогает автоматически сформировать досудебную претензию "
        "о погашении задолженности в формате PDF.\n\n"
        "Для чего нужен бот:\n"
        "• быстро подготовить претензию должнику\n"
        "• автоматически подтянуть данные компаний по ИНН\n"
        "• сформировать аккуратный PDF-документ\n"
        "• получить готовый файл для отправки контрагенту\n\n"
        "Как это работает:\n"
        "1. Вы вводите ИНН истца\n"
        "2. Бот находит данные компании\n"
        "3. Вы вводите ИНН ответчика\n"
        "4. Указываете сумму долга\n"
        "5. Пишете основание задолженности\n"
        "6. Указываете договор, счёт или акт\n"
        "7. Бот формирует PDF-претензию\n\n"
        "⚠️ Важно: документ формируется автоматически. "
        "Перед отправкой рекомендуется проверить его у юриста.\n\n"
        "Наши юристы помогут вам в этом:\n"
        f"🌐 {COMPANY_SITE}\n"
        f"📞 {COMPANY_PHONE}\n\n"
        "Выберите действие:",
        reply_markup=main_menu(),
    )


async def create_claim_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "Шаг 1/6. Введите ИНН истца:",
        reply_markup=ReplyKeyboardRemove(),
    )

    return CLAIMANT_INN


async def claimant_inn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inn = update.message.text.strip()

    if not is_valid_inn(inn):
        await update.message.reply_text("Введите корректный ИНН из 10 или 12 цифр:")
        return CLAIMANT_INN

    await update.message.reply_text("Ищу данные истца по ИНН...")

    company = get_company_by_inn(inn)

    if not company:
        await update.message.reply_text(
            "Не удалось найти организацию по этому ИНН. Проверьте ИНН и введите заново:"
        )
        return CLAIMANT_INN

    context.user_data["claimant_company"] = company

    await update.message.reply_text(
        f"Истец найден:\n\n"
        f"{company['name']}\n"
        f"ИНН: {company['inn']}\n"
        f"КПП: {company['kpp']}\n"
        f"ОГРН: {company['ogrn']}\n"
        f"Адрес: {company['address']}\n\n"
        f"Шаг 2/6. Введите ИНН ответчика:"
    )

    return DEFENDANT_INN


async def defendant_inn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inn = update.message.text.strip()

    if not is_valid_inn(inn):
        await update.message.reply_text("Введите корректный ИНН из 10 или 12 цифр:")
        return DEFENDANT_INN

    await update.message.reply_text("Ищу данные ответчика по ИНН...")

    company = get_company_by_inn(inn)

    if not company:
        await update.message.reply_text(
            "Не удалось найти организацию по этому ИНН. Проверьте ИНН и введите заново:"
        )
        return DEFENDANT_INN

    context.user_data["defendant_company"] = company

    await update.message.reply_text(
        f"Ответчик найден:\n\n"
        f"{company['name']}\n"
        f"ИНН: {company['inn']}\n"
        f"КПП: {company['kpp']}\n"
        f"ОГРН: {company['ogrn']}\n"
        f"Адрес: {company['address']}\n\n"
        f"Шаг 3/6. Введите сумму долга в рублях:"
    )

    return AMOUNT


async def amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = parse_amount(update.message.text)
    except Exception:
        await update.message.reply_text("Введите корректную сумму. Например: 125000")
        return AMOUNT

    context.user_data["amount"] = amount

    await update.message.reply_text(
        "Шаг 4/6. Введите основание долга.\n\n"
        "Например: неоплата поставленного товара / оказанных услуг / выполненных работ"
    )

    return REASON


async def reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = clean_text(update.message.text)

    if len(text) < 5:
        await update.message.reply_text("Опишите основание долга чуть подробнее:")
        return REASON

    context.user_data["reason"] = text

    await update.message.reply_text(
        "Шаг 5/6. Введите договор, счёт, акт или другой документ.\n\n"
        "Например: Договор №15 от 10.01.2026"
    )

    return CONTRACT


async def contract_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = clean_text(update.message.text)

    if len(text) < 3:
        await update.message.reply_text("Введите номер договора, счёта или акта:")
        return CONTRACT

    context.user_data["contract"] = text

    await update.message.reply_text(
        "Шаг 6/6. Введите срок оплаты по претензии.\n\n"
        "Например: 10 календарных дней с даты получения претензии"
    )

    return DEADLINE


async def finish_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    deadline = clean_text(update.message.text)

    if len(deadline) < 3:
        await update.message.reply_text("Введите срок оплаты:")
        return DEADLINE

    context.user_data["deadline"] = deadline

    claimant = context.user_data["claimant_company"]
    defendant = context.user_data["defendant_company"]

    data = {
        "claimant_name": claimant["name"],
        "claimant_inn": claimant["inn"],
        "claimant_kpp": claimant["kpp"],
        "claimant_ogrn": claimant["ogrn"],
        "claimant_address": claimant["address"],

        "defendant_name": defendant["name"],
        "defendant_inn": defendant["inn"],
        "defendant_kpp": defendant["kpp"],
        "defendant_ogrn": defendant["ogrn"],
        "defendant_address": defendant["address"],

        "amount": context.user_data["amount"],
        "reason": context.user_data["reason"],
        "contract": context.user_data["contract"],
        "deadline": context.user_data["deadline"],
    }

    await update.message.reply_text("Формирую PDF-документ...")

    pdf_path = None

    try:
        pdf_path = create_pdf(data)

        with open(pdf_path, "rb") as file:
            await update.message.reply_document(
                document=file,
                filename="dosudebnaya_pretenzia.pdf",
                caption="Готово. Досудебная претензия сформирована.",
            )

        await update.message.reply_text(
            "📄 Документ готов.\n\n"
            "Для дальнейшего сотрудничества:\n\n"
            f"🌐 Сайт: {COMPANY_SITE}\n"
            f"📞 Телефон: {COMPANY_PHONE}",
            reply_markup=site_keyboard(),
        )

        await update.message.reply_text(
            "Вы можете создать новую претензию:",
            reply_markup=main_menu(),
        )

    except Exception as e:
        print("PDF ERROR:", e)
        await update.message.reply_text(
            f"Не удалось сформировать PDF.\n\nОшибка: {e}"
        )

    finally:
        if pdf_path and os.path.exists(pdf_path):
            os.remove(pdf_path)

    context.user_data.clear()
    return ConversationHandler.END


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот формирует досудебную претензию в PDF.\n\n"
        "Понадобится:\n"
        "1. ИНН истца\n"
        "2. ИНН ответчика\n"
        "3. Сумма долга\n"
        "4. Основание долга\n"
        "5. Договор, счёт или акт\n"
        "6. Срок оплаты\n\n"
        "После заполнения бот отправит готовый PDF."
    )


async def contacts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Для дальнейшего сотрудничества:\n\n"
        f"🌐 Сайт: {COMPANY_SITE}\n"
        f"📞 Телефон: {COMPANY_PHONE}",
        reply_markup=site_keyboard(),
    )


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "Создание претензии отменено.",
        reply_markup=main_menu(),
    )

    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("BOT ERROR:", context.error)


# ========= ЗАПУСК =========
def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("Не задан TELEGRAM_TOKEN")

    if not DADATA_TOKEN:
        raise RuntimeError("Не задан DADATA_TOKEN")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conversation = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex("^📄 Создать претензию$"),
                create_claim_start,
            )
        ],
        states={
            CLAIMANT_INN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, claimant_inn)
            ],
            DEFENDANT_INN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, defendant_inn)
            ],
            AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, amount_handler)
            ],
            REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, reason_handler)
            ],
            CONTRACT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, contract_handler)
            ],
            DEADLINE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, finish_handler)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_handler)
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conversation)
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ Помощь$"), help_handler))
    app.add_handler(MessageHandler(filters.Regex("^📞 Контакты$"), contacts_handler))
    app.add_error_handler(error_handler)

    print("Бот запущен...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
