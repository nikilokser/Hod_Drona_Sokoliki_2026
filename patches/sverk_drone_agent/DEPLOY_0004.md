# Раскатка патча 0004 (голосование) на остальные дроны

Пошаговая инструкция для sverk-108, sverk-4, sverk-6, drone-05, drone-06 (и
любого следующего). Патч 0004 самодостаточен — не требует предварительного
применения 0001-0003 (они чинят другое: таймауты полётных команд).

**Важно:** IP из README устарели у части дронов (третий октет сменился с `.1`
на `.12` минимум у бывшего sverk-8 → `192.168.12.8`, теперь `king-8`) —
уточните актуальный IP каждого дрона перед подключением, не берите на веру
таблицу «Куда раскатывать» в README.md.

## 0. Предварительно проверить на дроне

```bash
ssh pi@<IP_ДРОНА>
sudo systemctl status sverk-drone-agent.service --no-pager | head -6
```

Должно быть `active (running)`. Если `pseudo` — патч работает как задуман
(перехватывает `[ГОЛОСОВАНИЕ]` до regex-парсера). Если уже `agent` — патч всё
равно безопасен (просто не понадобится regex-обход), но тогда голосование,
скорее всего, и так может идти через штатный LLM-путь — сначала проверьте,
не нужен ли патч вообще.

## 1. Задать реальные учётные данные для LLM

На дроне: `~/.sverk_drone_agent_env.sh` (или файл, на который указывает
`SVERK_DRONE_AGENT_ENV_FILE` в override.conf) — там уже есть строки
`OPENAI_BASE_URL`/`OPENAI_MODEL`/`OPENAI_API_KEY`, их нужно поправить на
проверенные значения. **Единственное, что нужно вписывать руками — ключ**
(секрет, в репозиторий и в этот файл-инструкцию не кладём). Всё остальное —
уже готовые, подтверждённые рабочими 2026-08-01 значения:

- `OPENAI_BASE_URL='https://ai.sverk.io/v1'`
- `OPENAI_MODEL='gemma-4-31b'` — быстрая (~0.15-4с на тёплом вызове),
  подтверждённо доступна ключу, использовавшемуся при отладке 0004 на
  king-8. Из проверенных тем же ключом альтернатив (если понадобится
  сменить модель): `deepseek-v4-pro`, `Gemma 4`, `gemma4-vlm`, `куцк`.
  **Не ставить** `deepseek-v4-flash` — 2026-08-01 стабильно падала 500-й
  ошибкой у самого провайдера (`Connection error`, не наша проблема, но
  сама модель в тот день была недоступна).
- `LLM_API_KEY_ENV='OPENAI_API_KEY'` — не трогать, уже верно.

Применить одной командой на дроне (заменяет только эти строки, остальной
файл — `CHESS_*`/`FLEET_*`/лимиты полёта и т.п. — не трогает):

```bash
sed -i "s|^export OPENAI_BASE_URL=.*|export OPENAI_BASE_URL='https://ai.sverk.io/v1'|" ~/.sverk_drone_agent_env.sh
sed -i "s|^export OPENAI_MODEL=.*|export OPENAI_MODEL='gemma-4-31b'|" ~/.sverk_drone_agent_env.sh
sed -i "s|^export OPENAI_API_KEY=.*|export OPENAI_API_KEY='ВСТАВЬТЕ_КЛЮЧ_СЮДА'|" ~/.sverk_drone_agent_env.sh
```

Затем открыть файл (`nano ~/.sverk_drone_agent_env.sh`) и вручную заменить
`ВСТАВЬТЕ_КЛЮЧ_СЮДА` на реальный ключ шлюза (тот же, что на king-8 и в
`STRONG_MODEL_API_KEY` из `web/backend/.env` нашего веб-бэкенда). Проверить,
что подставилось верно (без вывода самого ключа):

```bash
grep -c "OPENAI_API_KEY='ВСТАВЬТЕ_КЛЮЧ_СЮДА'" ~/.sverk_drone_agent_env.sh   # должно быть 0
grep -c "OPENAI_API_KEY=''" ~/.sverk_drone_agent_env.sh                     # должно быть 0
```

Если ключ на этом дроне окажется **другим** (не тем, что на king-8) и
`gemma-4-31b` ему недоступна — узнать реально доступные этому ключу модели:

```bash
curl -s https://ai.sverk.io/v1/chat/completions \
  -H "Authorization: Bearer <КЛЮЧ>" -H "Content-Type: application/json" \
  -d '{"model": "любая-заведомо-неверная", "messages": [{"role":"user","content":"тест"}]}'
```

