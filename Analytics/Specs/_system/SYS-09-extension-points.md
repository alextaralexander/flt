# SYS-09 — Точки расширения для будущих плагинов

| Поле | Значение |
|---|---|
| Статус | approved |
| Версия | 1.0 |
| Дата | 2026-10-11 |
| Автор | Claude (черновик) |
| Утвердил | пользователь, 2026-10-11 (PR #3) |
| Пункт(ы) BRD | STU-25, STU-30, STU-31, ADM-04 (плагины, этап 7 — здесь закладываются интерфейсы); STU-01–STU-05 (провайдеры LLM), STU-08–STU-11 (реестр языков), STU-13, STU-28 (провайдеры речи), STU-20–STU-23 (типы заданий, экзамены) |
| Модуль | shared kernel (`app/core/extensions`), app_shell (`src/lib/extension-points`), владельцы точек: `languages`, `llm_gateway`, `speech`, `lessons`, `assessment`; все модули — через `ModuleDefinition.extension_points` |
| Зависимости | ADR-002 (`ModuleDefinition`, подпакет `public`, import-linter), ADR-004 (декларации топиков `public/topics.py`, контейнер зависимостей), ADR-005 (зоны ESLint, запрет barrel-файлов), SYS-08 (интерфейсы `LLMProvider`, `EmbeddingsProvider`, провайдеры речи) |
| Связанные ADR/SYS | ADR-008 (локальный агент как реализация провайдера `local`), ADR-009 (стрим провайдера), ADR-014 (`search.py` как декларация модуля), SYS-01 (владельцы точек), SYS-04 (публичные топики), SYS-05 (реестры неизменяемы после старта), SYS-07 (реестр языков), SYS-10 (тесты точек расширения), SYS-13 (реализация плагинов, этап 7); OQ-27 |

## 1. Цель и область действия

- **Цель**: заложить в каркас платформы точки расширения — типизированные интерфейсы и реестры, через которые на этапе 7 плагины добавят языки, провайдеров LLM и речи, типы заданий, экзамены и элементы интерфейса, — так, чтобы к этапу 7 ни один модуль не пришлось переписывать. Спецификация описывает **только интерфейсы и правила их регистрации**; реализация плагинов (манифест в деталях, песочница, права, каталог) — SYS-13.
- **Область действия**: backend (shared kernel `app/core/extensions`, поле `extension_points` в `ModuleDefinition`, публичные API модулей-владельцев), frontend (app_shell `src/lib/extension-points`, компонент `<ExtensionSlot>`), контракты (публичные топики Kafka в `topics.py`), тесты (архитектурные тесты регистрации и типизации), CI. Локальный агент — не затрагивается (он реализация провайдера, а не точка расширения).
- **Действует с этапа**: 1 — для реестра точек расширения, UI-слотов app_shell и точки `llm_gateway.providers`; точки модулей `languages`, `speech`, `lessons`, `assessment` объявляются на этапе появления модуля по контрактам отсюда (раздел 3, R15).
- **Уточняет**: CLAUDE.md «Ключевые архитектурные требования → Расширяемость» («закладывать точки расширения в каркас, даже если сами плагины будут на этапе 7»); SDD_plan.md этап 1 Б.9 и этап 7 п. 1 (SYS-13); ADR-002, раздел 3.2 (`ModuleDefinition`); решает OQ-27 в части этапа 1.

## 2. Термины

| Термин | Определение или ссылка |
|---|---|
| Плагин (`plugin`) | [глоссарий](../../glossary.md), раздел 10 |
| Точка расширения (`extension_point`) | [глоссарий](../../glossary.md), раздел 10 |
| UI-слот (`ui_slot`) | [глоссарий](../../glossary.md), раздел 10 |
| Манифест плагина (`plugin_manifest`) | [глоссарий](../../glossary.md), раздел 10 |
| Реестр языков (`language_registry`) | [глоссарий](../../glossary.md), раздел 4 |
| Провайдер LLM (`llm_provider`), Провайдер речи (`speech_provider`) | [глоссарий](../../glossary.md), раздел 5 |
| Экзамен (`exam`) | [глоссарий](../../glossary.md), раздел 2 |
| Владелец точки расширения | Модуль, в чьём публичном API объявлен контракт точки и чей `ModuleDefinition` её регистрирует. Имя точки начинается с имени владельца: `llm_gateway.providers` |
| Вклад (`contribution`) | Конкретная реализация контракта точки, зарегистрированная в реестре: провайдер `openai_compatible` в точке `llm_gateway.providers`, кнопка в слоте `lesson.toolbar`. На этапах 1–6 вклады вносят только модули монолита, с этапа 7 — также плагины |
| Реестр точки (`ExtensionRegistry[T]`) | Типизированная коллекция вкладов одной точки: неизменяема после старта процесса, доступна по имени точки через контейнер shared kernel |
| Контракт точки | `typing.Protocol` (backend) или TypeScript-интерфейс (frontend) с семантической версией; вклад обязан ему соответствовать |
| Публичный топик | Топик Kafka, объявленный модулем с `visibility = "public"`: на него могут подписываться консьюмеры других модулей (SYS-04-R21), а с этапа 7 его события разрешено доставлять плагинам. Остальные топики — внутренние: их читает только сам модуль |

## 3. Требования

### SYS-09-R1 Единый механизм объявления точки расширения

- **Формулировка**: каждая точка расширения backend должна объявляться объектом `ExtensionPoint[T]` из shared kernel (`app/core/extensions/point.py`) с полями `name` (строка `<module>.<point>`), `version` (semver `MAJOR.MINOR.PATCH`), `contract` (класс `typing.Protocol` с декоратором `@runtime_checkable` или модель Pydantic для декларативных вкладов), `cardinality` (`many` — несколько вкладов, `single` — ровно один), `stage` (номер этапа, с которого точка действует) и регистрироваться в поле `extension_points: tuple[ExtensionPoint, ...]` объекта `ModuleDefinition` модуля-владельца (ADR-002, раздел 3.2 — поле добавляется этой спецификацией); объявление точки вне `ModuleDefinition` или вне подпакета `public` владельца запрещено.
- **Обоснование**: CLAUDE.md «Расширяемость»; без единого способа объявления точки расширения расползутся по модулям в виде словарей и `if provider == ...`; `ModuleDefinition` — единственное место, которое shared kernel читает о модуле (ADR-002), поэтому полный перечень точек известен без сканирования кода.
- **Проверка**: архитектурный тест `tests/architecture/test_extension_points_registered.py` (`<будет создан>`, этап 1 Г.2): все экземпляры `ExtensionPoint` в дереве `app/modules` (AST-поиск) входят в `extension_points` какого-либо `ModuleDefinition`; имя начинается с `<name>.` своего модуля; версия соответствует semver; `contract` — `Protocol` с `@runtime_checkable` или подкласс `BaseModel`; точка объявлена в `app/modules/<module>/public/extension_points.py`.
- **Применимость**: backend, tests.

### SYS-09-R2 Вклады регистрируются декларативно и только через контракт

- **Формулировка**: вклад должен регистрироваться объектом `ExtensionContribution` (`point: str`, `point_version: str` — требование совместимости вида `^1.0`, `id: str` — уникален в точке, формат `[a-z][a-z0-9_]*`, `provider: Callable[[], T]` — фабрика экземпляра, `order: int = 100`) в поле `contributions: tuple[ExtensionContribution, ...]` `ModuleDefinition` вносящего модуля; shared kernel при старте (`load_modules`) должен проверить, что точка существует, версия совместима, экземпляр фабрики проходит `isinstance(obj, point.contract)` (для `Protocol`) или валидацию модели, идентификатор уникален, а при `cardinality = "single"` вклад ровно один; нарушение должно останавливать старт процесса.
- **Обоснование**: регистрация при старте делает реестр неизменяемым в процессе (SYS-05: состояние в памяти допустимо только для неизменяемой конфигурации, одинаковой на всех инстансах) и даёт одинаковый набор вкладов на N инстансах; fail-fast вместо ошибки при первом вызове провайдера.
- **Проверка**: unit-тесты shared kernel `tests/core/extensions/test_registry.py` (`<будет создан>`): несовместимая версия, дубликат `id`, объект без метода контракта, два вклада в `single` — каждый случай даёт `ExtensionRegistrationError` при `load_modules`; архитектурный тест R1 дополнительно проверяет, что `ExtensionContribution` объявлены только в `module.py`.
- **Применимость**: backend, tests.

### SYS-09-R3 Доступ к реестру — через контейнер shared kernel, без прямого импорта реализаций

- **Формулировка**: модуль должен получать вклады точки через `registry(point_name)` контейнера зависимостей shared kernel (ADR-004, 2.6: `container.resolve(ExtensionRegistry, name="llm_gateway.providers")` или `Depends(provide_registry("llm_gateway.providers"))`), работать с ними только через контракт точки и не должен импортировать классы реализаций из чужих модулей; в тестах реестр подменяется `container.override`.
- **Обоснование**: CLAUDE.md «Модульный монолит»: другие модули импортируют только публичный API; контракт import-linter `modules-public-api-only` (ADR-002) не пропустит импорт `app.modules.llm_gateway.providers.openai_compatible` из `lessons`, а реестр делает такой импорт ненужным.
- **Проверка**: import-linter (ADR-002, контракт 1); тест `tests/architecture/test_extension_points_registered.py`: в `app/modules/<m>/**` нет импортов `app.modules.<other>.*` кроме `public`; unit-тест контейнера на `override` реестра.
- **Применимость**: backend.

### SYS-09-R4 Семантическое версионирование контрактов и порядок устаревания

- **Формулировка**: изменение контракта точки должно менять её `version` по правилам semver: добавление необязательного метода или поля — `MINOR`; изменение сигнатуры, удаление метода, изменение семантики — `MAJOR`; при `MAJOR` старая версия контракта должна сохраняться под именем `<Contract>V<N>` минимум один этап разработки (SDD_plan.md) с пометкой `@deprecated` и записью в разделе «Публичный API» спецификации модуля, а реестр должен принимать вклады обеих версий через адаптер владельца; удаление старой версии — отдельным ТЗ модуля-владельца с перечнем затронутых вкладов.
- **Обоснование**: плагины (этап 7) собираются вне репозитория и объявляют совместимость в манифесте (R13); без версий изменение контракта молча ломает установленные плагины; один этап — срок, за который SYS-13 успевает уведомить авторов плагинов.
- **Проверка**: тест `tests/architecture/test_extension_point_versions.py` (`<будет создан>`): снимок `name → (version, публичные методы контракта)` хранится в `tests/architecture/snapshots/extension_points.json`; изменение методов без изменения версии ломает тест; понижение версии запрещено. Спецификация модуля (раздел 3 «Публичный API») перечисляет точки с версиями — проверка на ревью G1.
- **Применимость**: backend, tests.

### SYS-09-R5 Реестр UI-слотов app_shell

- **Формулировка**: frontend должен предоставлять в `src/lib/extension-points/` реестр UI-слотов: файл `slots.ts` с перечнем идентификаторов `SLOT_IDS` и типом контекста каждого слота, функцию `registerSlotContribution(slotId, contribution)` (вызывается только из `src/app/extensions.ts` при инициализации приложения; на этапе 1 файл содержит пустой массив), компонент `<ExtensionSlot id context fallback>` (рендерит вклады по возрастанию `order`, у каждого вклада — `id`, `order`, `when?(context): boolean`, `component: React.ComponentType<SlotProps<Id>>`, `labelKey` — ключ i18n по SYS-07), и запрещать прямой импорт между модулями для встраивания компонентов; идентификаторы слотов — строки `<area>.<place>[.<kind>]` на английском.
- **Обоснование**: CLAUDE.md «Модульный монолит → Frontend»: модули не импортируют друг друга и связываются только в `src/app`; слот — единственный способ, которым модуль `dictionary` добавит кнопку на экран `lessons`, не импортируя его; тот же механизм используют плагины на этапе 7 (module federation или iframe — SYS-13), поэтому контракт вклада не должен зависеть от способа загрузки кода.
- **Проверка**: архитектурный тест `src/testing/architecture/extension-slots.test.ts` (`<будет создан>`): все `<ExtensionSlot id="...">` в `src/**` используют значения из `SLOT_IDS`; `registerSlotContribution` вызывается только в `src/app/extensions.ts`; ESLint `import-x/no-restricted-paths` (ADR-005) запрещает импорт `src/features/<a>` из `src/features/<b>`; компонентный тест `src/lib/extension-points/extension-slot.test.tsx`: порядок по `order`, фильтр `when`, `fallback` при отсутствии вкладов.
- **Применимость**: frontend, tests.

### SYS-09-R6 Стартовый перечень UI-слотов и правило добавления

- **Формулировка**: на этапе 1 `SLOT_IDS` должен содержать слоты `app.header.actions` (контекст `{ user: User | null }`), `app.nav.items` (`{ user: User | null }`), `app.user_menu.items` (`{ user: User }`), `settings.sections` (`{ user: User }`); на этапах 2–5 модули-владельцы добавляют `profile.tabs` (`{ profileUserId: string }`, `learner_profile`), `lesson.toolbar` (`{ lessonId: string; learningLanguage: LanguageCode }`, `lessons`), `lesson.sidebar.panels` (тот же контекст, `lessons`), `lesson.exercise.renderers` (`{ exerciseType: string }`, `lessons` — R10), `dictionary.entry.actions` (`{ entryId: string; language: LanguageCode }`, `dictionary`), `dashboard.widgets` (`{ user: User }`, app_shell); новый слот должен добавляться только через ТЗ модуля-владельца экрана с записью в `slots.ts`, в разделе «UI» ТЗ и в разделе «Публичный API» спецификации модуля (frontend-часть); удаление или переименование слота — по правилу R4 (объявление `deprecated` на один этап).
- **Обоснование**: ограниченный перечень не даёт превратить слоты в способ обойти границы модулей; слоты app_shell нужны с этапа 1 (переключатель языка SYS-07 R5 — первый вклад в `app.header.actions`); слоты уроков, словаря и профиля — типовые места расширения из BRD (STU-25 инструменты и скилы в занятии, STU-30 вайбкодинг плагинов).
- **Проверка**: тест `src/testing/architecture/extension-slots.test.ts`: множество `SLOT_IDS` на этапе 1 равно перечню выше; снимок типов контекста в `src/lib/extension-points/__snapshots__/slots.json`; ревью G1 ТЗ, добавляющего слот.
- **Применимость**: frontend, tests.

### SYS-09-R7 Точка `llm_gateway.providers`

- **Формулировка**: модуль `llm_gateway` должен объявить точку `llm_gateway.providers` версии `1.0.0` с контрактом `ProviderKindInfo` из SYS-08-R4 (вид провайдера: `kind`, `factory`, `jurisdiction`, `auth_mode`, `display_name_key`, `default_base_url`, `stage`), где `factory` создаёт на одно подключение адаптер `LLMProvider` из SYS-08-R2 (`@runtime_checkable` `Protocol`: свойство `kind`, методы `complete`, `stream_completion` — async-генератор `Delta` по ADR-009, `list_models`, `capabilities(llm_model) -> ModelCapabilities`, `check_connection`, `count_tokens`; точные сигнатуры — SYS-08-R2), `cardinality = "many"`; на этапе 1 вклады — `stub` (детерминированная заглушка record/replay для тестов) и `openai_compatible`; провайдер `local` (ADR-008) регистрируется модулем `local_runtime` на этапе 4 как вклад в ту же точку; точка `llm_gateway.embeddings_providers` (контракт `EmbeddingsProvider`, ADR-014, SYS-08-R21: реализации эмбеддингов платформенные и не создаются на подключение ученика) объявляется тогда же версии `1.0.0` с вкладом `stub` на этапе 1 и `platform` на этапе 5 (OQ-59).
- **Обоснование**: CLAUDE.md «LLM-агностичность»; глоссарий «Провайдер LLM»: «реестр провайдеров — точка расширения для плагинов»; SDD_plan.md этап 1 Г.6; критерий выхода этапа 7 — «плагин добавляет LLM-провайдера».
- **Проверка**: тест модуля `tests/modules/llm_gateway/unit/test_provider_registry.py` (`<будет создан>`, этап 1 Г.6): реестр содержит виды `stub` и `openai_compatible`, адаптеры, созданные их фабриками для тестового подключения, проходят `isinstance(..., LLMProvider)`; негативный тест: вклад, фабрика которого возвращает объект без `stream_completion`, не регистрируется; выбор вида по `kind` подключения ученика (`llm_gateway.provider_bindings`, SYS-08-R6) идёт через реестр, а не через `if`.
- **Применимость**: backend, tests.

### SYS-09-R8 Точка `languages.registry`

- **Формулировка**: модуль `languages` (этап 4) должен объявить точку `languages.registry` версии `1.0.0` с декларативным контрактом — Pydantic-моделью `LanguageDefinition` с полями из SYS-07 R24 (`code`, `name_native`, `script`, `direction`, `search_analyzer`, `transliteration_schemes`, `is_learning_language`, `is_ui_language`) и необязательным полем `transliterator: Callable[[str], str] | None` (реализация схемы транслитерации — вклад в отдельную точку `languages.transliterators`, контракт `Transliterator` `Protocol`: `scheme_id`, `language_code`, `transliterate(text) -> str`, `reverse(text) -> str | None`), `cardinality = "many"`; встроенные языки платформы регистрируются как вклады модуля `languages` из статической таблицы (YAML `app/modules/languages/data/languages.yaml`), а не как особый путь; добавление языка плагином на этапе 7 — вклад в ту же точку.
- **Обоснование**: STU-08–STU-11; глоссарий «Реестр языков — точка расширения для плагинов, добавляющих языки»; единый путь для встроенных и плагинных языков гарантирует, что плагин получает те же проверки.
- **Проверка**: тест модуля `languages` (этап 4): реестр строится только из вкладов; язык с некорректным `code` (SYS-07 R25) отклоняется при старте; для языка с `is_learning_language` и непустым `transliteration_schemes` существует вклад `languages.transliterators` на каждую схему.
- **Применимость**: backend, tests.

### SYS-09-R9 Точки провайдеров речи

- **Формулировка**: модуль `speech` (этап 5) должен объявить точки `speech.stt_providers` и `speech.tts_providers` версии `1.0.0` с контрактом `SpeechProviderKindInfo` из SYS-08-R22, `factory` которого создаёт адаптеры `STTProvider` и `TTSProvider` (потоковые интерфейсы ADR-009: `stream_transcribe(frames, *, language, sample_rate) -> AsyncIterator[Transcript]`, `stream_synthesize(text, *, voice, language, sample_rate) -> AsyncIterator[AudioFrame]`, `list_voices(language=None) -> list[Voice]`, `capabilities() -> SpeechCapabilities`, `check_connection() -> ConnectionCheck`; точные сигнатуры — SYS-08-R22), `cardinality = "many"`; вклады `stub` обязательны с момента появления модуля; провайдер через локальный агент — вклад `local` модуля `local_runtime`.
- **Обоснование**: CLAUDE.md «Синтез и распознавание речи: через провайдеров по аналогии с LLM»; STU-13, STU-28, STU-34.2.
- **Проверка**: тест модуля `speech` (этап 5) по образцу R7; архитектурный тест R1 (имя `speech.*`, объявление в `public/extension_points.py`).
- **Применимость**: backend, tests.

### SYS-09-R10 Точка типов заданий `lessons.exercise_types`

- **Формулировка**: модуль `lessons` (этап 2) должен объявить точку `lessons.exercise_types` версии `1.0.0` с контрактом `ExerciseType` (`Protocol`: `id` — `[a-z][a-z0-9_]*`, `payload_schema: type[BaseModel]` — схема задания, `answer_schema: type[BaseModel]` — схема ответа ученика, `grade(payload, answer, context) -> GradeResult` — проверка, в том числе через LLM по SYS-08, `render_hint_key: str` — ключ i18n описания), `cardinality = "many"`; frontend-рендерер типа задания — вклад в слот `lesson.exercise.renderers` (R6) с `when: ctx => ctx.exerciseType === '<id>'`; тип задания, у которого нет рендерера, должен отображаться запасным компонентом `UnsupportedExercise` с ключом `lessons:exercise.unsupported`; на этапе 2 обязателен хотя бы один тип (`free_text_dialogue` — демо-урок VIS-03/STU-20), остальные — по ТЗ STU-20–STU-22.
- **Обоснование**: STU-20–STU-23, STU-25, STU-30: тренинги и упражнения — основное, что добавляют плагины; разделение `payload_schema`/`answer_schema` даёт валидацию контента плагина без выполнения его кода (SYS-13).
- **Проверка**: тест модуля `lessons` (этап 2): реестр не пуст, у каждого типа схемы валидируются, `grade` заглушки детерминирован; frontend-тест `src/testing/architecture/extension-slots.test.ts`: для каждого `id` из контракта OpenAPI `lessons` (перечисление типов) есть вклад в `lesson.exercise.renderers` или тест явно ожидает `UnsupportedExercise`.
- **Применимость**: backend, frontend, tests.

### SYS-09-R11 Точка экзаменов `assessment.exams`

- **Формулировка**: модуль `assessment` (этап 5, STU-23) должен объявить точку `assessment.exams` версии `1.0.0` с декларативным контрактом `ExamDefinition` (Pydantic: `id`, `title_key`, `language_code`, `sections: list[ExamSection]` — `id`, `title_key`, `duration_minutes`, `exercise_type` из R10, `item_count`; `scoring: ScoringScale` — шкала и правила перевода в CEFR; `version`), `cardinality = "many"`; встроенные экзамены (TOEFL, IELTS) должны загружаться из файлов `app/modules/assessment/data/exams/<id>.yaml` и регистрироваться вкладами; экзамен должен ссылаться только на зарегистрированные типы заданий.
- **Обоснование**: SDD_plan.md этап 5 п. 11: «экзамен описывается конфигурацией… новые экзамены добавляются без изменения кода»; глоссарий «Экзамен».
- **Проверка**: тест модуля `assessment` (этап 5): загрузка YAML, валидация модели, ссылка на несуществующий `exercise_type` ломает старт; JSON Schema `ExamDefinition` публикуется в `Analytics/Specs/assessment/api/exam-definition.schema.json` и проверяется в job `contracts` (ADR-011).
- **Применимость**: backend, tests.

### SYS-09-R12 События Kafka как точка расширения: публичные топики

- **Формулировка**: декларация топика модуля (`TopicDeclaration` в `public/topics.py`, ADR-004 и SYS-04) должна содержать поле `visibility: Literal["internal", "public"]` со значением `internal` по умолчанию (`internal` — только консьюмеры самого модуля, `public` — консьюмеры других модулей и плагины, SYS-04-R21); событие, помеченное `public`, должно иметь схему payload без персональных данных сверх идентификаторов (SYS-02) и записываться в раздел «События» спецификации модуля с пометкой «публичное»; плагины (этап 7) получают события только публичных топиков через механизм доставки SYS-13 и никогда не подключаются к Kafka напрямую; смена `public` → `internal` — по правилу устаревания R4.
- **Обоснование**: CLAUDE.md «Взаимодействие»: Kafka наружу не публикуется, модуль публикует только свои события; плагинам нужна реакция на факты (`lessons.lesson_completed`, `progress.level_changed`), но не доступ к брокеру и не все события.
- **Проверка**: тест SYS-04 на декларации топиков дополняется проверкой поля `visibility`; тест `tests/architecture/test_public_topics_have_no_pii.py` (`<будет создан>`): payload-схемы публичных топиков не содержат полей из списка запрещённых имён (`email`, `phone`, `display_name`, `content`, `text`, `transcript`, `audio`); перечень публичных топиков генерируется в `Analytics/traceability.md` (SYS-12).
- **Применимость**: backend, tests.

### SYS-09-R13 Манифест плагина: схема версии 1 (только поля)

- **Формулировка**: формат манифеста плагина `plugin.yaml` должен иметь поле `manifest_version: 1` и следующие поля версии 1: `id` (обратное доменное имя `[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+`, например `com.example.hebrew_pack`), `version` (semver), `name` и `description` (объекты по языкам интерфейса SYS-07 R2, `ru` обязателен), `author` (`name`, `contact`), `license` (SPDX-идентификатор), `platform` (`min_version`, `max_version` — версия платформы, теги `stage-N` ADR-011), `contributes` (объект: ключ — имя точки расширения с версией `llm_gateway.providers@^1.0`, значение — список вкладов с `id` и путём к точке входа), `permissions` (список идентификаторов прав плагина — перечень задаёт SYS-13), `subscribes` (список публичных топиков R12), `ui` (список слотов R6 и путь к бандлу); JSON Schema манифеста (`Analytics/Specs/plugins/api/plugin-manifest-v1.schema.json`) и валидатор создаются в SYS-13 (этап 7); изменение набора полей версии 1 после утверждения SYS-13 запрещено — только `manifest_version: 2`.
- **Обоснование**: OQ-27: SYS-09 закрепляет контракт, SYS-13 — реализацию; фиксированный перечень полей позволяет уже сейчас проектировать точки так, чтобы вклад описывался декларативно (`id` и точка входа), а не кодом регистрации.
- **Проверка**: на этапе 1 — только ревью (схема и валидатор появятся в SYS-13; автоматическая проверка невозможна до появления кода плагинов); SYS-13 обязан добавить тест валидатора на пример из раздела 5 этой спецификации.
- **Применимость**: backend (этап 7).

### SYS-09-R14 Границы безопасности точек расширения

- **Формулировка**: контракты точек расширения не должны принимать и возвращать объекты доступа к инфраструктуре — сессии SQLAlchemy, клиенты Redis, брокер Kafka, `FileStorage`, настройки с секретами, объекты запроса FastAPI; вклад получает только данные (Pydantic-модели, примитивы) и явно переданные сервисы из публичных API модулей (`Protocol`), а всё, что вклад возвращает, должно валидироваться владельцем точки до использования; реестр не должен позволять вкладу переопределить или удалить чужой вклад; для вкладов плагинов (этап 7) дополнительно действует изоляция SYS-13.
- **Обоснование**: CLAUDE.md «Разграничение ролей: права проверять на сервере», «API-ключи учеников… в зашифрованном виде»; если контракт точки принимает сессию БД, плагин получает всю базу; ограничение контракта на этапе 1 дешевле переписывания точек на этапе 7.
- **Проверка**: архитектурный тест `tests/architecture/test_extension_contracts_are_data_only.py` (`<будет создан>`): аннотации методов всех контрактов точек не содержат типов из запрещённого списка (`AsyncSession`, `Redis`, `ModuleRedis`, `KafkaBroker`, `OutboxPublisher`, `FileStorage`, `Request`, `WebSocket`, `BaseSettings`, `SecretStr`) и их подклассов; unit-тест реестра: повторная регистрация `id` — ошибка.
- **Применимость**: backend, tests.

### SYS-09-R15 Что делается на этапе 1 и что позже

- **Формулировка**: на этапе 1 должны быть реализованы: пакет `app/core/extensions` (`ExtensionPoint`, `ExtensionContribution`, `ExtensionRegistry`, регистрация в `load_modules`, доступ через контейнер), поля `extension_points` и `contributions` в `ModuleDefinition`, точки `llm_gateway.providers` и `llm_gateway.embeddings_providers` с вкладами `stub` и `openai_compatible`, пакет `src/lib/extension-points` с четырьмя слотами app_shell из R6 и пустым `src/app/extensions.ts`, поле `visibility` в декларации топиков, архитектурные тесты R1, R4, R5, R6, R14; на этапах появления модулей — точки R8–R11 по контрактам отсюда; на этапе 7 (SYS-13) — загрузчик плагинов, песочница, права, валидатор манифеста, доставка публичных событий, загрузка UI-бандлов в слоты; модули этапов 2–6 не должны вводить собственных механизмов расширения (словари провайдеров, `if`-цепочки по типу, захардкоженные списки языков) вместо точек этой спецификации.
- **Обоснование**: SDD_plan.md этап 1 Б.9: «только интерфейсы, без реализации плагинов»; реестры с единственным встроенным вкладом на этапе 1 стоят дёшево и исключают переделку модулей на этапе 7.
- **Проверка**: критерий выхода этапа 1 (SDD_plan.md) дополняется проверкой «архитектурные тесты SYS-09 зелёные»; на ревью разбиения в конце каждого этапа (SDD_plan.md, раздел 8) — поиск `isinstance`/`match` по типу провайдера или языка вне владельца точки (grep-тест `tests/architecture/test_no_adhoc_registries.py`, `<будет создан>`: в `app/modules/**` нет словарей с ключами-идентификаторами провайдеров и языков вне `module.py` и `data/`).
- **Применимость**: backend, frontend, tests, CI.

### SYS-09-R16 Документирование точек в спецификациях модулей

- **Формулировка**: спецификация модуля-владельца (`_module.md`, раздел 3 «Публичный API») должна содержать таблицу точек расширения модуля: имя, версия, контракт (ссылка на файл `public/extension_points.py` или `slots.ts`), `cardinality`, стартовые вклады, этап; спецификация модуля, вносящего вклад в чужую точку, должна перечислять эти вклады в разделе «Зависимости»; матрица трассировки (SYS-12) должна содержать раздел «Точки расширения» со сводной таблицей по всем модулям, генерируемой `flt-tools traceability` из `ModuleDefinition` и `slots.ts`.
- **Обоснование**: SYS-13 и авторы плагинов должны видеть полный перечень точек и версий без чтения кода; генерация из кода исключает расхождение.
- **Проверка**: job `docs` CI (ADR-011): `flt-tools traceability check` сверяет раздел «Точки расширения» `Analytics/traceability.md` с кодом; ревью G1 спецификаций модулей.
- **Применимость**: backend, frontend, CI.

## 4. Влияние на модули и на шаблон ТЗ

### 4.1. Модули

| Модуль | Что меняется |
|---|---|
| shared kernel (`app/core/extensions`, `app/core/modules.py`) | `ExtensionPoint`, `ExtensionContribution`, `ExtensionRegistry`, проверка при `load_modules`, доступ через контейнер; поля `extension_points`, `contributions` в `ModuleDefinition`; поле `visibility` в декларации топика (вместе с SYS-04) |
| app_shell (`src/lib/extension-points`, `src/app/extensions.ts`) | `slots.ts` с четырьмя слотами, `registerSlotContribution`, `<ExtensionSlot>`, снимок типов контекста; первый вклад — переключатель языка в `app.header.actions` (SYS-07) |
| llm_gateway (этап 1) | точки `llm_gateway.providers`, `llm_gateway.embeddings_providers`; вклады `stub`, `openai_compatible`; выбор провайдера только через реестр |
| local_runtime (этап 4) | вклады `local` в `llm_gateway.providers`, позже в `speech.*` |
| languages (этап 4) | точки `languages.registry`, `languages.transliterators`; встроенные языки — вклады из `data/languages.yaml` |
| lessons (этап 2) | точка `lessons.exercise_types`, вклад `free_text_dialogue`; слоты `lesson.toolbar`, `lesson.sidebar.panels`, `lesson.exercise.renderers` на frontend |
| speech (этап 5) | точки `speech.stt_providers`, `speech.tts_providers`, вклады `stub` |
| assessment (этап 5) | точка `assessment.exams`, встроенные TOEFL и IELTS из YAML, JSON Schema `ExamDefinition` |
| learner_profile, dictionary (этап 4) | слоты `profile.tabs`, `dictionary.entry.actions` |
| все модули | `visibility` у топиков; запрет собственных механизмов расширения (R15); таблица точек в `_module.md` (R16) |
| plugins (этап 7, SYS-13) | загрузчик, песочница, манифест v1, доставка публичных событий, UI-бандлы в слоты |

### 4.2. Шаблон ТЗ

| Раздел шаблона ТЗ | Что добавить или проверять |
|---|---|
| Роли и пользовательские сценарии | указать, вводит ли фича новый тип сущности, которую позже сможет добавить плагин (язык, провайдер, тип задания, экзамен); если да — через какую точку |
| Контракты | публичные топики помечаются «публичное» и проверяются на отсутствие персональных данных (R12); схемы `payload_schema`/`answer_schema` типов заданий — в OpenAPI модуля |
| Модель данных | декларативные вклады (экзамены, языки) хранятся в файлах `data/` модуля, не в коде |
| UI | новые UI-слоты и вклады в существующие слоты перечисляются с идентификатором и контекстом; прямой импорт компонентов другого модуля запрещён |
| Вне рамок | явно указывается, что реализация плагинами — SYS-13 |

Шаблон спецификации модуля (`module-spec.md`), раздел 3 «Публичный API», получает подраздел «Точки расширения» (R16).

## 5. Примеры

### Пример 1. Объявление точки и вклада на backend (SYS-09-R1, SYS-09-R2, SYS-09-R7)

```python
# app/core/extensions/point.py
@dataclass(frozen=True)
class ExtensionPoint[T]:
    """Точка расширения: имя <module>.<point>, semver контракта, Protocol или модель вкладов."""

    name: str
    version: str
    contract: type[T]
    cardinality: Literal["many", "single"] = "many"
    stage: int = 1


@dataclass(frozen=True)
class ExtensionContribution:
    """Вклад модуля в точку расширения; регистрируется в ModuleDefinition.contributions."""

    point: str
    point_version: str          # требование совместимости, например "^1.0"
    id: str
    provider: Callable[[], object]
    order: int = 100
```

```python
# app/modules/llm_gateway/public/extension_points.py
from app.core.extensions import ExtensionPoint
from app.modules.llm_gateway.public.providers import EmbeddingsProvider, ProviderKindInfo

LLM_PROVIDERS = ExtensionPoint[ProviderKindInfo](name="llm_gateway.providers", version="1.0.0", contract=ProviderKindInfo)
EMBEDDINGS_PROVIDERS = ExtensionPoint[EmbeddingsProvider](
    name="llm_gateway.embeddings_providers", version="1.0.0", contract=EmbeddingsProvider
)
```

```python
# app/modules/llm_gateway/public/providers.py (фрагмент; полные сигнатуры — SYS-08-R2, R4)
@runtime_checkable
class LLMProvider(Protocol):
    """Адаптер провайдера LLM на одно подключение; создаётся фабрикой вклада llm_gateway.providers v1."""

    @property
    def kind(self) -> str: ...
    async def complete(self, request: CompletionRequest) -> CompletionResult: ...
    def stream_completion(self, request: CompletionRequest) -> AsyncIterator[Delta]: ...
    async def list_models(self) -> list[ModelInfo]: ...
    async def capabilities(self, llm_model: str) -> ModelCapabilities: ...
    async def check_connection(self) -> ConnectionCheck: ...
    def count_tokens(self, request: CompletionRequest) -> int | None: ...


@dataclass(frozen=True)
class ProviderKindInfo:
    """Вклад в точку llm_gateway.providers: вид провайдера и фабрика адаптера."""

    kind: str
    factory: Callable[[ProviderBindingConfig, ProviderCredentials | None], LLMProvider]
    jurisdiction: Jurisdiction
    auth_mode: Literal["api_key", "agent", "none"]
    display_name_key: str
    default_base_url: str | None
    stage: int
```

```python
# app/modules/llm_gateway/module.py
module = ModuleDefinition(
    name="llm_gateway",
    metadata=Base.metadata,
    router=router,
    extension_points=(LLM_PROVIDERS, EMBEDDINGS_PROVIDERS),
    contributions=(
        ExtensionContribution(point="llm_gateway.providers", point_version="^1.0", id="stub", provider=StubProvider),
        ExtensionContribution(point="llm_gateway.providers", point_version="^1.0", id="openai_compatible", provider=OpenAICompatibleProvider),
        ExtensionContribution(point="llm_gateway.embeddings_providers", point_version="^1.0", id="stub", provider=StubEmbeddings),
    ),
)
```

```python
# app/modules/local_runtime/module.py (этап 4) — вклад в чужую точку без импорта реализаций llm_gateway
from app.modules.llm_gateway.public import LLM_PROVIDERS  # только public

module = ModuleDefinition(
    name="local_runtime",
    ...,
    contributions=(ExtensionContribution(point=LLM_PROVIDERS.name, point_version="^1.0", id="local", provider=LOCAL_PROVIDER_KIND),),  # ProviderKindInfo(kind="local", factory=LocalAgentProvider, …)
)
```

Использование в сервисе `llm_gateway` (другие модули вызывают только `LlmGatewayService`, SYS-08-R1):

```python
kinds = registry.resolve(ProviderKindInfo, point="llm_gateway.providers")   # ExtensionRegistry[ProviderKindInfo]
adapter = kinds.get(binding.kind).factory(binding_config, credentials)       # KeyError → 422 core.validation_failed (SYS-08-R4)
```

Неправильно: `from app.modules.llm_gateway.providers.openai_compatible import OpenAICompatibleProvider` в `lessons` (нарушает R3 и ADR-002); `PROVIDERS = {"openai": ..., "local": ...}` словарём в `lessons` (нарушает R15).

### Пример 2. UI-слот app_shell и вклад модуля (SYS-09-R5, SYS-09-R6)

```ts
// src/lib/extension-points/slots.ts
export const SLOT_IDS = ['app.header.actions', 'app.nav.items', 'app.user_menu.items', 'settings.sections'] as const;
export type SlotId = (typeof SLOT_IDS)[number];

export interface SlotContexts {
  'app.header.actions': { user: User | null };
  'app.nav.items': { user: User | null };
  'app.user_menu.items': { user: User };
  'settings.sections': { user: User };
}

export interface SlotContribution<Id extends SlotId> {
  id: string;                       // уникален в слоте: '<module>.<name>'
  order: number;                    // по возрастанию
  labelKey: string;                 // ключ i18n (SYS-07), например 'common:header.language'
  when?: (ctx: SlotContexts[Id]) => boolean;
  component: React.ComponentType<{ context: SlotContexts[Id] }>;
}
```

```tsx
// src/lib/extension-points/extension-slot.tsx
export function ExtensionSlot<Id extends SlotId>({ id, context, fallback = null }: Props<Id>) {
  const items = useSlotContributions(id).filter((c) => c.when?.(context) ?? true);
  if (items.length === 0) return fallback;
  return <>{items.map((c) => <c.component key={c.id} context={context} />)}</>;
}
```

```ts
// src/app/extensions.ts — единственное место регистрации вкладов (на этапе 1 — вклады app_shell)
import { registerSlotContribution } from '@/lib/extension-points/registry';
import { LanguageSwitcher } from '@/components/layouts/language-switcher';

registerSlotContribution('app.header.actions', {
  id: 'app_shell.language_switcher',
  order: 10,
  labelKey: 'common:header.language',
  component: LanguageSwitcher,
});
```

```tsx
// src/components/layouts/header.tsx
<ExtensionSlot id="app.header.actions" context={{ user }} />
```

Неправильно: `import { DictionaryQuickLookup } from '@/features/dictionary/...'` внутри `src/features/lessons` — нарушение зоны ESLint; вместо этого `dictionary` вносит вклад в `lesson.toolbar` через `src/app/extensions.ts`.

### Пример 3. Манифест плагина версии 1 (SYS-09-R13)

```yaml
manifest_version: 1
id: com.example.hebrew_pack
version: 1.2.0
name:
  ru: "Иврит: язык и транслитерация"
  en: "Hebrew language pack"
  ar: "حزمة اللغة العبرية"
description:
  ru: "Добавляет иврит как изучаемый язык и схему транслитерации."
author:
  name: "Example Org"
  contact: "plugins@example.com"
license: MIT
platform:
  min_version: "stage-7"
  max_version: "stage-9"
contributes:
  "languages.registry@^1.0":
    - id: he
      entry: languages/he.yaml
  "languages.transliterators@^1.0":
    - id: he_sbl
      entry: transliterators/he_sbl.py:SblTransliterator
  "lesson.toolbar@^1.0":
    - id: hebrew_pack.niqqud_toggle
      entry: ui/niqqud-toggle.js
permissions:
  - lessons:lessons:read        # формат кода права — SYS-06-R2
subscribes:
  - flt.lessons.lesson_completed.v1
ui:
  bundle: ui/bundle.js
  slots: [lesson.toolbar]
```

Поля `permissions` и способ выполнения `entry` определяет SYS-13; здесь зафиксированы только имена и форма полей.

### Пример 4. Публичный топик (SYS-09-R12)

```python
# app/modules/lessons/public/topics.py
LESSON_COMPLETED = TopicDeclaration(
    name="flt.lessons.lesson_completed.v1",
    kind="event",
    visibility="public",
    partitions=6,
    retention=timedelta(days=7),
    message_model=LessonCompleted,       # payload: lesson_id, user_id, learning_language, duration_seconds — без текста диалога
    description="Занятие завершено.",
)
LESSON_MESSAGE_SENT = TopicDeclaration(
    name="flt.lessons.message_sent.v1",
    kind="event",
    visibility="internal",
    partitions=6,
    retention=timedelta(days=7),
    message_model=LessonMessageSent,     # payload содержит text — только internal
    description="Сообщение в занятии отправлено.",
)
```

## 6. Исключения и как их согласовать

Исключения из R3 и R15 для тестов (`tests/**`, `src/testing/**`) действуют без согласования: тесты вправе создавать вклады и реестры напрямую. Любое другое исключение: 1) вопрос в `Analytics/open-questions.md`; 2) решение человека; 3) строка в таблице ниже; 4) allowlist в архитектурном тесте со ссылкой на строку. Исключение без записи — нарушение.

