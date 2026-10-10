# Матрица трассировки FLT

> Связь BRD ↔ ТЗ ↔ тесты ↔ статус для каждого пункта бизнес-требований.
> Основа: [FLT_BRD.md](BRD/FLT_BRD.md) и [SDD_plan.md](BRD/SDD_plan.md) (Приложение А, разделы этапов). Правила процесса: [CLAUDE.md](../CLAUDE.md).
> Версия 0.4 от 2026-10-10, статус: **draft**.

## 1. Назначение

Матрица показывает для каждого пункта BRD: в каком ТЗ он специфицирован, на каком этапе реализуется, какой модуль им владеет, какими тестами покрыт и в каком состоянии находится. По матрице проверяется, что ни один пункт BRD не остался без ТЗ и тестов, и считается готовность этапа для гейта GS.

## 2. Источник истины для столбцов

| Столбец | Источник истины |
|---|---|
| ID, Пункт BRD, Этап, Модули | SDD_plan.md, Приложение А (реестр пунктов BRD); подпункты и разделение пунктов на базовую часть и расширение — разделы «Этап 4», «Этап 5», «Этап 7» |
| ТЗ | путь к файлу `Analytics/Specs/<модуль>/<ID>-<slug>.md`; пока ТЗ не создано — ожидаемый путь |
| Статус ТЗ | поле статуса в метаданных самого ТЗ; для SYS — метаданные системной спецификации, для ADR — метаданные ADR |
| Тесты (теги) | теги с ID критериев приёмки (`<ID ТЗ>-AC<N>`): маркеры pytest, имена тестов Vitest, теги Playwright. Формат ячейки после заполнения: `<ID>-AC1…AC<N> (покрыто/всего)`, например `STU-18-AC1…AC7 (7/7)` |
| Реализация | результат гейтов G2 и G3 конвейера (SDD_plan.md, разделы 4 и 5) |

Матрица — производный документ. При расхождении с ТЗ или тестами правится матрица, а не они.

## 3. Правило обновления

- Матрица обновляется на шаге 14 конвейера реализации фичи (SDD_plan.md, раздел 5) вместе со спецификацией модуля и переводом ТЗ в статус `implemented`; также при изменении требований (SDD_plan.md, раздел 9, пункт 5) и в конце каждого этапа (SDD_plan.md, раздел 8, пункт 2).
- На этапе 1 по SYS-12 генерация матрицы автоматизируется в CI: столбцы «Статус ТЗ» и «Тесты (теги)» заполняются из метаданных ТЗ и тегов тестов. До этого матрица ведётся вручную.
- Строки добавляются при появлении новых пунктов BRD и при разделении пункта на несколько ТЗ. Строки не удаляются: для снятого требования ставится статус ТЗ `changed` и пометка «снято» в столбце «Пункт BRD».

## 4. Легенда

**Статус ТЗ** (SDD_plan.md, раздел 4):

| Значение | Смысл |
|---|---|
| — | ТЗ ещё не создано |
| draft | черновик написан, ревью не проходил |
| review | на ревью у человека (гейт G1) |
| approved | утверждено, можно писать контракты и тесты |
| in-progress | идут шаги 4–13 конвейера |
| implemented | фича реализована, тесты зелёные, документация обновлена |
| changed | требования изменились после утверждения, ТЗ проходит цикл заново |

**Статус ADR** (`Analytics/Specs/_templates/README.md`, раздел «Жизненный цикл статусов и гейты», и шаблон `adr.md`):

| Значение | Смысл |
|---|---|
| — | ADR ещё не создан |
| proposed | черновик решения написан, решение человеком не принято |
| accepted | решение принято человеком; по существу ADR больше не редактируется, новое решение оформляется новым ADR |
| superseded | заменён другим ADR: решение больше не действует, ADR содержит ссылку на заменивший его ADR |
| rejected | решение отклонено человеком, ADR остаётся в репозитории, его номер не переиспользуется |

**Реализация**:

| Значение | Смысл |
|---|---|
| не начато | кода и тестов по ТЗ нет |
| в работе | написаны тесты (red) или часть кода, гейт G3 не пройден |
| готово | все тесты зелёные, Definition of Done выполнен, ожидает приёмки (гейт G3) |
| принято | гейт G3 пройден, изменения слиты в main |

## 5. Соглашения о строках