Ответ вида `"key not allowed to access model. This key can only access
models=[...]"` перечислит реально доступные модели — взять любую из списка
и поставить в `OPENAI_MODEL` тем же способом.

## 2. Скопировать файлы патча

С этой машины (там, где лежит этот репозиторий):

```bash
DRONE_IP=<IP_ДРОНА>
scp patches/sverk_drone_agent/pseudo_agent_text_node.py.patched \
  pi@$DRONE_IP:/home/pi/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_pseudo_agent_ros1/scripts/pseudo_agent_text_node.py
scp patches/sverk_drone_agent/vote_llm_call.py \
  pi@$DRONE_IP:/home/pi/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_pseudo_agent_ros1/scripts/vote_llm_call.py
```

(На всякий случай бэкап оригинала перед перезаписью — на самом дроне:
`cp .../pseudo_agent_text_node.py .../pseudo_agent_text_node.py.bak-$(date +%Y%m%d-%H%M%S)`
до выполнения scp выше.)

## 3. Применить на дроне

```bash
ssh pi@$DRONE_IP

chmod +x /home/pi/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_pseudo_agent_ros1/scripts/vote_llm_call.py

python3 -m py_compile /home/pi/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_pseudo_agent_ros1/scripts/pseudo_agent_text_node.py
python3 -m py_compile /home/pi/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_pseudo_agent_ros1/scripts/vote_llm_call.py
# обе команды должны отработать без вывода (успех)

rm -rf /home/pi/catkin_ws/src/sverk_drone_agent/ros1_ws/src/drone_pseudo_agent_ros1/scripts/__pycache__
sudo systemctl daemon-reload
sudo systemctl restart sverk-drone-agent.service
sleep 5
sudo systemctl status sverk-drone-agent.service --no-pager | head -10
```

Ожидается `active (running)`, оба процесса в CGroup (`bridge_node.py` и
`pseudo_agent_text_node.py`/`*_agent_text_node`). Дрон в этот момент должен
стоять на земле, разоружён — рестарт обрывает текущую команду агента.

## 4. Проверить, что обычные команды не сломались

Безопасный нефлайтовый запрос (на самом дроне):

```bash
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash
rostopic pub -1 /agent/text_command std_msgs/String \
  "data: '{\"message_id\": \"check-1\", \"robot_id\": \"<ROBOT_ID>\", \"text\": \"статус\"}'" &
rostopic echo -n 1 /agent/answer
```

Ожидается `status: completed` с реальными полями статуса за пару секунд —
то же самое поведение, что было до патча.

## 5. Проверить голосование

Тем же способом, с текстом голосования:

```bash
python3 - <<'PY'
import rospy, json, time
from std_msgs.msg import String
rospy.init_node("deploy_check", anonymous=True)
pub = rospy.Publisher("/agent/text_command", String, queue_size=1)
for _ in range(50):
    if pub.get_num_connections() > 0:
        break
    time.sleep(0.2)
text = ("[ГОЛОСОВАНИЕ] Позиция: rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w - - 0 1. "
        "Предложен ход конь g1-f3. Обоснование: тест раскатки. "
        "Ответь строго одной строкой в одном из форматов: "
        "\"ДА: <причина>\", \"НЕТ: <причина>\" или \"ХОД: <клетка>-<клетка>: <причина>\".")
pub.publish(String(data=json.dumps({"message_id": "check-2", "robot_id": "<ROBOT_ID>", "text": text}, ensure_ascii=False)))
time.sleep(0.5)
PY

rostopic echo -n 1 /agent/answer
```

Ожидается ответ строго `ДА: ...` / `НЕТ: ...` / `ХОД: ...` (обычно 1-5 с;
при нестабильной сети может занять до ~25 с из-за встроенных повторов — это
нормально). **Не** должно быть «Команда не поддерживается» (значит патч не
применился/кэш не сброшен) и **не** должно вызываться никаких полётных
инструментов (взлёт/перелёт) — если дрон взлетел в ответ на это сообщение,
немедленно останавливайте и разбирайтесь, это означает патч лёг не так, как
задумано.

## 6. Проверить через настоящий путь (с ноутбука, где крутится веб-бэкенд)

Привязать дрон к фигуре (вкладка «Привязка роботов» в веб-морде, или через
API) и один раз нажать «Предложить ход ИИ» при живом голосовании — новая
запись должна появиться в «Ленте переговоров» с реальным текстом ответа
дрона, не с ошибкой про 403/«не поддерживается».

## После — обновить таблицу в README.md

Отметить в таблице «Куда раскатывать» (`README.md` этой же папки) актуальный
IP и статус `0004` для этого робота, датой.
