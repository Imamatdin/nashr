import type { Locale } from "@/lib/locale";

/**
 * Copy for the presentation workspace shell.
 *
 * Keeping this contract beside the workspace components makes missing locale
 * keys a type error instead of letting one language silently fall back to a
 * different one. Generated project content is deliberately not translated.
 */
export const WORKSPACE_COPY = {
  en: {
    sourceTitle: "Sources",
    sourceEmpty:
      "Add PDFs, documents, or notes. Research and citations stay beside your draft.",
    sourceChoose: "Choose a file",
    sourceHint: "PDF, DOCX, PPTX. Up to 20 MB.",
    sourceUpload: "Add source",
    sourceUploading: "Uploading",
    sourceLabel: "Project sources",
    chooseFirst: "Choose a file first",
    uploaded: (name: string) => `${name} uploaded`,
    duplicateRun:
      "This project is already being created. You were not charged again.",
    fixStarting: "Applying the edit and rebuilding the presentation.",
    shareDisabled: "Public link disabled",
    shareRotated: "New link created. The old link no longer works.",
    shareEnabled: "Public link enabled",
    shareCopied: "Link copied",
    shareCopyFailed: "Could not copy it. Select the link and copy it manually.",
    backProjects: "Back to projects",
    chatDisabledRunning:
      "You can edit here as soon as the presentation is ready.",
    chatDisabledEmpty:
      "Chat opens after the presentation is ready and works directly on its slides.",
    fixApplying: "Applying your edit. This usually takes a few minutes.",
    fixDelivering: "Your edit is saved; its files are being prepared.",
    fixesRemaining: "Edits remaining",
    reconnecting: "Status is not updating. Reconnecting…",
    archivedTitle: "Archived project",
    archivedHint:
      "You can view this project, but you cannot start a new generation while it is archived.",
    startLead:
      "Once your sources are ready, create the presentation. It usually takes 3–6 minutes.",
    createPresentation: "Create presentation",
    charge: (tier: string, price: string) =>
      `${tier} will be charged from your balance: ${price}. A failed generation is refunded automatically.`,
    needsSource: "Add at least one source below.",
    queued: "Queued",
    queuedHint: "Your job is queued. The first step will begin shortly.",
    working: "Working",
    elapsed: "Elapsed",
    live: "live",
    refreshing: "refreshing",
    stalled:
      "The job has not responded for 45 seconds. It usually recovers on its own; otherwise your credit is refunded automatically.",
    refunded: "Credit refunded",
    technical: "Technical details",
    restart: "Start again",
    restartHint:
      "This starts a new generation from the first step and charges your balance again.",
    preparingFiles: "Preparing files",
    preparingFilesHint:
      "The presentation is assembled and its files are being published.",
    delivering: "Deck saved — preparing your files",
    deliveringHint:
      "Your deck is saved. Each download appears here as soon as it is published; there is no need to reload.",
    deliveryFailed: "Your deck was saved, but its files could not be produced.",
    deliveryFailedHint:
      "You were not charged for this run. The deck stays editable; update the exports to try the files again, or start a new generation.",
    processDetails: "Process details",
    deckAppears: "Your presentation will appear here.",
    noDeck: "No presentation yet.",
    aiImages: "AI images",
    readyIn: "created in",
    chat: "Chat",
    chatPlaceholder: "What should we change?",
    chatEmptyTitle: "Work on the presentation with Nashr",
    chatEmptyHint:
      "Try “correct the date on slide 3” or “shorten the conclusion”. Nashr stays grounded in the sources you uploaded.",
    approvalLabel: "Approval",
    approvalTitle: "Apply this change?",
    approve: "Apply",
    reject: "Dismiss",
    messageLabel: "Message",
    sendLabel: "Send",
    presentation: "Presentation",
    railLabel: "Chat and process",
    noSourceTitle: "No sources yet",
    noSourceHint:
      "The presentation uses facts from the files you provide. Upload a PDF, DOCX, or PPTX file (up to 20 MB).",
    sourceSnapshot:
      "This presentation was created from the sources listed here. Create it again to include any new file.",
    upload: "Upload",
    sharing: "Sharing",
    shareActiveHint:
      "The link works until you disable it. Replacing it invalidates the old link immediately.",
    copy: "Copy",
    rotateLink: "Replace link",
    disable: "Disable",
    shareLead:
      "A public link lets anyone view the presentation without signing in.",
    createShare: "Create public link",
    decisions: "Design decisions",
    audienceTakeaway: "Audience takeaway",
    legacyPlan:
      "This presentation predates the planning engine, so its written argument was not saved. Its design and slide list are shown below.",
    palette: "Colour palette",
    defaultDecisions:
      "If you skipped the questions, Nashr made these choices from your sources.",
    evidence: "Evidence",
    noEvidenceTitle: "No evidence found",
    noEvidenceHint:
      "No claims were extracted from sources for this presentation. Upload a text based PDF or DOCX to show evidence here.",
    evidenceShown: (total: number, shown: number) =>
      `Showing the first ${shown} of ${total} claims.`,
    sourceUnknown: "Unknown source",
    chunk: "chunk",
    topUp: "Payments are currently handled in the Telegram bot:",
    openBot: "open the bot",
    retry: "Try again",
    packageNames: {
      presentation_basic: "Basic",
      presentation_standard: "Standard",
      presentation_premium: "Premium",
    },
  },
  ru: {
    sourceTitle: "Источники",
    sourceEmpty:
      "Добавьте PDF, документы или заметки. Исследования и цитаты останутся рядом с черновиком.",
    sourceChoose: "Выбрать файл",
    sourceHint: "PDF, DOCX, PPTX. До 20 МБ.",
    sourceUpload: "Добавить источник",
    sourceUploading: "Загрузка",
    sourceLabel: "Источники проекта",
    chooseFirst: "Сначала выберите файл",
    uploaded: (name: string) => `${name} загружен`,
    duplicateRun: "Этот проект уже создаётся. Средства повторно не списаны.",
    fixStarting: "Применяем правку и пересобираем презентацию.",
    shareDisabled: "Публичная ссылка отключена",
    shareRotated: "Создана новая ссылка. Старая больше не работает.",
    shareEnabled: "Публичная ссылка включена",
    shareCopied: "Ссылка скопирована",
    shareCopyFailed:
      "Не удалось скопировать. Выделите ссылку и скопируйте вручную.",
    backProjects: "Назад к проектам",
    chatDisabledRunning:
      "Здесь можно будет редактировать презентацию, как только она будет готова.",
    chatDisabledEmpty:
      "Чат откроется после подготовки презентации и будет работать прямо с её слайдами.",
    fixApplying: "Применяем правку. Обычно это занимает несколько минут.",
    fixDelivering: "Правка сохранена, файлы для неё готовятся.",
    fixesRemaining: "Осталось правок",
    reconnecting: "Статус не обновляется. Переподключаемся…",
    archivedTitle: "Проект в архиве",
    archivedHint:
      "Проект можно просматривать, но новую генерацию нельзя запустить, пока он в архиве.",
    startLead:
      "Когда источники готовы, создайте презентацию. Обычно это занимает 3–6 минут.",
    createPresentation: "Создать презентацию",
    charge: (tier: string, price: string) =>
      `С баланса будет списан пакет «${tier}»: ${price}. При неудачной генерации средства вернутся автоматически.`,
    needsSource: "Добавьте ниже хотя бы один источник.",
    queued: "В очереди",
    queuedHint: "Задача поставлена в очередь. Первый этап скоро начнётся.",
    working: "В работе",
    elapsed: "Прошло",
    live: "в реальном времени",
    refreshing: "обновление",
    stalled:
      "Задача не отвечает 45 секунд. Обычно она восстанавливается сама; иначе средства вернутся автоматически.",
    refunded: "Средства возвращены",
    technical: "Технические подробности",
    restart: "Запустить заново",
    restartHint:
      "Это новая генерация с первого этапа и новым списанием средств.",
    preparingFiles: "Подготавливаем файлы",
    preparingFilesHint: "Презентация собрана, файлы сейчас публикуются.",
    delivering: "Презентация сохранена — готовим файлы",
    deliveringHint:
      "Презентация сохранена. Каждый файл появится здесь, как только будет опубликован, — перезагружать страницу не нужно.",
    deliveryFailed: "Презентация сохранена, но подготовить её файлы не удалось.",
    deliveryFailedHint:
      "Средства за этот запуск возвращены. Презентацию можно редактировать: обновите экспорт, чтобы попробовать ещё раз, или запустите новую генерацию.",
    processDetails: "Ход работы",
    deckAppears: "Презентация появится здесь.",
    noDeck: "Презентации пока нет.",
    aiImages: "ИИ-изображений",
    readyIn: "создано за",
    chat: "Чат",
    chatPlaceholder: "Что изменить?",
    chatEmptyTitle: "Обсудите презентацию с Nashr",
    chatEmptyHint:
      "Напишите «исправь дату на слайде 3» или «сократи вывод». Nashr опирается только на загруженные вами источники.",
    approvalLabel: "Подтверждение",
    approvalTitle: "Применить это изменение?",
    approve: "Применить",
    reject: "Не нужно",
    messageLabel: "Сообщение",
    sendLabel: "Отправить",
    presentation: "Презентация",
    railLabel: "Чат и ход работы",
    noSourceTitle: "Источников пока нет",
    noSourceHint:
      "Презентация опирается на факты из ваших файлов. Загрузите PDF, DOCX или PPTX до 20 МБ.",
    sourceSnapshot:
      "Презентация создана по перечисленным источникам. Чтобы учесть новый файл, запустите создание заново.",
    upload: "Загрузить",
    sharing: "Доступ",
    shareActiveHint:
      "Ссылка работает, пока вы её не отключите. После замены старая ссылка сразу перестанет работать.",
    copy: "Копировать",
    rotateLink: "Заменить ссылку",
    disable: "Отключить",
    shareLead: "Публичная ссылка позволяет открыть презентацию без входа.",
    createShare: "Создать публичную ссылку",
    decisions: "Решения по дизайну",
    audienceTakeaway: "Что унесёт аудитория",
    legacyPlan:
      "Эта презентация создана до появления планировщика, поэтому её письменная аргументация не сохранилась. Ниже показаны дизайн и список слайдов.",
    palette: "Цветовая палитра",
    defaultDecisions:
      "Если вы пропустили вопросы, Nashr сделал этот выбор по вашим источникам.",
    evidence: "Доказательства",
    noEvidenceTitle: "Доказательства не найдены",
    noEvidenceHint:
      "Для этой презентации из источников не извлечены утверждения. Загрузите текстовый PDF или DOCX, чтобы увидеть их здесь.",
    evidenceShown: (total: number, shown: number) =>
      `Показаны первые ${shown} из ${total} утверждений.`,
    sourceUnknown: "Источник неизвестен",
    chunk: "фрагмент",
    topUp: "Оплата пока проводится в Telegram-боте:",
    openBot: "открыть бота",
    retry: "Повторить",
    packageNames: {
      presentation_basic: "Базовый",
      presentation_standard: "Стандарт",
      presentation_premium: "Премиум",
    },
  },
  uz: {
    sourceTitle: "Manbalar",
    sourceEmpty:
      "PDF, hujjat yoki qaydlaringizni qo‘shing. Tadqiqot va iqtiboslar qoralama yonida turadi.",
    sourceChoose: "Fayl tanlash",
    sourceHint: "PDF, DOCX, PPTX. Maks. 20 MB.",
    sourceUpload: "Manba qo‘shish",
    sourceUploading: "Yuklanmoqda",
    sourceLabel: "Loyiha manbalari",
    chooseFirst: "Avval fayl tanlang",
    uploaded: (name: string) => `${name} yuklandi`,
    duplicateRun:
      "Bu loyiha allaqachon yaratilmoqda — hisobdan qayta yechilmadi.",
    fixStarting: "Tahrir qo‘llanmoqda — taqdimot qayta yig‘ilmoqda.",
    shareDisabled: "Havola o‘chirildi",
    shareRotated: "Yangi havola yaratildi. Eskisi bekor bo‘ldi.",
    shareEnabled: "Ommaviy havola yoqildi",
    shareCopied: "Havola nusxalandi",
    shareCopyFailed: "Nusxalab bo‘lmadi. Havolani qo‘lda belgilang.",
    backProjects: "Loyihalarga qaytish",
    chatDisabledRunning:
      "Taqdimot tayyor bo‘lgach, shu yerda uni tahrirlaysiz.",
    chatDisabledEmpty:
      "Suhbat taqdimot tayyor bo‘lgandan keyin ochiladi — u tayyor slaydlar ustida ishlaydi.",
    fixApplying: "Tahrir qo‘llanmoqda — bir necha daqiqa.",
    fixDelivering: "Tahrir saqlandi, uning fayllari tayyorlanmoqda.",
    fixesRemaining: "Qolgan tahrirlar",
    reconnecting: "Holat yangilanmayapti — qayta ulanmoqda.",
    archivedTitle: "Arxivlangan loyiha",
    archivedHint:
      "Bu loyiha arxivda. Uni ko‘rish mumkin, lekin yangi generatsiya boshlanmaydi.",
    startLead:
      "Manbalar tayyor bo‘lgach, taqdimotni buyurtma qiling. Odatda 3–6 daqiqa davom etadi.",
    createPresentation: "Taqdimot yaratish",
    charge: (tier: string, price: string) =>
      `Hisobdan ${tier} paketi yechiladi: ${price}. Muvaffaqiyatsiz bo‘lsa avtomatik qaytariladi.`,
    needsSource: "Kamida bitta manba kerak — quyida yuklang.",
    queued: "Navbatda",
    queuedHint: "Ish navbatga qo‘yildi. Birinchi bosqich boshlanmoqda.",
    working: "Ishlanmoqda",
    elapsed: "Ketgan vaqt",
    live: "jonli",
    refreshing: "yangilanmoqda",
    stalled:
      "Ish 45 soniyadan beri javob bermayapti. Odatda o‘zi tiklanadi — tiklanmasa, kredit avtomatik qaytariladi.",
    refunded: "Kredit qaytarildi",
    technical: "Texnik tafsilot",
    restart: "Qaytadan boshlash",
    restartHint:
      "Bu yangi generatsiya: jarayon birinchi bosqichdan boshlanadi va hisobdan qayta yechiladi.",
    preparingFiles: "Fayllar tayyorlanmoqda",
    preparingFilesHint: "Taqdimot yig‘ildi — fayllar hozir joylanmoqda.",
    delivering: "Taqdimot saqlandi — fayllar tayyorlanmoqda",
    deliveringHint:
      "Taqdimot saqlandi. Har bir fayl joylanishi bilan shu yerda paydo bo‘ladi — sahifani yangilash shart emas.",
    deliveryFailed: "Taqdimot saqlandi, lekin uning fayllarini tayyorlab bo‘lmadi.",
    deliveryFailedHint:
      "Bu ishga yechilgan mablag‘ qaytarildi. Taqdimotni tahrirlash mumkin: fayllarni qayta urinish uchun eksportni yangilang yoki yangi generatsiya boshlang.",
    processDetails: "Jarayon tafsiloti",
    deckAppears: "Taqdimot shu yerda paydo bo‘ladi.",
    noDeck: "Hali taqdimot yo‘q.",
    aiImages: "AI rasm",
    readyIn: "ichida tayyorlandi",
    chat: "Suhbat",
    chatPlaceholder: "Nimani o‘zgartiramiz?",
    chatEmptyTitle: "Taqdimot ustida gaplashamiz",
    chatEmptyHint:
      "«3-slayddagi sanani to‘g‘rila» yoki «xulosani qisqartir» deb yozing. Nashr faqat siz yuklagan manbalardagi faktlarga tayanadi.",
    approvalLabel: "Tasdiqlash",
    approvalTitle: "Bu o‘zgarishni qo‘llaymizmi?",
    approve: "Qo‘llash",
    reject: "Kerak emas",
    messageLabel: "Xabar",
    sendLabel: "Yuborish",
    presentation: "Taqdimot",
    railLabel: "Suhbat va jarayon",
    noSourceTitle: "Manba yuklanmagan",
    noSourceHint:
      "Taqdimot faqat siz yuklagan fayllardagi faktlarga tayanadi. PDF, DOCX yoki PPTX yuklang (maks. 20 MB).",
    sourceSnapshot:
      "Taqdimot shu manbalar asosida yig‘ilgan. Yangi fayl qo‘shsangiz, uni qo‘shish uchun qaytadan yaratish kerak.",
    upload: "Yuklash",
    sharing: "Ulashish",
    shareActiveHint:
      "Havola siz o‘chirmaguningizcha ishlaydi. Yangilasangiz, eskisi darhol bekor bo‘ladi.",
    copy: "Nusxalash",
    rotateLink: "Havolani yangilash",
    disable: "O‘chirish",
    shareLead:
      "Ommaviy havola taqdimotni istalgan kishiga, kirmasdan, ko‘rsatadi.",
    createShare: "Ommaviy havola yaratish",
    decisions: "Nima qaror qilindi",
    audienceTakeaway: "Tinglovchi nima bilan chiqadi",
    legacyPlan:
      "Bu taqdimot reja mexanizmi joriy qilinishidan oldin yaratilgan, shuning uchun uning yozma argumenti saqlanmagan. Dizayn va slaydlar ro‘yxati quyida.",
    palette: "Rang palitrasi",
    defaultDecisions:
      "Savollarga javob bermagan bo‘lsangiz, bu tanlovlarni manbalaringiz asosida Nashr o‘zi qildi.",
    evidence: "Dalillar",
    noEvidenceTitle: "Dalil topilmadi",
    noEvidenceHint:
      "Bu taqdimot uchun manbalardan da’vo ajratilmagan. Matnli PDF yoki DOCX yuklasangiz, dalillar shu yerda ko‘rinadi.",
    evidenceShown: (total: number, shown: number) =>
      `${total} ta da’vodan birinchi ${shown} tasi ko‘rsatilgan.`,
    sourceUnknown: "Manba noma’lum",
    chunk: "bo‘lak",
    topUp: "To‘lov hozircha Telegram botda:",
    openBot: "botni ochish",
    retry: "Qayta urinish",
    packageNames: {
      presentation_basic: "Oddiy",
      presentation_standard: "Standart",
      presentation_premium: "Premium",
    },
  },
  kaa: {
    sourceTitle: "Derekler",
    sourceEmpty:
      "PDF, hújjet yamasa jazbalarıńızdı qosıń. Izertlew hám iqtiboslar qaralama janında turadı.",
    sourceChoose: "Fayl tańlaw",
    sourceHint: "PDF, DOCX, PPTX. Maks. 20 MB.",
    sourceUpload: "Derek qosıw",
    sourceUploading: "Júklenbekte",
    sourceLabel: "Loyiha derekleri",
    chooseFirst: "Aldın fayl tańlań",
    uploaded: (name: string) => `${name} júklendi`,
    duplicateRun:
      "Bul loyiha áldeqashan jaratılbaqta — esaptan qayta alınbadı.",
    fixStarting: "Redaktorlaw qollanbaqta — prezentaciya qayta jıynalbaqta.",
    shareDisabled: "Silteme óshirildi",
    shareRotated: "Jańa silteme jaratıldı. Eskisi biykar boldı.",
    shareEnabled: "Járiya silteme qosıldı",
    shareCopied: "Silteme kóshirildi",
    shareCopyFailed: "Kóshirip bolmadı. Siltemeni qolda belgileń.",
    backProjects: "Loyihalarǵa qaytıw",
    chatDisabledRunning:
      "Prezentaciya tayar bolǵannan keyin, usı jerde onı redaktorlaysız.",
    chatDisabledEmpty:
      "Sáwbet prezentaciya tayar bolǵannan keyin ashıladı — ol tayar slaydlar ústinde isleydi.",
    fixApplying: "Redaktorlaw qollanbaqta — bir neshe minut.",
    fixDelivering: "Redaktorlaw saqlandı, onıń faylları tayarlanbaqta.",
    fixesRemaining: "Qalǵan redaktorlawlar",
    reconnecting: "Halat jańalanbay atır — qayta jalǵanbaqta.",
    archivedTitle: "Arxivlengen loyiha",
    archivedHint:
      "Bul loyiha arxivte. Onı kóriwge boladı, biraq jańa generaciya baslanbaydı.",
    startLead:
      "Derekler tayar bolǵannan keyin, prezentaciyanı buyırtpa etiń. Ádette 3–6 minut dawam etedi.",
    createPresentation: "Prezentaciya jaratıw",
    charge: (tier: string, price: string) =>
      `Esaptan ${tier} paketi alınadı: ${price}. Sátsiz bolsa avtomat túrde qaytarıladı.`,
    needsSource: "Keminde bir derek kerek — tómende júkleń.",
    queued: "Gezekte",
    queuedHint: "Jumıs gezekke qoyıldı. Birinshi basqısh baslanbaqta.",
    working: "Islenbekte",
    elapsed: "Ótken waqıt",
    live: "janlı",
    refreshing: "jańalanbaqta",
    stalled:
      "Jumıs 45 sekundtan beri juwap bermey atır. Ádette ózi tiklenedi — tiklenbese, kredit avtomat túrde qaytarıladı.",
    refunded: "Kredit qaytarıldı",
    technical: "Texnikalıq maǵlıwmat",
    restart: "Qaytadan baslaw",
    restartHint:
      "Bul jańa generaciya: process birinshi basqıshtan baslanadı hám esaptan qayta alınadı.",
    preparingFiles: "Fayllar tayarlanbaqta",
    preparingFilesHint: "Prezentaciya jıynaldı — fayllar házir jaylanbaqta.",
    delivering: "Prezentaciya saqlandı — fayllar tayarlanbaqta",
    deliveringHint:
      "Prezentaciya saqlandı. Hár bir fayl jaylanıwı menen usı jerde payda boladı — betti jańalaw shárt emes.",
    deliveryFailed: "Prezentaciya saqlandı, biraq onıń faylların tayarlap bolmadı.",
    deliveryFailedHint:
      "Bul jumısqa alınǵan aqsha qaytarıldı. Prezentaciyanı redaktorlawǵa boladı: fayllardı qayta urınıw ushın eksporttı jańalań yamasa jańa generaciya baslań.",
    processDetails: "Process maǵlıwmatı",
    deckAppears: "Prezentaciya usı jerde payda boladı.",
    noDeck: "Ele prezentaciya joq.",
    aiImages: "AI súwret",
    readyIn: "ishinde tayarlandı",
    chat: "Sáwbet",
    chatPlaceholder: "Neni ózgertemiz?",
    chatEmptyTitle: "Prezentaciya ústinde sóylesemiz",
    chatEmptyHint:
      "«3-slaydtaǵı sáneni durısla» yamasa «juwmaqtı qısqart» dep jazıń. Nashr tek siz júklegen dereklerdegi faktlerge súyenedi.",
    approvalLabel: "Tastıyıqlaw",
    approvalTitle: "Bul ózgeristi qollaymız ba?",
    approve: "Qollaw",
    reject: "Kerek emes",
    messageLabel: "Xabar",
    sendLabel: "Jiberiw",
    presentation: "Prezentaciya",
    railLabel: "Sáwbet hám process",
    noSourceTitle: "Derek júklenbegen",
    noSourceHint:
      "Prezentaciya tek siz júklegen fayllardaǵı faktlerge súyenedi. PDF, DOCX yamasa PPTX júkleń (maks. 20 MB).",
    sourceSnapshot:
      "Prezentaciya usı derekler tiykarında jıynalǵan. Jańa fayl qossańız, onı qosıw ushın qaytadan jaratıw kerek.",
    upload: "Júklew",
    sharing: "Bólisiw",
    shareActiveHint:
      "Silteme siz óshirmegenińizshe isleydi. Jańalasańız, eskisi derhal biykar boladı.",
    copy: "Kóshiriw",
    rotateLink: "Siltemeni jańalaw",
    disable: "Óshiriw",
    shareLead:
      "Járiya silteme prezentaciyanı qálegen adamǵa, kirmey-aq, kórsetedi.",
    createShare: "Járiya silteme jaratıw",
    decisions: "Ne sheshim etildi",
    audienceTakeaway: "Tıńlawshı ne menen shıǵadı",
    legacyPlan:
      "Bul prezentaciya reje mexanizmi engiziliwinen aldın jaratılǵan, sonlıqtan onıń jazba argumenti saqlanbaǵan. Dizayn hám slaydlar dizimi tómende.",
    palette: "Reń palitrası",
    defaultDecisions:
      "Sorawlarǵa juwap bermegen bolsańız, bul tańlawlardı dereklerińiz tiykarında Nashr ózi isledi.",
    evidence: "Dáliller",
    noEvidenceTitle: "Dálil tabılmadı",
    noEvidenceHint:
      "Bul prezentaciya ushın dereklerden da'wa ajratılmaǵan. Tekstli PDF yamasa DOCX júkleseńiz, dáliller usı jerde kórinedi.",
    evidenceShown: (total: number, shown: number) =>
      `${total} da'wadan birinshi ${shown} kórsetilgen.`,
    sourceUnknown: "Derek belgisiz",
    chunk: "bólek",
    topUp: "Tólem házirshe Telegram-botta:",
    openBot: "bottı ashıw",
    retry: "Qayta urınıw",
    packageNames: {
      presentation_basic: "Ápiwayı",
      presentation_standard: "Standart",
      presentation_premium: "Premium",
    },
  },
} satisfies Record<Locale, Record<string, unknown>>;

export type WorkspaceCopy = (typeof WORKSPACE_COPY)[Locale];