- Один пункт BRD — одна строка. Исключения перечислены ниже.
- Пункт с подпунктами (STU-01, STU-34, STU-35) имеет строку самого пункта и по строке на каждый подпункт. ТЗ строки самого пункта описывает общую часть — требования, одинаковые для всех подпунктов; ТЗ подпункта описывает только его особенности.
- Пункт, разнесённый по двум этапам (STU-03, STU-12, STU-32), имеет две строки: базовая часть (этап 4) и расширение (этап 5). ID ТЗ назначены по правилу SDD_plan.md, раздел 3: `<ID>.1` — базовая часть, `<ID>.2` — расширение.
- У пункта с несколькими модулями ТЗ лежит в папке модуля-владельца — первого в списке столбца «Модули».
- Slug в имени файла ТЗ, SYS и ADR — от двух до пяти английских слов в kebab-case, по правилам имён из `Analytics/Specs/_templates/README.md`. Пока документ не создан, путь в матрице — ожидаемый: slug уточняется при создании документа и не меняется после его утверждения.

## 6. Посетитель портала

| ID | Пункт BRD | Этап | Модули | ТЗ | Статус ТЗ | Тесты (теги) | Реализация |
|---|---|---|---|---|---|---|---|
| VIS-01 | Просмотр основных возможностей платформы (включая демо-видео) | 2 | cms | `Analytics/Specs/cms/VIS-01-platform-overview.md` | — | — | не начато |
| VIS-02 | Просмотр каталога курсов | 2 | courses | `Analytics/Specs/courses/VIS-02-course-catalog.md` | — | — | не начато |
| VIS-03 | Быстрый тест без регистрации (своя модель или модель платформы) | 2 | assessment, lessons, llm_gateway | `Analytics/Specs/assessment/VIS-03-quick-test.md` | — | — | не начато |
| VIS-04 | Регистрация | 2 | identity | `Analytics/Specs/identity/VIS-04-user-registration.md` | — | — | не начато |
| VIS-05 | Вход в систему | 2 | identity | `Analytics/Specs/identity/VIS-05-user-login.md` | — | — | не начато |

## 7. Администратор платформы

| ID | Пункт BRD | Этап | Модули | ТЗ | Статус ТЗ | Тесты (теги) | Реализация |
|---|---|---|---|---|---|---|---|
| ADM-01 | Управление пользователями (атрибуты, временное отключение) | 3 | identity, audit | `Analytics/Specs/identity/ADM-01-user-management.md` | — | — | не начато |
| ADM-02 | Управление курсами (отключение, бан преподавателей) | 3 | courses, identity, audit | `Analytics/Specs/courses/ADM-02-course-management.md` | — | — | не начато |
| ADM-03 | Управление контентом стартовой и основных страниц (CMS) | 3 | cms, audit | `Analytics/Specs/cms/ADM-03-cms-page-management.md` | — | — | не начато |
| ADM-04 | Модерация публикуемых плагинов | 7 | plugins, audit | `Analytics/Specs/plugins/ADM-04-plugin-moderation.md` | — | — | не начато |
| ADM-05 | Модерация социальных возможностей (жалобы, записи, страницы, группы) | 7 | social, audit | `Analytics/Specs/social/ADM-05-social-moderation.md` | — | — | не начато |
| ADM-06 | Продвижение платформы от имени персонажа-ведущего (каналы Telegram и VK, тематические группы, расписание публикаций, модерация) | 7 | promotion, social, audit | `Analytics/Specs/promotion/ADM-06-persona-promotion.md` | — | — | не начато |

## 8. Ученик