| Требование | Где | Обоснование | Срок действия | Кто согласовал и когда |
|---|---|---|---|---|
| SYS-09-R2, SYS-09-R3 | `tests/**`, `src/testing/**` | Тесты подменяют реестры и вклады | бессрочно | фиксируется при утверждении этой спецификации |

## 7. Вне рамок

- Выполнение кода плагинов, песочница, права, модерация, каталог, установка, вайбкодинг — SYS-13, ТЗ STU-25, STU-30, STU-31, ADM-04 (этап 7).
- Способ загрузки UI-бандлов плагинов (module federation или iframe с `postMessage`) — SYS-13; контракт слота R5 обязан это допускать.
- Полные сигнатуры `LLMProvider`, `ProviderKindInfo`, `EmbeddingsProvider`, `STTProvider`, `TTSProvider`, `ModelCapabilities`, `SpeechCapabilities` — SYS-08.
- MCP-серверы и скилы (STU-25) — не точки расширения платформы, а настройки harness конкретного ученика (SYS-08, OQ-56, OQ-57).
- Расширение Kafka внешними сервисами (вне монолита) — появляется только при выделении микросервисов; здесь — лишь признак `visibility`.
- Точки расширения локального агента (новые движки сверх LM Studio и llama.cpp) — ADR-008 и ТЗ этапов 4–5; агент не исполняет плагины платформы.

