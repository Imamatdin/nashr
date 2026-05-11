"""Localized labels for bot messages and keyboards.

Covers every user-facing string the Telegram bot can emit: registration
prompts, menu buttons, status updates, error messages, payment copy.
Four languages are supported (uz, ru, en, kaa); the bot always renders
in the user's selected language and falls back to Uzbek when the
language string is unrecognised, never to English. The dataclass is
frozen so a handler cannot accidentally mutate a shared label pack.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BotLabels:
    """All user-facing strings the bot can emit for one language.

    Templated fields use ``str.format`` placeholders (``{invoice_number}``,
    ``{balance}``, ``{free_today}``, ``{progress}``, ``{required}``,
    ``{amount}``) so callers can interpolate runtime values without
    touching the language file.
    """

    welcome: str
    choose_language: str
    choose_calibration: str
    enter_name: str
    registration_complete: str
    calibration_school: str
    calibration_bachelor: str
    calibration_master: str
    calibration_doctoral: str

    main_menu: str
    create_article: str
    create_presentation: str
    my_projects: str
    my_balance: str
    settings: str

    upload_prompt: str
    upload_received: str
    upload_more: str
    continue_btn: str
    upload_error: str

    interview_start: str

    outline_ready: str
    approve: str
    regenerate: str
    cancel: str

    choose_tier: str
    basic: str
    standard: str
    premium: str

    choose_payment: str
    use_balance: str
    invoice_created: str
    payment_pending: str
    payment_confirmed: str
    insufficient_balance: str

    generating: str
    generation_complete: str
    generation_failed: str

    download_ready: str
    done: str

    open_questionnaire: str
    skip_questionnaire: str

    balance_info: str
    free_credit_earned: str

    error_generic: str
    error_file_too_large: str
    error_unsupported_format: str
    error_no_sources: str

    please_start_first: str
    no_projects_yet: str


LABELS_UZ = BotLabels(
    welcome="Nashr platformasiga xush kelibsiz! Til tanlang:",
    choose_language="Til tanlang:",
    choose_calibration="Ta'lim darajangizni tanlang:",
    enter_name="Ismingizni kiriting:",
    registration_complete="Ro'yxatdan o'tish muvaffaqiyatli! ✅",
    calibration_school="🏫 Maktab (9-11 sinf)",
    calibration_bachelor="🎓 Bakalavr",
    calibration_master="📚 Magistratura",
    calibration_doctoral="🔬 Doktorantura",
    main_menu="Bosh menyu:",
    create_article="📝 Maqola yaratish",
    create_presentation="📊 Prezentatsiya yaratish",
    my_projects="📁 Loyihalarim",
    my_balance="💰 Balansim",
    settings="⚙️ Sozlamalar",
    upload_prompt="Manba hujjatlarini yuboring (PDF, DOCX, TXT, XLSX, PPTX, rasm):",
    upload_received="Hujjat qabul qilindi! ✅ Yana yuborasizmi yoki davom etamizmi?",
    upload_more="📎 Yana yuklash",
    continue_btn="▶️ Davom etish",
    upload_error="Hujjatni qayta ishlashda xatolik yuz berdi.",
    interview_start="Bir necha savollarga javob bering:",
    outline_ready="Reja tayyor! Tekshirib chiqing:",
    approve="✅ Tasdiqlash",
    regenerate="🔄 Qayta yaratish",
    cancel="❌ Bekor qilish",
    choose_tier="Tarifni tanlang:",
    basic="Asosiy",
    standard="Standart",
    premium="Premium",
    choose_payment="To'lov usulini tanlang:",
    use_balance="💰 Balansdan to'lash",
    invoice_created=(
        "Hisob-faktura yaratildi.\n\n"
        "Raqam: <b>{invoice_number}</b>\n"
        "Summa: <b>{amount} UZS</b>\n\n"
        "To'lov ilovasini oching va Nashr ni qidirib, raqamingizni kiriting."
    ),
    payment_pending="To'lov kutilmoqda...",
    payment_confirmed="To'lov qabul qilindi! ✅",
    insufficient_balance=(
        "Balans yetarli emas. Joriy balans: {balance} UZS, kerak: {required} UZS"
    ),
    generating="Yaratilmoqda... ⏳\n{progress}",
    generation_complete="Tayyor! ✅",
    generation_failed=(
        "Xatolik yuz berdi. Qayta urinib ko'ring yoki qo'llab-quvvatlash xizmatiga murojaat qiling."
    ),
    download_ready="Fayllaringiz tayyor. Formatni tanlang:",
    done="✅ Tayyor",
    open_questionnaire="📋 Savolnomani ochish",
    skip_questionnaire="⏭ O'tkazib yuborish (standart sozlamalar)",
    balance_info="Balans: <b>{balance} UZS</b>\nBugungi bepul kreditlar: {free_today}/3",
    free_credit_earned="Bepul kredit olindi! +{amount} UZS 🎉",
    error_generic="Xatolik yuz berdi. Qayta urinib ko'ring.",
    error_file_too_large="Fayl juda katta (max 20 MB).",
    error_unsupported_format=(
        "Bu format qo'llab-quvvatlanmaydi. Qo'llab-quvvatlanadigan formatlar: "
        "PDF, DOCX, TXT, XLSX, PPTX, JPG, PNG."
    ),
    error_no_sources="Avval manba hujjatlarini yuklang.",
    please_start_first="Avval /start buyrug'ini yuboring.",
    no_projects_yet="Hali loyihalaringiz yo'q.",
)


LABELS_RU = BotLabels(
    welcome="Добро пожаловать в Nashr! Выберите язык:",
    choose_language="Выберите язык:",
    choose_calibration="Выберите уровень образования:",
    enter_name="Введите ваше имя:",
    registration_complete="Регистрация завершена! ✅",
    calibration_school="🏫 Школа (9-11 класс)",
    calibration_bachelor="🎓 Бакалавриат",
    calibration_master="📚 Магистратура",
    calibration_doctoral="🔬 Докторантура",
    main_menu="Главное меню:",
    create_article="📝 Создать статью",
    create_presentation="📊 Создать презентацию",
    my_projects="📁 Мои проекты",
    my_balance="💰 Мой баланс",
    settings="⚙️ Настройки",
    upload_prompt="Отправьте исходные документы (PDF, DOCX, TXT, XLSX, PPTX, изображение):",
    upload_received="Документ получен! ✅ Загрузить ещё или продолжить?",
    upload_more="📎 Загрузить ещё",
    continue_btn="▶️ Продолжить",
    upload_error="Ошибка при обработке документа.",
    interview_start="Ответьте на несколько вопросов:",
    outline_ready="План готов! Проверьте:",
    approve="✅ Утвердить",
    regenerate="🔄 Пересоздать",
    cancel="❌ Отменить",
    choose_tier="Выберите тариф:",
    basic="Базовый",
    standard="Стандарт",
    premium="Премиум",
    choose_payment="Выберите способ оплаты:",
    use_balance="💰 Оплатить с баланса",
    invoice_created=(
        "Счёт создан.\n\n"
        "Номер: <b>{invoice_number}</b>\n"
        "Сумма: <b>{amount} UZS</b>\n\n"
        "Откройте платёжное приложение, найдите Nashr и введите номер."
    ),
    payment_pending="Ожидание оплаты...",
    payment_confirmed="Оплата принята! ✅",
    insufficient_balance="Недостаточно средств. Баланс: {balance} UZS, нужно: {required} UZS",
    generating="Создаётся... ⏳\n{progress}",
    generation_complete="Готово! ✅",
    generation_failed="Произошла ошибка. Попробуйте снова или обратитесь в поддержку.",
    download_ready="Файлы готовы. Выберите формат:",
    done="✅ Готово",
    open_questionnaire="📋 Открыть анкету",
    skip_questionnaire="⏭ Пропустить (стандартные настройки)",
    balance_info="Баланс: <b>{balance} UZS</b>\nБесплатные кредиты сегодня: {free_today}/3",
    free_credit_earned="Бесплатный кредит получен! +{amount} UZS 🎉",
    error_generic="Произошла ошибка. Попробуйте снова.",
    error_file_too_large="Файл слишком большой (макс. 20 МБ).",
    error_unsupported_format=(
        "Формат не поддерживается. Поддерживаемые: PDF, DOCX, TXT, XLSX, PPTX, JPG, PNG."
    ),
    error_no_sources="Сначала загрузите исходные документы.",
    please_start_first="Сначала отправьте команду /start.",
    no_projects_yet="У вас пока нет проектов.",
)


LABELS_EN = BotLabels(
    welcome="Welcome to Nashr! Choose your language:",
    choose_language="Choose language:",
    choose_calibration="Select your education level:",
    enter_name="Enter your name:",
    registration_complete="Registration complete! ✅",
    calibration_school="🏫 School (9th-11th grade)",
    calibration_bachelor="🎓 Bachelor's",
    calibration_master="📚 Master's",
    calibration_doctoral="🔬 Doctoral",
    main_menu="Main menu:",
    create_article="📝 Create article",
    create_presentation="📊 Create presentation",
    my_projects="📁 My projects",
    my_balance="💰 My balance",
    settings="⚙️ Settings",
    upload_prompt="Send your source documents (PDF, DOCX, TXT, XLSX, PPTX, image):",
    upload_received="Document received! ✅ Upload more or continue?",
    upload_more="📎 Upload more",
    continue_btn="▶️ Continue",
    upload_error="Error processing document.",
    interview_start="Answer a few questions:",
    outline_ready="Outline ready! Review it:",
    approve="✅ Approve",
    regenerate="🔄 Regenerate",
    cancel="❌ Cancel",
    choose_tier="Choose a plan:",
    basic="Basic",
    standard="Standard",
    premium="Premium",
    choose_payment="Choose payment method:",
    use_balance="💰 Pay from balance",
    invoice_created=(
        "Invoice created.\n\n"
        "Number: <b>{invoice_number}</b>\n"
        "Amount: <b>{amount} UZS</b>\n\n"
        "Open your payment app, search for Nashr, and enter your number."
    ),
    payment_pending="Waiting for payment...",
    payment_confirmed="Payment confirmed! ✅",
    insufficient_balance="Insufficient balance. Current: {balance} UZS, required: {required} UZS",
    generating="Generating... ⏳\n{progress}",
    generation_complete="Done! ✅",
    generation_failed="An error occurred. Try again or contact support.",
    download_ready="Your files are ready. Choose format:",
    done="✅ Done",
    open_questionnaire="📋 Open questionnaire",
    skip_questionnaire="⏭ Skip (use defaults)",
    balance_info="Balance: <b>{balance} UZS</b>\nFree credits today: {free_today}/3",
    free_credit_earned="Free credit earned! +{amount} UZS 🎉",
    error_generic="An error occurred. Try again.",
    error_file_too_large="File too large (max 20 MB).",
    error_unsupported_format=(
        "Unsupported format. Supported: PDF, DOCX, TXT, XLSX, PPTX, JPG, PNG."
    ),
    error_no_sources="Please upload source documents first.",
    please_start_first="Please send /start first.",
    no_projects_yet="No projects yet.",
)


LABELS_KAA = BotLabels(
    welcome="Nashr platformasına xosh kelipsiz! Til tańlań:",
    choose_language="Til tańlań:",
    choose_calibration="Bilim dárejańizdi tańlań:",
    enter_name="Atıńızdı kirgiziń:",
    registration_complete="Dizimnen ótiw tamamlandı! ✅",
    calibration_school="🏫 Mektep (9-11 klass)",
    calibration_bachelor="🎓 Bakalavr",
    calibration_master="📚 Magistratura",
    calibration_doctoral="🔬 Doktorantura",
    main_menu="Bas menyu:",
    create_article="📝 Maqala jaratıw",
    create_presentation="📊 Prezentaciya jaratıw",
    my_projects="📁 Loyihalarım",
    my_balance="💰 Balansım",
    settings="⚙️ Sazlamalar",
    upload_prompt="Derekli hújjetlerdi jiberiń (PDF, DOCX, TXT, XLSX, PPTX, súwret):",
    upload_received="Hújjet qabıl etildi! ✅ Taǵı júkleysiz be yaki dawam etemiz be?",
    upload_more="📎 Taǵı júklew",
    continue_btn="▶️ Dawam etiw",
    upload_error="Hújjetti qayta islewde qátelik.",
    interview_start="Bir neshe sorawǵa juwap beriń:",
    outline_ready="Joba tayar! Tekserip shıǵıń:",
    approve="✅ Tastıyıqlaw",
    regenerate="🔄 Qayta jaratıw",
    cancel="❌ Biykar etiw",
    choose_tier="Tarifti tańlań:",
    basic="Tiykarǵı",
    standard="Standart",
    premium="Premium",
    choose_payment="Tólem usılın tańlań:",
    use_balance="💰 Balanstan tólew",
    invoice_created=(
        "Esap-faktura jaratıldı.\n\n"
        "Nomer: <b>{invoice_number}</b>\n"
        "Summa: <b>{amount} UZS</b>\n\n"
        "Tólem qosımshańızdı ashıń, Nashr di izlep, nomerińizdi kirgiziń."
    ),
    payment_pending="Tólem kútilmekte...",
    payment_confirmed="Tólem qabıl etildi! ✅",
    insufficient_balance="Balans jetpeydi. Házirgi balans: {balance} UZS, kerek: {required} UZS",
    generating="Jaratılmaqta... ⏳\n{progress}",
    generation_complete="Tayar! ✅",
    generation_failed="Qátelik júz berdi. Qayta urınıp kóriń.",
    download_ready="Fayllarıńız tayar. Formatdı tańlań:",
    done="✅ Tayar",
    open_questionnaire="📋 Sorawnamanı ashıw",
    skip_questionnaire="⏭ Ótkerip jiberiw (standart sazlamalar)",
    balance_info="Balans: <b>{balance} UZS</b>\nBúgingi tegin kreditler: {free_today}/3",
    free_credit_earned="Tegin kredit alındı! +{amount} UZS 🎉",
    error_generic="Qátelik júz berdi. Qayta urınıp kóriń.",
    error_file_too_large="Fayl júda úlken (maks 20 MB).",
    error_unsupported_format=(
        "Bul format qollap-quwatlanbaydı. Qollap-quwatlanadıǵanlar: "
        "PDF, DOCX, TXT, XLSX, PPTX, JPG, PNG."
    ),
    error_no_sources="Aldın derekli hújjetlerdi júklemelisiniz.",
    please_start_first="Aldın /start buyrıǵın jiberiń.",
    no_projects_yet="Sizde hesh qanday loyiha joq.",
)


_LABELS: dict[str, BotLabels] = {
    "uz": LABELS_UZ,
    "ru": LABELS_RU,
    "en": LABELS_EN,
    "kaa": LABELS_KAA,
}


def get_bot_labels(language: str) -> BotLabels:
    """Return the label pack for ``language``; fall back to Uzbek.

    Karakalpak (``kaa``) is checked first because its ISO code is three
    letters and would otherwise be truncated to ``ka`` (Georgian).
    Unknown codes fall back to Uzbek, the primary user language, rather
    than to English.
    """

    if not language:
        return LABELS_UZ
    lowered = language.lower()
    if lowered.startswith("kaa"):
        return LABELS_KAA
    return _LABELS.get(lowered[:2], LABELS_UZ)