| ID | Пункт BRD | Этап | Модули | ТЗ | Статус ТЗ | Тесты (теги) | Реализация |
|---|---|---|---|---|---|---|---|
| STU-01 | Подключение внешней LLM (OpenAI, Claude, YandexGPT, GigaChat и др.) — общая часть | 4 | llm_gateway | `Analytics/Specs/llm_gateway/STU-01-external-llm-connection.md` | — | — | не начато |
| STU-01.1 | Подключение внешней LLM — провайдер OpenAI | 4 | llm_gateway | `Analytics/Specs/llm_gateway/STU-01.1-openai-provider.md` | — | — | не начато |
| STU-01.2 | Подключение внешней LLM — провайдер Claude | 4 | llm_gateway | `Analytics/Specs/llm_gateway/STU-01.2-claude-provider.md` | — | — | не начато |
| STU-01.3 | Подключение внешней LLM — провайдер YandexGPT | 4 | llm_gateway | `Analytics/Specs/llm_gateway/STU-01.3-yandexgpt-provider.md` | — | — | не начато |
| STU-01.4 | Подключение внешней LLM — провайдер GigaChat | 4 | llm_gateway | `Analytics/Specs/llm_gateway/STU-01.4-gigachat-provider.md` | — | — | не начато |
| STU-02 | Подключение локальной модели (llama.cpp, автоскачивание) | 5 | local_runtime, llm_gateway | `Analytics/Specs/local_runtime/STU-02-llama-cpp-local-model.md` | — | — | не начато |
| STU-03.1 | Выбор внешней или локальной модели — базовая часть: тип модели (внешняя или локальная) и конкретная модель | 4 | llm_gateway, learner_profile | `Analytics/Specs/llm_gateway/STU-03.1-model-selection.md` | — | — | не начато |
| STU-03.2 | Выбор внешней или локальной модели — расширение: квантование и параметры локальной модели | 5 | llm_gateway, learner_profile | `Analytics/Specs/llm_gateway/STU-03.2-local-model-parameters.md` | — | — | не начато |
| STU-04 | Автоматическое предложение модели под запросы и железо | 5 | local_runtime | `Analytics/Specs/local_runtime/STU-04-model-recommendation.md` | — | — | не начато |
| STU-05 | Подключение к локальному LM Studio | 4 | llm_gateway, local_runtime | `Analytics/Specs/llm_gateway/STU-05-lm-studio-connection.md` | — | — | не начато |
| STU-06 | Выбор языка интерфейса | 4 | learner_profile | `Analytics/Specs/learner_profile/STU-06-interface-language.md` | — | — | не начато |
| STU-07 | Выбор изучаемого языка | 4 | learner_profile | `Analytics/Specs/learner_profile/STU-07-studied-language.md` | — | — | не начато |
| STU-08 | Поддержка всех европейских языков | 4 | languages | `Analytics/Specs/languages/STU-08-european-languages.md` | — | — | не начато |
| STU-09 | Языки с написанием слева направо и справа налево | 5 | languages | `Analytics/Specs/languages/STU-09-rtl-languages.md` | — | — | не начато |
| STU-10 | Языки на основе вязи | 5 | languages | `Analytics/Specs/languages/STU-10-cursive-script-languages.md` | — | — | не начато |
| STU-11 | Языки на основе иероглифов | 5 | languages | `Analytics/Specs/languages/STU-11-logographic-languages.md` | — | — | не начато |
| STU-12.1 | Словари (значения, примеры, фразеологизмы, грамматика) — базовая часть: европейские языки, генерация статей LLM ученика, общий кэш статей в PostgreSQL с индексом в OpenSearch | 4 | dictionary | `Analytics/Specs/dictionary/STU-12.1-dictionary-base.md` | — | — | не начато |
| STU-12.2 | Словари — расширение: языки с письмом справа налево, на основе вязи и иероглифов | 5 | dictionary | `Analytics/Specs/dictionary/STU-12.2-dictionary-rtl-cursive-logographic.md` | — | — | не начато |
| STU-13 | Произношение в словаре (возраст, пол, акцент) | 5 | speech, dictionary | `Analytics/Specs/speech/STU-13-dictionary-pronunciation.md` | — | — | не начато |
| STU-14 | Выбор текущего уровня (A1–C2) | 4 | learner_profile | `Analytics/Specs/learner_profile/STU-14-current-level.md` | — | — | не начато |
| STU-15 | Автоматическое определение текущего уровня | 4 | assessment | `Analytics/Specs/assessment/STU-15-automatic-level-assessment.md` | — | — | не начато |
| STU-16 | Выбор уровня языка, используемого в занятиях сейчас | 4 | learner_profile | `Analytics/Specs/learner_profile/STU-16-working-level.md` | — | — | не начато |
| STU-17 | Выбор целевого уровня | 4 | learner_profile | `Analytics/Specs/learner_profile/STU-17-target-level.md` | — | — | не начато |
| STU-18 | Пошаговая программа обучения (интенсивность, длительность, срок) | 4 | learning_plan | `Analytics/Specs/learning_plan/STU-18-learning-plan.md` | — | — | не начато |
| STU-19 | Отслеживание прогресса | 4 | progress | `Analytics/Specs/progress/STU-19-progress-tracking.md` | — | — | не начато |
| STU-20 | Теоретические занятия | 4 | lessons | `Analytics/Specs/lessons/STU-20-theory-lessons.md` | — | — | не начато |
| STU-21 | Практические занятия | 4 | lessons | `Analytics/Specs/lessons/STU-21-practice-lessons.md` | — | — | не начато |
| STU-22 | Тренинги на выбранную тему | 5 | lessons | `Analytics/Specs/lessons/STU-22-topic-trainings.md` | — | — | не начато |
| STU-23 | Подготовка к TOEFL и аналогам (в первой версии TOEFL и IELTS) | 5 | lessons, assessment | `Analytics/Specs/lessons/STU-23-exam-preparation.md` | — | — | не начато |
| STU-24 | Продвинутые параметры обучения | 5 | learner_profile, learning_plan | `Analytics/Specs/learner_profile/STU-24-advanced-learning-parameters.md` | — | — | не начато |
| STU-25 | Подключение MCP, скилов, настройки harness | 7 | plugins, llm_gateway | `Analytics/Specs/plugins/STU-25-mcp-skills-harness.md` | — | — | не начато |
| STU-26 | Темы ученика | 4 | learner_profile | `Analytics/Specs/learner_profile/STU-26-learner-topics.md` | — | — | не начато |
| STU-27 | Загрузка собственных материалов | 5 | materials | `Analytics/Specs/materials/STU-27-own-materials.md` | — | — | не начато |
| STU-28 | Голосовое общение с преподавателем | 5 | speech | `Analytics/Specs/speech/STU-28-voice-conversation.md` | — | — | не начато |
| STU-29 | Визуальный аватар преподавателя | 5 | avatar | `Analytics/Specs/avatar/STU-29-teacher-avatar.md` | — | — | не начато |
| STU-30 | Вайбкодинг собственных плагинов | 7 | plugins | `Analytics/Specs/plugins/STU-30-plugin-vibecoding.md` | — | — | не начато |
| STU-31 | Публикация и шаринг плагинов | 7 | plugins | `Analytics/Specs/plugins/STU-31-plugin-publishing.md` | — | — | не начато |
| STU-32.1 | Wizard первоначальной настройки — базовая часть: языки → LLM → уровень → программа | 4 | learner_profile (frontend) | `Analytics/Specs/learner_profile/STU-32.1-setup-wizard-base.md` | — | — | не начато |
| STU-32.2 | Wizard первоначальной настройки — расширение: подробная настройка | 5 | learner_profile (frontend) | `Analytics/Specs/learner_profile/STU-32.2-setup-wizard-advanced.md` | — | — | не начато |
| STU-33 | Отдельный параллельный прогресс на разных языках | 4 | progress, learner_profile | `Analytics/Specs/progress/STU-33-parallel-language-progress.md` | — | — | не начато |
| STU-34 | Режим заучивания слов и выражений (десктопный с уведомлениями и аудио) — общая часть | 5 | memorization, dictionary, speech, progress | `Analytics/Specs/memorization/STU-34-memorization-mode.md` | — | — | не начато |
| STU-34.1 | Режим заучивания — десктопный вариант: всплывающие уведомления на рабочем столе, частота показа, «тихие часы», ответ «помню/не помню» или ввод | 5 | memorization, speech | `Analytics/Specs/memorization/STU-34.1-desktop-notifications.md` | — | — | не начато |
| STU-34.2 | Режим заучивания — аудио-вариант без экрана в мобильном браузере: проговаривание, пауза, перевод и пример, голосовой ответ, управление голосом и кнопками | 5 | memorization, speech | `Analytics/Specs/memorization/STU-34.2-audio-mode.md` | — | — | не начато |
| STU-35 | Социальные возможности: страницы, записи, друзья, группы, сообщения — общая часть | 7 | social, messaging | `Analytics/Specs/social/STU-35-social-features.md` | — | — | не начато |
| STU-35.1 | Собственная страница ученика: аватар, о себе, языки и уровни, достижения по желанию ученика | 7 | social | `Analytics/Specs/social/STU-35.1-learner-page.md` | — | — | не начато |
| STU-35.2 | Записи на странице: текст, изображения, ссылки; комментарии и отметки «нравится» | 7 | social | `Analytics/Specs/social/STU-35.2-posts-comments-likes.md` | — | — | не начато |
| STU-35.3 | Друзья и подписки, лента новостей от друзей и групп | 7 | social | `Analytics/Specs/social/STU-35.3-friends-and-feed.md` | — | — | не начато |
| STU-35.4 | Группы учеников: открытые и закрытые, приглашения и заявки, роли владельца и модераторов, лента группы | 7 | social | `Analytics/Specs/social/STU-35.4-learner-groups.md` | — | — | не начато |
| STU-35.5 | Личные сообщения между учениками | 7 | social, messaging | `Analytics/Specs/social/STU-35.5-direct-messages.md` | — | — | не начато |
| STU-35.6 | Поиск учеников и групп | 7 | social | `Analytics/Specs/social/STU-35.6-learner-and-group-search.md` | — | — | не начато |
| STU-35.7 | Приватность: видимость страницы, записей и прогресса, кто может писать; блокировка пользователей и жалобы на контент | 7 | social | `Analytics/Specs/social/STU-35.7-privacy-blocking-reports.md` | — | — | не начато |
| STU-36 | Живой персонаж-ведущий платформы (имя, характер, визуальный образ, поведенческие паттерны при повторных входах) | 5 | avatar, lessons, llm_gateway | `Analytics/Specs/avatar/STU-36-platform-persona.md` | — | — | не начато |

