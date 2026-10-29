"""Набор эмодзи для панели выбора (по образцу быстрой панели Discord) и поиск по ним.

Каждая запись — «эмодзи|слова для поиска» (по-русски и по-английски через пробел).
Категории и порядок, как в Discord: смайлы, люди, природа, еда, активности, путешествия,
предметы, символы.
"""
from __future__ import annotations

CATEGORIES: list[tuple[str, str, list[str]]] = [
    ("smileys", "😀", [
        "😀|улыбка grinning smile", "😃|радость smiley happy", "😄|смех smile laugh", "😁|ухмылка grin",
        "😆|хохот laughing", "😅|пот неловко sweat", "🤣|ржу rofl lol", "😂|слёзы смех joy tears",
        "🙂|улыбка slight", "🙃|вверх ногами upside", "😉|подмигивание wink", "😊|смущение blush",
        "😇|ангел angel halo", "🥰|влюблён love hearts", "😍|глаза сердечки heart eyes", "🤩|звёзды star struck wow",
        "😘|поцелуй kiss", "😗|поцелуйчик kissing", "😚|поцелуй kissing closed", "😋|вкусно yum",
        "😛|язык tongue", "😜|подмигивает язык wink tongue", "🤪|безумный zany crazy", "😝|язык прищур squint tongue",
        "🤑|деньги money", "🤗|обнимашки hug", "🤭|ой рука hand over mouth", "🤫|тсс shush quiet",
        "🤔|думаю thinking hmm", "🤐|молчу zipper", "🤨|бровь raised eyebrow", "😐|нейтрально neutral",
        "😑|без эмоций expressionless", "😶|без рта no mouth", "😏|ухмылка smirk", "😒|недоволен unamused",
        "🙄|закатил глаза eye roll", "😬|гримаса grimace", "🤥|ложь lying", "😌|облегчение relieved",
        "😔|грусть pensive", "😪|сонный sleepy", "🤤|слюни drool", "😴|сон sleep zzz",
        "😷|маска mask sick", "🤒|температура thermometer", "🤕|повязка bandage", "🤢|тошнит nauseated",
        "🤮|рвота vomit", "🤧|чих sneeze", "🥵|жарко hot", "🥶|холодно cold", "🥴|пьян woozy",
        "😵|головокружение dizzy", "🤯|взрыв мозга mind blown", "🤠|ковбой cowboy", "🥳|праздник party",
        "😎|круто cool sunglasses", "🤓|ботан nerd", "🧐|монокль monocle", "😕|растерян confused",
        "😟|тревога worried", "🙁|грустно frown", "☹️|грусть sad", "😮|удивление open mouth",
        "😯|ого hushed", "😲|шок astonished", "😳|красный flushed", "🥺|умоляю pleading",
        "😦|нахмурился frowning", "😧|страдание anguished", "😨|страх fearful", "😰|холодный пот anxious",
        "😥|грусть облегчение sad relieved", "😢|плачу cry", "😭|рыдаю sob", "😱|крик scream",
        "😖|мучение confounded", "😣|упорство persevere", "😞|разочарован disappointed", "😓|пот downcast",
        "😩|устал weary", "😫|измотан tired", "🥱|зевок yawn", "😤|пар из носа triumph", "😡|злой angry",
        "😠|сердит angry mad", "🤬|ругань cursing", "😈|дьяволёнок devil", "👿|злой дьявол imp",
        "💀|череп skull", "💩|какашка poop", "🤡|клоун clown", "👻|призрак ghost", "👽|пришелец alien",
        "🤖|робот robot", "😺|кот cat smile", "😸|кот смех cat grin", "😹|кот слёзы cat joy", "😻|кот любовь cat heart",
        "🙈|не вижу see no evil monkey", "🙉|не слышу hear no evil", "🙊|не скажу speak no evil",
    ]),
    ("people", "👋", [
        "👋|привет рука wave hello", "🤚|ладонь raised back hand", "🖐️|рука hand", "✋|стоп stop hand",
        "🖖|вулкан spock", "👌|окей ok", "🤌|итальянский pinched", "🤏|чуть pinch", "✌️|мир victory peace",
        "🤞|скрестил crossed fingers luck", "🤟|люблю love you", "🤘|рок rock", "🤙|позвони call me",
        "👈|влево point left", "👉|вправо point right", "👆|вверх point up", "👇|вниз point down",
        "☝️|один index up", "👍|класс лайк thumbs up like", "👎|дизлайк thumbs down dislike", "✊|кулак fist",
        "👊|удар punch", "🤛|кулак влево left fist", "🤜|кулак вправо right fist", "👏|аплодисменты clap",
        "🙌|ура raising hands", "👐|открытые руки open hands", "🤲|ладони palms", "🤝|рукопожатие handshake",
        "🙏|пожалуйста молитва please pray thanks", "✍️|пишу writing", "💅|маникюр nail", "🤳|селфи selfie",
        "💪|сила бицепс muscle strong", "🦾|протез mechanical arm", "👀|глаза eyes look", "👁️|глаз eye",
        "👅|язык tongue", "👄|рот lips mouth", "🧠|мозг brain", "🦷|зуб tooth", "👂|ухо ear", "👃|нос nose",
        "👶|малыш baby", "🧒|ребёнок child", "👦|мальчик boy", "👧|девочка girl", "🧑|человек person",
        "👨|мужчина man", "👩|женщина woman", "🧓|пожилой older", "👴|дед old man", "👵|бабушка old woman",
        "🙋|рука вверх raising hand", "🤦|фейспалм facepalm", "🤷|не знаю shrug", "🙅|нет no", "🙆|ок gesture ok",
        "💁|информация info", "🙇|поклон bow", "🧑‍💻|программист technologist developer", "🧑‍🚀|космонавт astronaut",
        "🦸|герой superhero", "🧙|маг mage wizard", "🧛|вампир vampire", "🧟|зомби zombie", "🧞|джинн genie",
    ]),
    ("nature", "🐶", [
        "🐶|собака dog", "🐱|кот cat", "🐭|мышь mouse", "🐹|хомяк hamster", "🐰|кролик rabbit", "🦊|лиса fox",
        "🐻|медведь bear", "🐼|панда panda", "🐨|коала koala", "🐯|тигр tiger", "🦁|лев lion", "🐮|корова cow",
        "🐷|свинья pig", "🐸|лягушка frog", "🐵|обезьяна monkey", "🐔|курица chicken", "🐧|пингвин penguin",
        "🐦|птица bird", "🦆|утка duck", "🦅|орёл eagle", "🦉|сова owl", "🦇|летучая мышь bat", "🐺|волк wolf",
        "🐴|лошадь horse", "🦄|единорог unicorn", "🐝|пчела bee", "🐛|гусеница bug", "🦋|бабочка butterfly",
        "🐌|улитка snail", "🐞|божья коровка ladybug", "🐜|муравей ant", "🕷️|паук spider", "🐢|черепаха turtle",
        "🐍|змея snake", "🦖|динозавр dino t-rex", "🐙|осьминог octopus", "🦀|краб crab", "🐠|рыба fish",
        "🐬|дельфин dolphin", "🐳|кит whale", "🦈|акула shark", "🐘|слон elephant", "🦒|жираф giraffe",
        "🌵|кактус cactus", "🎄|ёлка christmas tree", "🌲|ель pine", "🌳|дерево tree", "🌴|пальма palm",
        "🌱|росток seedling", "🍀|клевер clover luck", "🍁|лист maple leaf", "🍂|листья fallen leaf",
        "🌷|тюльпан tulip", "🌹|роза rose", "🌻|подсолнух sunflower", "🌼|цветок blossom",
        "☀️|солнце sun", "🌙|луна moon", "⭐|звезда star", "🌟|сияющая звезда glowing star", "✨|искры sparkles",
        "⚡|молния lightning", "🔥|огонь fire", "💧|капля drop", "🌈|радуга rainbow", "☁️|облако cloud",
        "❄️|снег snowflake", "⛄|снеговик snowman", "🌊|волна wave", "🌍|земля earth globe",
    ]),
    ("food", "🍔", [
        "🍏|яблоко apple green", "🍎|яблоко красное apple", "🍐|груша pear", "🍊|апельсин orange", "🍋|лимон lemon",
        "🍌|банан banana", "🍉|арбуз watermelon", "🍇|виноград grapes", "🍓|клубника strawberry",
        "🍒|вишня cherries", "🍑|персик peach", "🥭|манго mango", "🍍|ананас pineapple", "🥥|кокос coconut",
        "🥝|киви kiwi", "🍅|помидор tomato", "🥑|авокадо avocado", "🥦|брокколи broccoli", "🥕|морковь carrot",
        "🌽|кукуруза corn", "🥔|картошка potato", "🍞|хлеб bread", "🥐|круассан croissant", "🧀|сыр cheese",
        "🥚|яйцо egg", "🍳|яичница fried egg", "🥓|бекон bacon", "🍔|бургер burger", "🍟|картошка фри fries",
        "🍕|пицца pizza", "🌭|хот-дог hot dog", "🥪|сэндвич sandwich", "🌮|тако taco", "🌯|буррито burrito",
        "🍝|паста spaghetti pasta", "🍜|лапша ramen noodles", "🍣|суши sushi", "🍤|креветка shrimp",
        "🍦|мороженое ice cream", "🍩|пончик donut", "🍪|печенье cookie", "🎂|торт cake birthday",
        "🍰|кусок торта cake slice", "🍫|шоколад chocolate", "🍬|конфета candy", "🍭|леденец lollipop",
        "☕|кофе coffee", "🍵|чай tea", "🥤|напиток soda drink", "🍺|пиво beer", "🍻|пиво cheers beers",
        "🥂|шампанское champagne cheers", "🍷|вино wine", "🍸|коктейль cocktail", "🥛|молоко milk",
    ]),
    ("activity", "⚽", [
        "⚽|футбол soccer football", "🏀|баскетбол basketball", "🏈|американский футбол football", "⚾|бейсбол baseball",
        "🎾|теннис tennis", "🏐|волейбол volleyball", "🏉|регби rugby", "🎱|бильярд pool 8ball", "🏓|пинг-понг ping pong",
        "🏸|бадминтон badminton", "🥊|бокс boxing", "🥋|единоборства martial arts", "⛳|гольф golf",
        "🎣|рыбалка fishing", "🎿|лыжи ski", "🏂|сноуборд snowboard", "🏆|кубок trophy", "🥇|золото gold medal first",
        "🥈|серебро silver medal", "🥉|бронза bronze medal", "🏅|медаль medal", "🎖️|награда military medal",
        "🎮|геймпад игра video game", "🕹️|джойстик joystick", "🎲|кубик dice", "🧩|пазл puzzle", "🎯|мишень dart target",
        "🎳|боулинг bowling", "🎭|театр masks theater", "🎨|палитра art paint", "🎬|кино clapper movie",
        "🎤|микрофон microphone", "🎧|наушники headphones", "🎸|гитара guitar", "🎹|пианино piano", "🥁|барабан drum",
        "🎺|труба trumpet", "🎻|скрипка violin", "🎉|ура party popper tada", "🎊|конфетти confetti", "🎈|шарик balloon",
        "🎁|подарок gift present",
    ]),
    ("travel", "🚗", [
        "🚗|машина car", "🚕|такси taxi", "🚌|автобус bus", "🚓|полиция police", "🚑|скорая ambulance",
        "🚒|пожарная fire engine", "🚚|грузовик truck", "🚜|трактор tractor", "🏍️|мотоцикл motorcycle",
        "🚲|велосипед bike bicycle", "🛴|самокат scooter", "🚂|поезд train", "🚆|электричка train", "🚀|ракета rocket",
        "✈️|самолёт airplane plane", "🚁|вертолёт helicopter", "⛵|парусник sailboat", "🚢|корабль ship",
        "⚓|якорь anchor", "⛽|заправка fuel", "🚦|светофор traffic light", "🚧|ремонт construction",
        "🏠|дом house home", "🏢|офис office building", "🏥|больница hospital", "🏦|банк bank", "🏫|школа school",
        "🏰|замок castle", "🗼|башня tower", "🗽|статуя свободы statue liberty", "⛰️|гора mountain", "🏔️|горы snow mountain",
        "🏖️|пляж beach", "🏝️|остров island", "🌅|рассвет sunrise", "🌃|ночь город night city", "🗺️|карта map",
        "🧭|компас compass", "⌛|песочные часы hourglass", "⏰|будильник alarm clock",
    ]),
    ("objects", "💡", [
        "⌚|часы watch", "📱|телефон phone mobile", "💻|ноутбук laptop", "⌨️|клавиатура keyboard", "🖥️|монитор desktop computer",
        "🖱️|мышь computer mouse", "💾|дискета floppy save", "💿|диск cd", "📷|камера camera", "📸|фото вспышка camera flash",
        "📹|видеокамера video camera", "📺|телевизор tv", "📻|радио radio", "🔋|батарея battery", "🔌|вилка plug",
        "💡|лампочка идея bulb idea", "🔦|фонарик flashlight", "📚|книги books", "📖|книга book", "📝|заметка memo note",
        "✏️|карандаш pencil", "🖊️|ручка pen", "🖌️|кисть paintbrush", "📌|кнопка pushpin", "📍|метка pin location",
        "📎|скрепка paperclip", "✂️|ножницы scissors", "📁|папка folder", "📂|открытая папка open folder",
        "📅|календарь calendar", "📊|график chart bar", "📈|рост chart up", "📉|падение chart down", "📋|буфер clipboard",
        "🔒|замок lock", "🔓|открыт unlock", "🔑|ключ key", "🔨|молоток hammer", "🔧|ключ гаечный wrench", "⚙️|шестерёнка gear settings",
        "🧰|инструменты toolbox", "🔗|ссылка link", "🔍|поиск search magnifier", "🔔|колокольчик bell", "🔕|без звука mute bell",
        "📢|громкоговоритель loudspeaker", "💬|сообщение speech", "💭|мысль thought", "✉️|письмо envelope mail", "📧|email e-mail",
        "💰|деньги money bag", "💵|доллар dollar", "💳|карта credit card", "💎|алмаз gem diamond", "🛒|корзина cart",
        "🐞|баг bug", "🧪|пробирка test tube", "🔬|микроскоп microscope", "💊|таблетка pill", "🗑️|корзина trash", "🚫|запрещено prohibited",
    ]),
    ("symbols", "❤️", [
        "❤️|сердце красное heart red", "🧡|оранжевое сердце orange heart", "💛|жёлтое сердце yellow heart",
        "💚|зелёное сердце green heart", "💙|синее сердце blue heart", "💜|фиолетовое сердце purple heart",
        "🖤|чёрное сердце black heart", "🤍|белое сердце white heart", "💔|разбитое сердце broken heart",
        "💕|два сердца two hearts", "💖|сердце блеск sparkling heart", "💯|сто баллов hundred 100", "💢|злость anger",
        "💥|взрыв boom collision", "💫|головокружение dizzy star", "💦|брызги sweat droplets", "💨|ветер dash",
        "✅|галочка check ok done", "☑️|флажок check box", "✔️|галочка heavy check", "❌|крестик cross x no",
        "❎|крест cross mark", "❓|вопрос question", "❔|вопрос белый white question", "❗|восклицание exclamation",
        "❕|восклицание белый white exclamation", "⚠️|внимание warning", "⛔|стоп no entry", "🔴|красный круг red circle",
        "🟠|оранжевый круг orange circle", "🟡|жёлтый круг yellow circle", "🟢|зелёный круг green circle",
        "🔵|синий круг blue circle", "🟣|фиолетовый круг purple circle", "⚫|чёрный круг black circle",
        "⚪|белый круг white circle", "🟥|красный квадрат red square", "🟩|зелёный квадрат green square",
        "🟦|синий квадрат blue square", "➕|плюс plus", "➖|минус minus", "➗|деление divide", "✖️|умножить multiply",
        "➡️|стрелка вправо arrow right", "⬅️|стрелка влево arrow left", "⬆️|стрелка вверх arrow up",
        "⬇️|стрелка вниз arrow down", "↗️|стрелка вправо вверх up right", "↘️|стрелка вправо вниз down right",
        "🔄|обновить refresh arrows", "🔁|повтор repeat", "🆕|новое new", "🆗|ок ok button", "🔝|топ top",
        "🏁|финиш flag finish", "🚩|флаг flag red", "🏳️|белый флаг white flag", "©️|копирайт copyright", "™️|торговая марка trademark",
    ]),
]

QUICK = ["👍", "👎", "😂", "❤️", "🔥", "🎉", "👀", "✅", "❌", "⚠️", "❓", "💯"]   # стартовый «часто используемые»


def _split(entry: str) -> tuple[str, str]:
    char, _, words = entry.partition("|")
    return char, words.lower()


ALL: list[tuple[str, str]] = [_split(e) for _name, _icon, items in CATEGORIES for e in items]


def search(query: str) -> list[str]:
    """Поиск по словам (как быстрая панель Discord): все слова запроса должны входить
    в ключевые слова эмодзи по началу слова или подстроке."""
    words = query.lower().split()
    if not words:
        return []
    return [char for char, kw in ALL if all(w in kw for w in words)]
