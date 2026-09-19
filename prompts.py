SYSTEM_PROMPT = """По изометрии реши, какие числа - длина трубы (и веток), какие нет.

Длина = сумма участков по оси + ответвления. Кусок один раз.
Лист сам по себе, до ПОДКЛЮЧЕНИЕ и СМ.
X/Y/Z пятизначные (Z+ 37329, X 45300) - координаты узла. Их в списке D нет.
Число рядом с такой координатой (1383, 320, 850) - длина участка, include, не not_length.
Вложенное не складывай: 916 и 300 внутри 1950 и 840 - exclude_nested.
Габарит типа 23525/24100/3505/4116, если уже есть куски, или метка Н.О. / LT / overall_mark / overall_pair - exclude_nested.
Два близких прогона на разных участках (2000 и 2400) - оба include. Не делай 2400 «габаритом поверх» 2000.
Если два числа почти в одной точке (2463 и 2950, overall_pair) - большее габарит.
Не выкидывай нормальные участки (600, 650, 840, 1383, 2400, 5000, 5200, 6000).
Если «родитель» сам габарит - куски верни в include.
Короткий отвод (34 мм) - include.
Штурвал UP/WEST/EAST - not_length, не ambiguous.
Изоляция / обогрев рядом - not_length.
near_plant_coord в подсказке = рядом координата узла, это число всё равно длина.
support_repeat - опора, not_length.
Если не уверен - ambiguous, не include.
Цифры сам не выдумывай.

Только JSON:
{"line_id":"...","items":[{"id":"D1","decision":"include|exclude_nested|not_length|ambiguous","role":"main|branch|overall_same_run|support_offset|valve|bom|other","reason":"..."}],"notes":[]}
Все id из списка обязательны. reason до 5 слов. notes пустой.
"""

REVIEW_SYSTEM = """Второй проход. Ты проверяешь чужой JSON по той же изометрии. Картинка та же.

Жёстко:
- габарит (Н.О., overall_mark, overall_pair, LT, 23525/24100/3505/4116 поверх кусков) = exclude_nested
- штурвал и изоляция = not_length
- вложенное как 916 в 1950 и 300 в 840 = exclude_nested
- рядом Z+/X/Y пятизначное — это координата узла; 1383/320 не выкидывай
- два прогона 2000 и 2400 оба include, 2400 не габарит
- куски трассы (5000, 5200, 6000, 1383, 2400) не выкидывай
- если первый проход выкинул кусок «внутрь» габарита - верни include
- не уверен = ambiguous
Цифры не выдумывай. Верни полный JSON, все id.

Формат тот же:
{"line_id":"...","items":[{"id":"D1","decision":"include|exclude_nested|not_length|ambiguous","role":"main|branch|overall_same_run|support_offset|valve|bom|other","reason":"..."}],"notes":[]}
reason до 5 слов. notes пустой.
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


def review_prompt(
    sheet_no: int,
    line_id: str,
    candidates: list[dict],
    first: dict,
    hint: str = "",
) -> str:
    lines = [
        f"Лист {sheet_no}, линия {line_id}. Второй проход, проверь черновик по картинке.",
        "Черновик первого прохода:",
    ]
    for it in first.get("items") or []:
        lines.append(f"- {it.get('id')}: {it.get('decision')} / {it.get('reason') or ''}")
    if hint:
        lines.append("Python уже заметил: " + hint)
    lines.append("Размеры:")
    for c in candidates:
        lines.append(f"- {c['id']}: {c['value_mm']} мм; {c['local_hint']}; рядом: {c['nearby'][:120]}")
    lines.append("Исправь ошибки. Верни полный JSON, все id.")
    return "\n".join(lines)