## 9. Администратор преподавателя/класса

| ID | Пункт BRD | Этап | Модули | ТЗ | Статус ТЗ | Тесты (теги) | Реализация |
|---|---|---|---|---|---|---|---|
| TCH-01 | Все возможности Ученика | 6 | identity | `Analytics/Specs/identity/TCH-01-teacher-role.md` | — | — | не начато |
| TCH-02 | Создание преднастроенных курсов | 6 | courses | `Analytics/Specs/courses/TCH-02-course-creation.md` | — | — | не начато |
| TCH-03 | Наполнение курсов контентом | 6 | courses, materials | `Analytics/Specs/courses/TCH-03-course-content.md` | — | — | не начато |
| TCH-04 | Настройка аватара преподавателя для ученика | 6 | avatar | `Analytics/Specs/avatar/TCH-04-avatar-for-learner.md` | — | — | не начато |
| TCH-05 | Прогресс учеников и корректировка планов | 6 | progress, learning_plan | `Analytics/Specs/progress/TCH-05-learner-progress-and-plan-adjustment.md` | — | — | не начато |
| TCH-06 | Индивидуальное общение с учениками | 6 | messaging | `Analytics/Specs/messaging/TCH-06-individual-messaging.md` | — | — | не начато |
| TCH-07 | Управление расписанием групповых занятий | 6 | classroom | `Analytics/Specs/classroom/TCH-07-group-lesson-schedule.md` | — | — | не начато |
| TCH-08 | Общение в классе (на занятиях и офлайн) | 6 | classroom, messaging | `Analytics/Specs/classroom/TCH-08-class-communication.md` | — | — | не начато |
| TCH-09 | Wizard настройки курсов и классов | 6 | courses, classroom | `Analytics/Specs/courses/TCH-09-course-and-class-wizard.md` | — | — | не начато |