## 8. Связанные ADR

| ADR | Связь | Что берётся |
|---|---|---|
| [ADR-002](../../ADR/ADR-002-module-layout.md) | основан на | `ModuleDefinition`, подпакет `public`, контракты import-linter; спецификация добавляет поля `extension_points` и `contributions` и файл `public/extension_points.py` |
| [ADR-004](../../ADR/ADR-004-communication-patterns.md) | основан на | контейнер зависимостей и `Protocol` для вызовов между модулями (R3); декларации топиков `public/topics.py` (R12) |
| [ADR-005](../../ADR/ADR-005-frontend-stack.md) | основан на | зоны ESLint между модулями, запрет barrel-файлов, связывание в `src/app` (R5) |
| [ADR-009](../../ADR/ADR-009-llm-streaming-and-voice.md) | уточняет | `stream_completion` как async-генератор — часть контракта `LLMProvider`; потоковые STT и TTS |
| [ADR-008](../../ADR/ADR-008-local-agent.md) | уточняет | провайдер `local` — вклад модуля `local_runtime` в `llm_gateway.providers` |
| [ADR-014](../../ADR/ADR-014-search-engines.md) | уточняет | `EmbeddingsProvider` как точка `llm_gateway.embeddings_providers`; декларации `search.py` остаются декларациями модуля, не точкой расширения |
| [ADR-013](../../ADR/ADR-013-secrets-management.md) | ограничивает | контракты точек не получают `SecretStr` и настройки (R14) |

