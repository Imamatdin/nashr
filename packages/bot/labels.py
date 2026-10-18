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

    failed_sources_warning: str
    generation_failed_at_step: str
    generation_ungrounded_refunded: str

    # Conversational editing loop + approval gate (Build 2, Stage 4). The brain's
    # own replies are produced in the user's language by the model; these are the
    # bot-chrome strings the machinery emits around it.
    edit_applied: str  # templated with {count}
    edit_render_failed: str
    edit_fixes_exhausted: str  # templated with {limit}
    edit_session_not_found: str
    approval_prompt: str  # templated with {reason}
    approval_approve: str
    approval_reject: str
    approval_required_first: str
    # A button pressed for a decision that was answered or replaced since (B1-FIX5).
    approval_stale: str
    # Approve pressed in the bot: the edit is now queued like a web approval and its
    # files are delivered here when the job completes (B8.1).
    approval_applying: str
    # The approved edit could not be queued; the decision stays re-presentable.
    edit_not_queued: str
    change_discarded: str
    edit_button: str  # the "Edit with AI" delivery button
    edit_invite: str  # shown on entering the conversational editor
    brain_busy: str  # dropped-message notice while a turn is still running
    stale_button: str  # toast for an expired inline button (fallback router)
    edit_nudge: str  # reviewing_output: how to reach the editor
    edit_nudge_unavailable: str  # reviewing_output, no editing session: buttons only
    brain_text_only: str  # talking_to_brain: non-text message rejected
    # Canonical document state (ADR 0001): the deck the user is editing here was
    # changed elsewhere; the bot never overwrites it and offers a reload instead.
    deck_changed_elsewhere: str
    reload_deck_button: str
    deck_reloaded: str
    deck_regeneration_proposed: str
    edit_unchanged: str
    # Fetch the latest rendered files from storage when a push did not arrive (B8.1).
    send_files_button: str
    files_not_ready: str


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
    failed_sources_warning=("⚠️ {count} ta fayl qayta ishlanmadi:\n{details}"),
    generation_failed_at_step=(
        "Xatolik: {step}. Qayta urinib ko'ring yoki qo'llab-quvvatlash xizmatiga murojaat qiling."
    ),
    generation_ungrounded_refunded=(
        "Ba'zi da'volarni manbalaringizdan tasdiqlab bo'lmadi, shuning uchun hech narsa "
        "yuborilmadi va to'lovingiz qaytarildi. Ko'proq manba qo'shib, qayta urinib ko'ring."
    ),
    edit_applied="✅ {count} ta slayd yangilandi. Yuklab oling:",
    edit_render_failed="Tahrirni tayyorlab bo'lmadi. Qayta urinib ko'ring — tahrirlar saqlanib qoldi.",
    edit_fixes_exhausted="Bu tarif uchun barcha {limit} ta tahrirdan foydalandingiz.",
    edit_session_not_found="Faol tahrirlash sessiyasi topilmadi.",
    approval_prompt="Bu o'zgarishni tasdiqlaysizmi?\n\n{reason}",
    approval_approve="✅ Tasdiqlash",
    approval_reject="❌ Bekor qilish",
    approval_required_first="Avval o'zgarishni tasdiqlang yoki bekor qiling.",
    approval_applying="✅ O'zgarish qo'llanmoqda. Yangilangan fayllar tez orada shu yerga keladi.",
    edit_not_queued="O'zgarishni boshlab bo'lmadi. Birozdan keyin qayta urinib ko'ring.",
    approval_stale="Bu tugma eski o'zgarishga tegishli — u allaqachon hal qilingan yoki almashtirilgan. Hech narsa o'zgarmadi.",
    change_discarded="O'zgarish bekor qilindi.",
    edit_button="✏️ AI bilan tahrirlash",
    edit_invite="Nimani o'zgartirishni yozing — men slaydlarni tahrirlab beraman.",
    brain_busy=(
        "⏳ Oldingi so'rovingiz ustida ishlayapman — bu xabar qayta ishlanmadi. "
        "Javobimdan keyin qayta yuboring."
    ),
    stale_button="Bu tugma eskirgan.",
    edit_nudge=(
        "Taqdimotni tahrirlash uchun quyidagi “✏️ AI bilan tahrirlash” tugmasini bosing, "
        "so'ng nimani o'zgartirishni yozing."
    ),
    edit_nudge_unavailable=(
        "Bu taqdimot uchun tahrirlash mavjud emas — yuklab olish yoki qayta yaratish "
        "uchun quyidagi tugmalardan foydalaning."
    ),
    brain_text_only="Bu yerda faqat matn bilan ishlay olaman — o'zgartirishni so'z bilan yozing.",
    deck_changed_elsewhere="Bu taqdimot siz bu yerda tahrirlashni boshlaganingizdan keyin boshqa joyda (masalan, saytda) o'zgartirildi. Tahriringiz qo'llanmadi. Eng so'nggi versiyani yuklab, qayta urinib ko'ring.",
    reload_deck_button="🔄 So'nggi versiyani yuklash",
    deck_reloaded="So'nggi versiya yuklandi. Tahrirlashni davom ettirishingiz mumkin.",
    deck_regeneration_proposed="Qayta yaratish davomida taqdimot boshqa joyda o'zgartirildi. Yangi versiya taklif sifatida saqlandi — uni saytda ko'rib chiqib, qabul qilishingiz mumkin.",
    edit_unchanged="Bu tahrir taqdimotga hech qanday o'zgarish kiritmadi.",
    send_files_button="📥 Fayllarni yuborish",
    files_not_ready="Fayllar hali tayyor emas. Birozdan keyin qayta urinib ko'ring.",
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
    failed_sources_warning=("⚠️ Не удалось обработать {count} файл(ов):\n{details}"),
    generation_failed_at_step=(
        "Ошибка на этапе: {step}. Попробуйте снова или обратитесь в поддержку."
    ),
    generation_ungrounded_refunded=(
        "Некоторые утверждения не удалось подтвердить вашими источниками, поэтому ничего "
        "не отправлено, а средства возвращены. Добавьте больше источников и попробуйте снова."
    ),
    edit_applied="✅ Обновлено слайдов: {count}. Скачайте:",
    edit_render_failed="Не удалось подготовить правку. Попробуйте ещё раз — ваши правки сохранены.",
    edit_fixes_exhausted="Вы использовали все {limit} правок для этого тарифа.",
    edit_session_not_found="Активная сессия редактирования не найдена.",
    approval_prompt="Подтвердить это изменение?\n\n{reason}",
    approval_approve="✅ Подтвердить",
    approval_reject="❌ Отменить",
    approval_required_first="Сначала подтвердите или отмените изменение.",
    approval_applying="✅ Изменение применяется. Обновлённые файлы скоро придут сюда.",
    edit_not_queued="Не удалось запустить изменение. Попробуйте ещё раз чуть позже.",
    approval_stale="Эта кнопка относится к прежнему изменению — оно уже решено или заменено. Ничего не изменилось.",
    change_discarded="Изменение отменено.",
    edit_button="✏️ Редактировать с ИИ",
    edit_invite="Напишите, что изменить — я отредактирую слайды.",
    brain_busy=(
        "⏳ Ещё работаю над предыдущим запросом — это сообщение не обработано. "
        "Отправьте его ещё раз после моего ответа."
    ),
    stale_button="Эта кнопка устарела.",
    edit_nudge=(
        "Чтобы отредактировать презентацию, нажмите «✏️ Редактировать с ИИ» ниже, "
        "затем напишите, что изменить."
    ),
    edit_nudge_unavailable=(
        "Редактирование недоступно для этой презентации — используйте кнопки ниже, "
        "чтобы скачать или создать заново."
    ),
    brain_text_only="Здесь я работаю только с текстом — опишите изменение словами.",
    deck_changed_elsewhere="Эта презентация была изменена в другом месте (например, на сайте) после того, как вы начали редактировать её здесь. Ваша правка не применена. Загрузите последнюю версию и попробуйте снова.",
    reload_deck_button="🔄 Загрузить последнюю версию",
    deck_reloaded="Последняя версия загружена. Можно продолжать редактирование.",
    deck_regeneration_proposed="Пока презентация создавалась заново, её изменили в другом месте. Новая версия сохранена как предложение — её можно просмотреть и принять на сайте.",
    edit_unchanged="Эта правка не изменила презентацию.",
    send_files_button="📥 Отправить файлы",
    files_not_ready="Файлы ещё не готовы. Попробуйте чуть позже.",
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
    failed_sources_warning=("⚠️ {count} file(s) could not be processed:\n{details}"),
    generation_failed_at_step=("Error at step: {step}. Please try again or contact support."),
    generation_ungrounded_refunded=(
        "Some claims couldn't be grounded in your sources, so nothing was shipped and "
        "you've been refunded. Add more source material and try again."
    ),
    edit_applied="✅ Updated {count} slide(s). Download:",
    edit_render_failed="The edit couldn't be rendered. Please try again — your edits are kept.",
    edit_fixes_exhausted="You've used all {limit} edits for this tier.",
    edit_session_not_found="No active editing session found.",
    approval_prompt="Approve this change?\n\n{reason}",
    approval_approve="✅ Approve",
    approval_reject="❌ Reject",
    approval_required_first="Please approve or reject the change first.",
    approval_applying="✅ Your change is being applied. The updated files will arrive here shortly.",
    edit_not_queued="Couldn't start the change. Please try again in a moment.",
    approval_stale="This button belongs to an earlier change that was already resolved or replaced. Nothing was changed.",
    change_discarded="Change discarded.",
    edit_button="✏️ Edit with AI",
    edit_invite="Tell me what to change — I'll edit the slides for you.",
    brain_busy=(
        "⏳ Still working on your previous request — this message was not processed. "
        "Send it again after I reply."
    ),
    stale_button="This button has expired.",
    edit_nudge=("To edit the deck, tap “✏️ Edit with AI” below, then tell me what to change."),
    edit_nudge_unavailable=(
        "Editing isn't available for this deck — use the buttons below to download or regenerate."
    ),
    brain_text_only="I can only work with text here — describe the change in words.",
    deck_changed_elsewhere="This presentation was changed somewhere else (for example on the website) after you started editing it here. Your edit was not applied. Reload the latest version and try again.",
    reload_deck_button="🔄 Reload latest version",
    deck_reloaded="Loaded the latest version. You can keep editing.",
    deck_regeneration_proposed="The presentation was changed elsewhere while it was being regenerated. The new version was saved as a proposal — you can review and accept it on the website.",
    edit_unchanged="That edit made no change to the presentation.",
    send_files_button="📥 Send files",
    files_not_ready="The files aren't ready yet. Please try again in a moment.",
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
    failed_sources_warning=("⚠️ {count} fayl qayta islenbedi:\n{details}"),
    generation_failed_at_step=(
        "Qátelik: {step}. Qayta urınıp kóriń yamasa qollap-quwatlawǵa baylanısıń."
    ),
    generation_ungrounded_refunded=(
        "Ba'zi da'walar dereklerińizden tastıyıqlanbadı, sonlıqtan hesh nárse jiberilmedi "
        "hám tólem qaytarıldı. Kóbirek derek qosıp, qayta urınıp kóriń."
    ),
    edit_applied="✅ {count} slayd jańalandı. Júklep alıń:",
    edit_render_failed="Redaktorlawdı tayarlap bolmadı. Qayta urınıp kóriń — redaktorlawlarıńız saqlandı.",
    edit_fixes_exhausted="Bul tarif ushın barlıq {limit} redaktorlawdı paydalandıńız.",
    edit_session_not_found="Aktiv redaktorlaw sessiyası tabılmadı.",
    approval_prompt="Bul ózgeristi tastıyıqlaysızba?\n\n{reason}",
    approval_approve="✅ Tastıyıqlaw",
    approval_reject="❌ Biykarlaw",
    approval_required_first="Aldın ózgeristi tastıyıqlań yamasa biykarlań.",
    approval_applying="✅ Ózgeris qollanbaqta. Jańalanǵan fayllar tez arada usı jerge keledi.",
    edit_not_queued="Ózgeristi baslap bolmadı. Azdan keyin qayta urinıp kóriń.",
    approval_stale="Bul túyme aldıńǵı ózgeriske tiyisli — ol sheshilgen yamasa almastırılǵan. Hesh nárse ózgermedi.",
    change_discarded="Ózgeris biykarlandı.",
    edit_button="✏️ AI menen redaktorlaw",
    edit_invite="Neni ózgertiw kerekligin jazıń — men slaydlardı redaktorlap beremen.",
    brain_busy=(
        "⏳ Aldınǵı sorawıńız ústinde islep atırman — bul xabar islenbedi. "
        "Juwabımnan keyin qaytadan jiberiń."
    ),
    stale_button="Bul túyme eskirgen.",
    edit_nudge=(
        "Prezentaciyanı redaktorlaw ushın tómendegi “✏️ AI menen redaktorlaw” túymesin basıń, "
        "keyin neni ózgertiwdi jazıń."
    ),
    edit_nudge_unavailable=(
        "Bul prezentaciya ushın redaktorlaw múmkin emes — júklep alıw yamasa qaytadan "
        "jaratıw ushın tómendegi túymelerden paydalanıń."
    ),
    brain_text_only="Bul jerde tek tekst penen isley alaman — ózgerisdi sóz benen jazıń.",
    deck_changed_elsewhere="Bul prezentaciya siz bul jerde redaktorlawdı baslaǵannan keyin basqa jerde (mısalı, saytta) ózgertildi. Redaktorlawıńız qollanılmadı. Eń sońǵı versiyanı júklep, qayta urınıp kóriń.",
    reload_deck_button="🔄 Eń sońǵı versiyanı júklew",
    deck_reloaded="Eń sońǵı versiya júklendi. Redaktorlawdı dawam ettiriwińiz múmkin.",
    deck_regeneration_proposed="Qaytadan jaratıw waqtında prezentaciya basqa jerde ózgertildi. Jańa versiya usınıs retinde saqlandı — onı saytta kórip shıǵıp, qabıl ete alasız.",
    edit_unchanged="Bul redaktorlaw prezentaciyaǵa hesh qanday ózgeris kirgizbedi.",
    send_files_button="📥 Fayllardı jiberiw",
    files_not_ready="Fayllar ele tayyar emes. Azdan keyin qayta urinıp kóriń.",
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
