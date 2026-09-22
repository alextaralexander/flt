# ColoredLogger - Утилита для создания цветных логгеров с тегами  
  
Расширенная библиотека для Python, которая добавляет поддержку цветного логирования с системой тегов. Позволяет создавать красивые и информативные логи с использованием 10 вст роенных цветов и настраиваемых тегов.  
## Особенности  
  
- **10 встроенных цветов**: red, green, yellow, blue, magenta, cyan, white, orange, purple, ocean  
- **15 предустановленных тегов**: incoming, outgoing, success, error, warning, info, debug, api, database, cache, event, metric, security, config, model  
- **Поддержка стандартных уровней логирования** с тегами (debug, info, warning, error, critical)  
- **Автоматическое форматирование JSON** и объектов Pydantic  
- **Гибкая настройка** с возможностью добавления кастомных цветов и тегов  
- **Удобный синтаксис** с поддержкой цепочек вызовов  
- **Полная обратная совместимость** со стандартным logging  
  
## Quick start
  
```python  
from colored_logger import get_colored_logger  
  
# Создание логгера  
logger = get_colored_logger("colored_logger")  
  
# Простое цветное сообщение  
logger.green("Все хорошо!")  
logger.red("Что-то пошло не так")  
  
# Сообщения с тегами  
logger.green.success("Операция завершена успешно")  
logger.red.error("Критическая ошибка")  
logger.yellow.warning("Внимание: CUDA не используется :(")  
  
# Стандартные методы с тегами  
logger.info.api("Запрос к внешнему API")  
logger.error.database("Ошибка подключения к БД")  
```  
## Основные возможности  
**1. Цветные сообщения**  
Используйте любой из 10 встроенных цветов:  
```python 
logger = get_colored_logger("app")  
  
logger.red("Красное сообщение")  
logger.green("Зеленое сообщение") 
logger.yellow("Желтое сообщение")  
logger.blue("Синее сообщение")  
logger.magenta("Пурпурное сообщение")  
logger.cyan("Голубое сообщение")  
logger.white("Белое сообщение")  
logger.orange("Оранжевое сообщение")  
logger.purple("Фиолетовое сообщение")  
logger.ocean("Океанское сообщение")  
```

**2. Теги для категоризации**  
Каждый цвет поддерживает все предустановленные теги:  
```python
logger.blue.info("Информационное сообщение")  
logger.yellow.warning("Предупреждение")  
logger.red.error("Ошибка")  
logger.green.success("Успех")  

logger.orange.api("Вызов API")  
logger.cyan.database("Операция с БД")  
logger.purple.cache("Работа с cashем")  
logger.ocean.config("Настройки конфигурации")  

logger.magenta.event("Событие системы")  
logger.white.metric("Метрика производительности")  
logger.red.security("Проблема безопасности")  
logger.blue.model("Настройки модели")  

logger.yellow.incoming("Входящий запрос")  
logger.orange.outgoing("Исходящий ответ")  
```
  
**3. Стандартные уровни логирования с тегами**  
Все стандартные методы (debug, info, warning, error, critical) поддерживают теги:  
  
**Обычное использование (без изменений)**  
```python
logger.info("Стандартное сообщение")  
logger.warning("Стандартное предупреждение")  
logger.error("Стандартная ошибка")  
```
  
**С тегами**  
```python
logger.info.database("Запрос к базе данных")  
logger.warning.api("Медленный ответ API")  
logger.error.security("Нарушение безопасности")  
logger.debug.cache("Отладка кеша")  
logger.critical.system("Критическая ошибка системы")  
```  
  
**4. Автоматическое форматирование данных**  
Логгер автоматически форматирует различные типы данных:  

**Словари**  
```python
user_data = {"id": 123, "name": "John", "email": "john@example.com"}  
logger.blue.api("Получены данные пользователя", user_data)  
```
  
**Объекты Pydantic**  
```python
from pydantic import BaseModel  
  
class User(BaseModel):  
    id: int  
    name: str  
    email: str 
    
user = User(id=123, name="John", email="john@example.com")  
logger.green.success("Пользователь создан", user)  
``` 
**Обычные объекты**  
```python
class SimpleObject:  
    def __init__(self):  
        self.status = "active"  
        self.count = 42  
  
obj = SimpleObject()  
logger.yellow.info("Статус объекта", obj)  
```
**5. Настройка и кастомизация**  
  
**Кастомные цвета**  
```python
custom_colors = {  
    'pink': '\033[38;5;213m',  
    'lime': '\033[38;5;154m',  
    'gold': '\033[38;5;220m'  
}  
  
logger = get_colored_logger("app", custom_colors=custom_colors)  
  
logger.pink("Розовое сообщение")  
logger.lime.success("Лаймовый успех")  
logger.gold.warning("Zoloto")  
```
**Кастомные теги**  
```python
custom_tags = {  
    'payment': 'PAYMENT',  
    'auth': 'AUTH',  
    'notification': 'NOTIFY'  
}  
  
logger = get_colored_logger("app", custom_tags=custom_tags)  
  
logger.green.payment("Платеж обработан")  
logger.blue.auth("Пользователь авторизован")  
logger.purple.notification("Уведомление отправлено")  
```
**Комбинированная настройка**  
```python
logger = get_colored_logger(  
    "my_app",  
    level=logging.DEBUG,  
    custom_colors={  
        'pink': '\033[38;5;213m',  
        'lime': '\033[38;5;154m'  
    },  
    custom_tags={  
        'payment': 'PAYMENT',  
        'auth': 'AUTH'  
    }  
)  
  
logger.pink.payment("Обработка платежа")  
logger.lime.auth("Успешная авторизация")  
```
  