## 9. Открытые вопросы

| Вопрос | Суть | Блокирует G1 | Статус |
|---|---|---|---|
| [OQ-27](../../open-questions.md) | Плагинная система: точки расширения и архитектура | нет | planned → SYS-09 решает часть этапа 1 (R1–R16: реестры, слоты, версии, манифест v1 по полям); изоляция и песочница — SYS-13 (этап 7); статус `planned` сохраняется до утверждения SYS-13 |
| [OQ-56](../../open-questions.md), [OQ-57](../../open-questions.md) | Определение скила и состав harness | нет | planned → SYS-08, ТЗ STU-25; на точки расширения не влияют |
| [OQ-59](../../open-questions.md) | Модель эмбеддингов и контейнер `embeddings` | нет | planned → ТЗ STU-27, SYS-08; вклад `platform` в `llm_gateway.embeddings_providers` появится по решению |

## 10. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | draft |
| 0.2 | 2026-10-11 | Claude | Согласование SYS-01…SYS-12: R7 — контракт точки `llm_gateway.providers` — `ProviderKindInfo` с фабрикой адаптера `LLMProvider`, сигнатуры совпадают с SYS-08-R2, R4 (`stream_completion`, `kind`, без параметра подключения); R9 — сигнатуры `STTProvider`/`TTSProvider` по SYS-08-R22; R12 — смысл `visibility` согласован с SYS-04-R21 (`public` — другие модули и плагины); примеры 2 и 4 — `public/providers.py`, вклад `local` и выбор вида в сервисе `llm_gateway` вместо `lessons`, `public/topics.py` и поля `TopicDeclaration` по SYS-04; пример манифеста — право в формате SYS-06 `lessons:lessons:read`; путь теста реестра провайдеров — `tests/modules/llm_gateway/unit/` (раскладка SYS-10) | draft |
| 1.0 | 2026-10-11 | пользователь | Утверждена на гейте G1 блока Б этапа 1 без изменений (PR #3) | approved |