## 10. Системные спецификации и ADR

Названия — из SDD_plan.md, разделы «Этап 1» и «Этап 7». Пути — по SDD_plan.md, раздел 2. Статус SYS ведётся по легенде статусов ТЗ, статус ADR — по легенде статусов ADR (раздел 4, значения по шаблону ADR). Черновики ADR-001…ADR-015 написаны 2026-10-10 в ветке `spec/stage-1-adr` и приняты пользователем 2026-10-10 (PR #2; статус `accepted`, версия 1.0 каждого); открытые вопросы, выявленные при их написании, — OQ-59…OQ-76 в `Analytics/open-questions.md` (решения, принятые вместе с ADR, записаны там же).

| ID | Название | Этап | Путь | Статус |
|---|---|---|---|---|
| SYS-01 | Карта модулей | 1 | `Analytics/Specs/_system/SYS-01-module-map.md` | — |
| SYS-02 | Нефункциональные требования | 1 | `Analytics/Specs/_system/SYS-02-non-functional-requirements.md` | — |
| SYS-03 | Конвенции REST API | 1 | `Analytics/Specs/_system/SYS-03-rest-api-conventions.md` | — |
| SYS-04 | Асинхронное взаимодействие (WebSocket, Kafka) | 1 | `Analytics/Specs/_system/SYS-04-async-messaging.md` | — |
| SYS-05 | Масштабирование и хранение состояния | 1 | `Analytics/Specs/_system/SYS-05-state-and-scaling.md` | — |
| SYS-06 | Роли и права | 1 | `Analytics/Specs/_system/SYS-06-roles-and-permissions.md` | — |
| SYS-07 | i18n | 1 | `Analytics/Specs/_system/SYS-07-i18n-and-rtl.md` | — |
| SYS-08 | LLM-шлюз | 1 | `Analytics/Specs/_system/SYS-08-llm-gateway.md` | — |
| SYS-09 | Точки расширения для будущих плагинов | 1 | `Analytics/Specs/_system/SYS-09-extension-points.md` | — |
| SYS-10 | Тестовая стратегия | 1 | `Analytics/Specs/_system/SYS-10-test-strategy.md` | — |
| SYS-11 | Развёртывание | 1 | `Analytics/Specs/_system/SYS-11-deployment-and-environments.md` | — |
| SYS-12 | CI/CD и качество | 1 | `Analytics/Specs/_system/SYS-12-ci-cd-and-quality.md` | — |
| SYS-13 | Архитектура плагинов | 7 | `Analytics/Specs/_system/SYS-13-plugin-architecture.md` | — |
| ADR-001 | Стек и политика версий (Python и FastAPI, React и TypeScript, переход на Python 3.14) | 1 | `Analytics/ADR/ADR-001-tech-stack.md` | accepted |
| ADR-002 | Раскладка доменных модулей в boilerplate, скаффолдер, контроль границ модулей | 1 | `Analytics/ADR/ADR-002-module-layout.md` | accepted |
| ADR-003 | Хранение состояния (PostgreSQL, Redis, крупные файлы) | 1 | `Analytics/ADR/ADR-003-state-storage.md` | accepted |
| ADR-004 | Взаимодействие (REST, WebSocket, Kafka, outbox, роли API и воркера) | 1 | `Analytics/ADR/ADR-004-communication-patterns.md` | accepted |
| ADR-005 | Frontend на основе bulletproof-react (версии, i18n и RTL, генерация клиента, покрытие) | 1 | `Analytics/ADR/ADR-005-frontend-stack.md` | accepted |
| ADR-006 | Аутентификация и авторизация | 1 | `Analytics/ADR/ADR-006-authentication-and-authorization.md` | accepted |
| ADR-007 | Файловое хранилище MinIO (S3) | 1 | `Analytics/ADR/ADR-007-file-storage.md` | accepted |
| ADR-008 | Локальный агент | 1 | `Analytics/ADR/ADR-008-local-agent.md` | accepted |
| ADR-009 | Стриминг ответов LLM через WebSocket, передача голоса | 1 | `Analytics/ADR/ADR-009-llm-streaming-and-voice.md` | accepted |
| ADR-010 | Наблюдаемость | 1 | `Analytics/ADR/ADR-010-observability-stack.md` | accepted |
| ADR-011 | CI/CD | 1 | `Analytics/ADR/ADR-011-ci-cd.md` | accepted |
| ADR-012 | HAProxy как единая точка входа | 1 | `Analytics/ADR/ADR-012-haproxy-entry-point.md` | accepted |
| ADR-013 | Секреты (Vault в Kubernetes, переменные окружения в docker-compose) | 1 | `Analytics/ADR/ADR-013-secrets-management.md` | accepted |
| ADR-014 | Поиск (OpenSearch, Qdrant) | 1 | `Analytics/ADR/ADR-014-search-engines.md` | accepted |
| ADR-015 | Медиасервер для видеосвязи на групповых занятиях | 1 (нужно к этапу 6) | `Analytics/ADR/ADR-015-media-server.md` | accepted |

## 11. Сводка по этапам

Число пунктов BRD считается по строкам разделов 6–9: с подпунктами и с разделёнными строками базовой части и расширения. Этап 1 не содержит пунктов BRD: на нём пишутся SYS-01…SYS-12 и ADR-001…ADR-015 и строится каркас.

| Этап | Пунктов BRD (строк) | ТЗ в статусе implemented | Доля |
|---|---|---|---|
| 1 | 0 | 0 | — |
| 2 | 5 | 0 | 0 % |
| 3 | 3 | 0 | 0 % |
| 4 | 22 | 0 | 0 % |
| 5 | 19 | 0 | 0 % |
| 6 | 9 | 0 | 0 % |
| 7 | 14 | 0 | 0 % |
| Итого | 72 | 0 | 0 % |

По ролям: Посетитель портала — 5 строк, Администратор платформы — 6 (ADM-06 добавлен 2026-10-10), Ученик — 52 (36 пунктов STU-01…STU-36, из них STU-03, STU-12 и STU-32 даны двумя строками каждый, плюс 13 подпунктов: STU-01.1…STU-01.4, STU-34.1, STU-34.2, STU-35.1…STU-35.7; STU-36 добавлен 2026-10-10), Администратор преподавателя/класса — 9.
