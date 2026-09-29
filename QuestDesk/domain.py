"""Pure business rules, independent of the interface and PostgreSQL."""
REWARDS = {'easy': (40, 15), 'normal': (80, 30), 'hard': (140, 50)}
DIFFICULTIES = {'easy': 'Лёгкий', 'normal': 'Обычный', 'hard': 'Сложный'}
STATUSES = {'draft': 'Запланирован', 'active': 'В работе', 'completed': 'Завершён', 'failed': 'Не выполнен'}


class RuleError(ValueError):
    pass


def level(xp):
    return xp // 200 + 1


def validate_text(value, label, maximum):
    value = value.strip()
    if not value or len(value) > maximum:
        raise RuleError(f'{label}: введите от 1 до {maximum} символов.')
    return value


def require_state(quest, *states):
    if quest['status'] not in states:
        raise RuleError('Это действие недоступно в текущем состоянии квеста.')
