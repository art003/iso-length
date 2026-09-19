SYSTEM_PROMPT = """По изометрии реши, какие числа - длина трубы (и веток), какие нет.

Длина = сумма участков по оси + ответвления. Кусок один раз.
Лист сам по себе, до ПОДКЛЮЧЕНИЕ и СМ.
X/Y/Z, DN, опоры О3/Ф4, кружки позиций - не длина.
Вложенное не складывай: 916 и 300 внутри 1950 и 840 в примере - это exclude_nested.
Габарит типа 23525/24100, если уже есть куски 6000 - exclude_nested, не include.
Не выкидывай нормальные участки трассы (600, 650, 840, 6000) как вложенные.
Короткий отвод (34 мм) - include.
Штурвал UP/WEST/EAST - ambiguous, в сумму не пихай.
Если не уверен - ambiguous, не include.
Цифры сам не выдумывай.

Только JSON:
{"line_id":"...","items":[{"id":"D1","decision":"include|exclude_nested|not_length|ambiguous","role":"main|branch|overall_same_run|support_offset|valve|bom|other","reason":"..."}],"notes":[]}
Все id из списка обязательны. reason до 5 слов. notes пустой.
"""


def user_prompt(sheet_no: int, line_id: str, candidates: list[dict]) -> str:
    lines = [
        f"Лист {sheet_no}, линия {line_id}. Размеры в мм.",
        "На картинке метки D1, D2...",
        "Список:",
    ]
    for c in candidates:
        lines.append(f"- {c['id']}: {c['value_mm']} мм; {c['local_hint']}; рядом: {c['nearby'][:160]}")
    lines.append(
        "С учебного листа LC_1031: 60+1950+650+840+522+250+34=4306, 916 и 300 не брать."
    )
    return "\n".join(lines)
