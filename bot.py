import logging
import json
from datetime import datetime, timedelta
import pytz
import io
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import (
    Updater, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, CallbackContext,
    Filters
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import Config
from database import Database
from api_client import ClashRoyaleAPI
from keyboards import Keyboards
from nickname_manager import NicknameManager

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, Config.LOG_LEVEL)
)
logger = logging.getLogger(__name__)

# Initialize components
db = Database()
api = ClashRoyaleAPI(Config.CR_API_TOKEN)
nickname_manager = NicknameManager(api, db)
scheduler = BackgroundScheduler()

# States
REGISTER, CONFIRM_TAG = range(2)

class ClanBot:
    def __init__(self, token, webhook_url=None):
        self.token = token
        self.webhook_url = webhook_url
        
        if webhook_url:
            self.updater = Updater(token, use_context=True)
            self.updater.start_webhook(
                listen="0.0.0.0",
                port=Config.PORT,
                url_path=token,
                webhook_url=f"{webhook_url}/{token}"
            )
        else:
            self.updater = Updater(token, use_context=True)
            self.updater.start_polling()
        
        self.dispatcher = self.updater.dispatcher
        
        # Get bot username
        self.bot_username = self.updater.bot.get_me().username
        
        self.register_handlers()
        self.setup_scheduler()
        logger.info(f"Bot initialized with username: @{self.bot_username}")
    
    def register_handlers(self):
        """Register all handlers"""
        # Basic commands
        self.dispatcher.add_handler(CommandHandler("start", self.start))
        self.dispatcher.add_handler(CommandHandler("help", self.help_command))
        self.dispatcher.add_handler(CommandHandler("register", self.register))
        self.dispatcher.add_handler(CommandHandler("stats", self.stats))
        self.dispatcher.add_handler(CommandHandler("clan", self.clan_info))
        
        # Group chat commands
        self.dispatcher.add_handler(CommandHandler("war", self.war_info))
        self.dispatcher.add_handler(CommandHandler("attacks", self.war_attacks))
        self.dispatcher.add_handler(CommandHandler("top", self.top_players))
        self.dispatcher.add_handler(CommandHandler("sync_me", self.sync_me))

        # Admin commands
        self.dispatcher.add_handler(CommandHandler("admin", self.admin_panel))

        # Utility commands
        self.dispatcher.add_handler(CommandHandler("battles", self.show_battles))
        self.dispatcher.add_handler(CommandHandler("members", self.show_members))
        self.dispatcher.add_handler(CommandHandler("donations", self.show_donations))

        # War API commands
        self.dispatcher.add_handler(CommandHandler("warlog", self.show_war_log))
        self.dispatcher.add_handler(CommandHandler("river", self.show_river_race))
        self.dispatcher.add_handler(CommandHandler("tournaments", self.search_tournaments, pass_args=True))
        self.dispatcher.add_handler(CommandHandler("river_check", self.manual_river_check))
        self.dispatcher.add_handler(CommandHandler("donations_full", self.show_donations_full))
        self.dispatcher.add_handler(CommandHandler("warstats", self.show_war_stats))
        
        # Conversation handler (detailed registration)
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('reg', self.start_detailed_registration)],
            states={
                REGISTER: [MessageHandler(Filters.text & ~Filters.command & Filters.private, self.get_player_tag)],
                CONFIRM_TAG: [CallbackQueryHandler(self.confirm_registration, pattern='^(confirm|cancel)_')]
            },
            fallbacks=[CommandHandler('cancel', self.cancel_registration)],
            conversation_timeout=300,
            per_user=True,
            per_chat=True
        )
        self.dispatcher.add_handler(conv_handler)
        
        # Callback handlers
        self.dispatcher.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Message handlers
        self.dispatcher.add_handler(MessageHandler(Filters.status_update.new_chat_members, self.welcome_new_member))
        self.dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, self.handle_text_message))
    
    def setup_scheduler(self):
        """Setup background scheduler for automated tasks"""
        # Проверка речной гонки каждые 30 минут
        scheduler.add_job(
            self.check_river_race_period,
            'interval',
            minutes=30,
            id='river_race_check',
            replace_existing=True
        )
        
        # Запуск планировщика
        scheduler.start()
        logger.info("Scheduler started with river race monitoring")
    
    # ============ UTILITY METHODS ============
    
    def is_group_chat(self, update: Update):
        return update.effective_chat.type in ['group', 'supergroup']
    
    def is_admin(self, user_id):
        return db.is_admin(user_id)
    
    def get_bot_mention(self):
        return f"@{self.bot_username}"
    
    # ============ UTILITY FUNCTIONS ============
    
    def remove_emojis(self, text):
        """Удаление эмодзи из текста"""
        if not text:
            return text
        
        # Удаляем эмодзи (Unicode characters in specific ranges)
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags (iOS)
            "\U00002500-\U00002BEF"  # Chinese characters
            "\U00002702-\U000027B0"
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "\U0001f926-\U0001f937"
            "\U00010000-\U0010ffff"
            "\u2640-\u2642"
            "\u2600-\u2B55"
            "\u200d"
            "\u23cf"
            "\u23e9"
            "\u231a"
            "\ufe0f"  # dingbats
            "\u3030"
            "]+",
            flags=re.UNICODE
        )
        
        # Удаляем эмодзи и лишние пробелы
        text_without_emojis = emoji_pattern.sub(r'', text)
        # Удаляем лишние пробелы
        text_without_emojis = ' '.join(text_without_emojis.split())
        
        return text_without_emojis.strip()
    
    def format_custom_title(self, player_name, clan_role, player_tag=None):
        """Форматирование кастомного заголовка (роли) без эмодзи"""
        # Удаляем эмодзи из имени игрока
        clean_name = self.remove_emojis(player_name)
        
        # Формируем заголовок без эмодзи
        if clan_role.lower() == 'leader':
            title = f"👑 {clean_name}"
        elif clan_role.lower() == 'coleader':
            title = f"⭐ {clean_name}"
        elif clan_role.lower() == 'elder':
            title = f"🛡️ {clean_name}"
        elif clan_role.lower() == 'admin':
            title = f"🔧 {clean_name}"
        else:  # member
            title = clean_name
        
        # Обрезаем если слишком длинный
        if len(title) > 16:
            title = clean_name[:13] + "..."
        
        return title.strip()
    
    def promote_to_admin(self, context, chat_id, user_id, player_name, clan_role):
        """Назначение администратором с кастомным заголовком"""
        try:
            # Сначала проверяем, является ли уже администратором
            chat_member = context.bot.get_chat_member(chat_id, user_id)
            
            if chat_member.status not in ['administrator', 'creator']:
                # Назначаем права администратора с минимальными правами
                success = context.bot.promote_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    can_delete_messages=False,
                    can_restrict_members=False,
                    can_promote_members=False,
                    can_change_info=False,
                    can_invite_users=True,
                    can_pin_messages=False,
                    can_manage_video_chats=False,
                    can_manage_chat=False,
                    can_post_messages=True,
                    can_edit_messages=False,
                    can_manage_topics=False
                )
                
                if not success:
                    return False, "Не удалось назначить права администратора"
            
            # Устанавливаем кастомный заголовок (без эмодзи в заголовке)
            custom_title = self.format_custom_title(player_name, clan_role)
            
            # Устанавливаем заголовок
            try:
                context.bot.set_chat_administrator_custom_title(
                    chat_id=chat_id,
                    user_id=user_id,
                    custom_title=custom_title
                )
            except Exception as e:
                # Если не удалось установить заголовок, продолжаем без него
                logger.warning(f"Could not set custom title for {user_id}: {e}")
                custom_title = ""
            
            return True, custom_title
            
        except Exception as e:
            logger.error(f"Error promoting user {user_id}: {e}")
            return False, f"Ошибка: {str(e)}"
    
    def _format_time_remaining(self, iso_time):
        """Форматирование оставшегося времени"""
        try:
            from datetime import datetime, timezone
            end_time = datetime.fromisoformat(iso_time.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            
            # Если end_time не имеет timezone, добавляем UTC
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            
            remaining = end_time - now
            
            if remaining.total_seconds() <= 0:
                return "завершено"
            
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            
            if hours > 0:
                return f"{hours}ч {minutes}м"
            else:
                return f"{minutes}м"
        except Exception as e:
            logger.error(f"Error formatting time {iso_time}: {e}")
            return "неизвестно"
    
    # ============ MENUS & KEYBOARDS ============
    
    def get_group_welcome_keyboard(self):
        """Keyboard for new members in group"""
        keyboard = [
            [
                InlineKeyboardButton("🎮 Привязать тег", url=f"https://t.me/{self.bot_username}?start=register"),
                InlineKeyboardButton("🏰 Инфо о клане", callback_data="clan_info")
            ],
            [
                InlineKeyboardButton("📜 Правила", callback_data="show_rules"),
                InlineKeyboardButton("⚔️ Война", callback_data="war_info")
            ],
            [
                InlineKeyboardButton("👥 Топ игроков", callback_data="top_players"),
                InlineKeyboardButton("⚠️ Неактивные", callback_data="check_inactive")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_personal_menu_keyboard(self):
        """Keyboard for personal chat"""
        keyboard = [
            [
                InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats"),
                InlineKeyboardButton("🏰 Мой клан", callback_data="my_clan")
            ],
            [
                InlineKeyboardButton("🎁 Мои сундуки", callback_data="my_chests"),
                InlineKeyboardButton("⚔️ Мои бои", callback_data="my_battles")
            ],
            [
                InlineKeyboardButton("🔄 Синхронизировать", callback_data="sync_me"),
                InlineKeyboardButton("📝 Регистрация", callback_data="register_now")
            ],
            [
                InlineKeyboardButton("❓ Помощь", callback_data="help_menu"),
                InlineKeyboardButton("⚙️ Настройки", callback_data="settings_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_war_keyboard(self):
        """Keyboard for war info (теперь для River Race)"""
        keyboard = [
            [
                InlineKeyboardButton("🎯 Атаки игроков", callback_data="war_attacks"),
                InlineKeyboardButton("📊 Рейтинг", callback_data="river_race_ranking")
            ],
            [
                InlineKeyboardButton("👥 Участники", callback_data="river_race_participants"),
                InlineKeyboardButton("⏰ Таймер", callback_data="river_race_timer")
            ],
            [
                InlineKeyboardButton("🔄 Обновить", callback_data="refresh_war"),
                InlineKeyboardButton("🔔 Напомнить", callback_data="remind_war")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_admin_keyboard(self):
        """Keyboard for admin panel"""
        keyboard = [
            [
                InlineKeyboardButton("👢 Исключить", callback_data="admin_kick"),
                InlineKeyboardButton("⚠️ Предупредить", callback_data="admin_warn")
            ],
            [
                InlineKeyboardButton("🔄 Обновить никнеймы", callback_data="admin_update_nicks"),
                InlineKeyboardButton("🔄 Синхр. роли", callback_data="admin_sync_roles")
            ],
            [
                InlineKeyboardButton("👑 Назначить роли всем", callback_data="mass_promote"),
                InlineKeyboardButton("🔍 Проверить роли", callback_data="check_missing_roles")
            ],
            [
                InlineKeyboardButton("🔔 Напомнить о войне", callback_data="admin_remind"),
                InlineKeyboardButton("📊 Отчет", callback_data="admin_report")
            ],
            [
                InlineKeyboardButton("⚙️ Настройки чата", callback_data="admin_settings"),
                InlineKeyboardButton("📈 Статистика", callback_data="admin_stats")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    # ============ BASIC COMMANDS ============
    
    def start(self, update: Update, context: CallbackContext):
        user = update.effective_user
        user_id = user.id
        
        db.update_user_activity(user_id)
        
        if self.is_group_chat(update):
            welcome_text = f"""🏰 *Добро пожаловать в чат клана, {user.first_name}!*

Я - бот для управления кланом Clash Royale.

*Основные команды:*
/war - Текущая речная гонка
/attacks - Статус атак
/top - Топ игроков клана
/inactive - Неактивные игроки
/clan - Информация о клане
/rules - Правила клана

*Для управления никнеймом:*
Нажмите кнопку ниже👇"""
            
            update.message.reply_text(
                welcome_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=self.get_group_welcome_keyboard()
            )
        else:
            db_user = db.get_user_by_telegram_id(user_id)
            
            if context.args and context.args[0] == 'register':
                welcome_text = f"""👋 *Привет, {user.first_name}!*

📝 *Регистрация в Clash Royale Clan Bot*

Чтобы привязать ваш аккаунт, отправьте:
`/register #ВАШ_ТЕГ`

*Пример:*
`/register #2P0Y8C82U`

ℹ️ *Где найти тег:*
1. Откройте Clash Royale
2. Зайдите в свой профиль
3. Скопируйте тег (начинается с #)"""
                
                update.message.reply_text(
                    welcome_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=self.get_personal_menu_keyboard()
                )
            else:
                if db_user:
                    welcome_text = f"""✅ *Вы зарегистрированы!*

🏷️ *Ваш тег:* `{db_user['cr_tag']}`
🎮 *Имя в игре:* {db_user.get('username', 'Неизвестно')}
👑 *Роль в клане:* {db_user.get('clan_role', 'member')}

*Доступные команды:*
/stats - Ваша статистика
/clan - Информация о клане
/chests - Ваши сундуки
/battles - Ваши бои

Используйте кнопки ниже для быстрого доступа👇"""
                else:
                    welcome_text = f"""🎮 *Clash Royale Clan Bot*

👋 *Привет, {user.first_name}!*

Я помогу управлять вашим кланом в Clash Royale.

*Для начала работы:*
1. Привяжите ваш тег CR
2. Ваш никнейм автоматически обновится в чате
3. Получите доступ ко всем функциям

Нажмите '📝 Регистрация' для начала👇"""
                
                update.message.reply_text(
                    welcome_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=self.get_personal_menu_keyboard()
                )
    
    def help_command(self, update: Update, context: CallbackContext):
        help_text = """🎮 *Доступные команды*

*Основные:*
/start - Начало работы
/register - Привязать ваш тег
/stats - Ваша статистика
/clan - Информация о клане
/sync_me - Синхронизировать мои данные
/help - Эта справка

*Для группового чата:*
/war - Текущая война
/attacks - Статус атак в войне
/top - Топ игроков клана
/inactive - Неактивные игроки
/rules - Правила клана
/warlog - История войн клана
/river - Текущая речная гонка
/tournaments <имя> - Поиск турниров
/rankings - Глобальные рейтинги кланов

*Управление никнеймом:*
/nickname - Обновить свой никнейм
/update_nicknames - Обновить все никнеймы (админы)
/nickname_format - Изменить формат (админы)
/sync_roles - Синхронизировать роли (админы)

*Для админов:*
/admin - Панель администратора
/mass_promote - Назначить роли всем пользователям
/check_missing_roles - Проверить отсутствующие роли
/fix_user - Исправить роль конкретного пользователя
/kick #тег - Исключить игрока
/warn #тег - Предупредить игрока
/remind - Напомнить о войне
/settings - Настройки чата
/river_check - Ручная проверка речной гонки

*Дополнительно:*
/chests - Ваши сундуки
/battles - История боев
/members - Список участников
/donations - Статистика донатов"""
        
        keyboard = [
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
            [InlineKeyboardButton("📱 Кнопки управления", callback_data="show_buttons")]
        ]
        
        update.message.reply_text(
            help_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ============ REGISTRATION ============
    
    def register(self, update: Update, context: CallbackContext):
        """Универсальная команда регистрации"""
        user = update.effective_user
        
        if self.is_group_chat(update):
            # В группе - отправляем в личный чат
            update.message.reply_text(
                f"👋 {user.first_name},\n\n"
                f"📝 *Регистрация в боте*\n\n"
                f"Для регистрации напишите мне в личном сообщении:\n"
                f"1. Начните чат с @{self.bot_username}\n"
                f"2. Используйте команду `/register #ВАШ_ТЕГ`\n\n"
                f"ℹ️ *Ваш никнейм автоматически обновится в этой группе!*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    "📩 Написать в личку", 
                    url=f"https://t.me/{self.bot_username}?start=register"
                )]])
            )
        else:
            # В личном чате - быстрая регистрация
            self.quick_register(update, context)
    
    def quick_register(self, update: Update, context: CallbackContext):
        """Быстрая регистрация в личном чате"""
        user_id = update.effective_user.id
        user = update.effective_user
        
        if not context.args:
            keyboard = [
                [InlineKeyboardButton("❓ Где найти тег?", callback_data="find_tag_help")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            
            update.message.reply_text(
                "📝 *Быстрая регистрация*\n\n"
                "Использование: `/register #ВАШ_ТЕГ`\n"
                "Пример: `/register #2P0Y8C82U`\n\n"
                "ℹ️ *После регистрации ваш никнейм автоматически обновится в группе клана!*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        player_tag = context.args[0].strip()
        
        if not player_tag.startswith('#'):
            update.message.reply_text(
                "❌ *Ошибка:* Тег должен начинаться с символа `#`\n"
                "Пример правильного тега: `#2P0Y8C82U`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        update.message.reply_text("⏳ Проверяю ваш тег и обновляю никнейм...")
        
        player_data = api.get_player_info(player_tag)
        
        if not player_data:
            update.message.reply_text(
                f"❌ *Игрок не найден*\n\n"
                f"Тег `{player_tag}` не существует или неверен.\n"
                "Проверьте правильность тега и попробуйте еще раз.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Проверяем, есть ли уже такой тег
        existing_user = db.get_user_by_cr_tag(player_tag)
        if existing_user and existing_user['telegram_id'] != user_id:
            update.message.reply_text(
                f"❌ *Тег уже привязан*\n\n"
                f"Тег `{player_tag}` уже привязан к другому пользователю.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # ========== АВТОМАТИЧЕСКОЕ ОБНОВЛЕНИЕ НИКНЕЙМА И НАЗНАЧЕНИЕ ПРАВ ==========
        admin_promoted = False
        nickname_result = ""
        
        if Config.GROUP_CHAT_ID and Config.AUTO_NICKNAME_ENABLED:
            try:
                # Получаем роль игрока
                current_role = nickname_manager.get_clan_role(player_tag)
                if not current_role:
                    current_role = 'member'
                
                player_name = player_data.get('name', '')
                if player_name:
                    # Назначаем права администратора
                    success, result = self.promote_to_admin(
                        context, 
                        Config.GROUP_CHAT_ID, 
                        user_id, 
                        player_name, 
                        current_role
                    )
                    
                    if success:
                        admin_promoted = True
                        if result:
                            nickname_result = f"📝 *Роль установлена:* {result}"
                        else:
                            nickname_result = f"✅ *Права администратора назначены*"
                    else:
                        nickname_result = f"⚠️ *Ошибка назначения прав:* {result}"
                else:
                    nickname_result = "⚠️ *Никнейм:* Имя игрока не найдено"
                    
            except Exception as e:
                logger.error(f"Failed to auto-update nickname: {e}")
                nickname_result = f"⚠️ *Никнейм не обновлен:* {str(e)}"
        else:
            nickname_result = "ℹ️ *Никнейм:* Автообновление отключено в настройках"
        # ======================================================
        
        # Регистрируем пользователя в БД
        success = db.register_user(
            telegram_id=user_id,
            cr_tag=player_tag,
            username=user.username
        )
        
        if success:
            player_name = player_data.get('name', 'Неизвестно')
            player_trophies = player_data.get('trophies', 0)
            player_level = player_data.get('expLevel', 1)
            
            # Сохраняем имя и роль в БД
            current_role = nickname_manager.get_clan_role(player_tag) or 'member'
            db.update_user_nickname(user_id, player_name, current_role)
            
            keyboard = [
                [InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats")],
                [InlineKeyboardButton("🏰 Инфо о клане", callback_data="my_clan")],
                [InlineKeyboardButton("🔄 Синхронизировать", callback_data="sync_me")]
            ]
            
            success_message = f"✅ *Регистрация успешна!*\n\n"
            success_message += f"🎮 *Игрок:* {player_name}\n"
            success_message += f"🏷️ *Тег:* `{player_tag}`\n"
            success_message += f"👑 *Роль:* {current_role}\n"
            success_message += f"🏆 *Трофеи:* {player_trophies:,}\n"
            success_message += f"⭐ *Уровень:* {player_level}\n\n"
            success_message += nickname_result + "\n\n"
            
            if admin_promoted:
                success_message += "🔧 *Теперь у вас есть минимальные права администратора в группе клана!*\n\n"
            
            success_message += "Теперь вы можете использовать все функции бота!"
            
            update.message.reply_text(
                success_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # Уведомление в группу (если настроено)
            if Config.GROUP_CHAT_ID:
                try:
                    group_message = f"🎉 *Новая регистрация!*\n\n"
                    group_message += f"Игрок *{player_name}* зарегистрировался в боте!\n"
                    group_message += f"🏆 Трофеи: {player_trophies:,}\n"
                    
                    if admin_promoted:
                        group_message += f"✅ Права администратора назначены!"
                    else:
                        group_message += f"📝 Используйте `/nickname` чтобы обновить роль"
                    
                    context.bot.send_message(
                        chat_id=Config.GROUP_CHAT_ID,
                        text=group_message,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"Failed to send group notification: {e}")
        else:
            update.message.reply_text(
                "❌ *Ошибка регистрации*\n\n"
                "Не удалось завершить регистрацию. Попробуйте позже.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    def start_detailed_registration(self, update: Update, context: CallbackContext):
        """Детальная регистрация через conversation (для личного чата)"""
        if self.is_group_chat(update):
            update.message.reply_text(
                "📝 Регистрация доступна только в личном чате с ботом.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END
        
        update.message.reply_text(
            "📝 *Детальная регистрация*\n\n"
            "Отправьте мне ваш тег игрока.\n"
            "Пример: `#2P0Y8C82U`\n\n"
            "ℹ️ Тег можно найти в игре в вашем профиле.",
            parse_mode=ParseMode.MARKDOWN
        )
        return REGISTER
    
    def get_player_tag(self, update: Update, context: CallbackContext):
        """Получение тега в conversation"""
        player_tag = update.message.text.strip()
        
        if not player_tag.startswith('#'):
            update.message.reply_text(
                "❌ Тег должен начинаться с символа `#`\n"
                "Пример: `#2P0Y8C82U`\n"
                "Попробуйте еще раз:",
                parse_mode=ParseMode.MARKDOWN
            )
            return REGISTER
        
        player_data = api.get_player_info(player_tag)
        
        if not player_data:
            update.message.reply_text(
                f"❌ Игрок с тегом `{player_tag}` не найден.\n"
                "Проверьте правильность тега и попробуйте еще раз:",
                parse_mode=ParseMode.MARKDOWN
            )
            return REGISTER
        
        context.user_data['player_tag'] = player_tag
        context.user_data['player_data'] = player_data
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, это я", callback_data="confirm_register"),
                InlineKeyboardButton("❌ Нет, другой тег", callback_data="cancel_register")
            ]
        ]
        
        update.message.reply_text(
            f"🔍 *Найден игрок:*\n\n"
            f"🎮 *Имя:* {player_data.get('name')}\n"
            f"🏆 *Трофеи:* {player_data.get('trophies'):,}\n"
            f"⭐ *Уровень:* {player_data.get('expLevel')}\n"
            f"🏷️ *Тег:* {player_tag}\n\n"
            "Это вы?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CONFIRM_TAG
    
    def confirm_registration(self, update: Update, context: CallbackContext):
        """Подтверждение регистрации"""
        query = update.callback_query
        query.answer()
        
        user_id = query.from_user.id
        player_tag = context.user_data.get('player_tag')
        player_data = context.user_data.get('player_data')
        
        if query.data == 'confirm_register':
            success = db.register_user(
                telegram_id=user_id,
                cr_tag=player_tag,
                username=query.from_user.username
            )
            
            if success:
                player_name = player_data.get('name', '')
                current_role = nickname_manager.get_clan_role(player_tag) or 'member'
                
                # Сохраняем имя и роль в БД
                db.update_user_nickname(user_id, player_name, current_role)
                
                # Пытаемся обновить роль в группе
                admin_promoted = False
                
                if Config.GROUP_CHAT_ID and Config.AUTO_NICKNAME_ENABLED and player_name:
                    try:
                        success, result = self.promote_to_admin(
                            context, 
                            Config.GROUP_CHAT_ID, 
                            user_id, 
                            player_name, 
                            current_role
                        )
                        admin_promoted = success
                    except Exception as e:
                        logger.error(f"Failed to update nickname in conversation: {e}")
                
                success_message = f"✅ *Регистрация успешна!*\n\n"
                success_message += f"Тег `{player_tag}` привязан к вашему аккаунту.\n"
                success_message += f"Добро пожаловать, *{player_name}*!\n\n"
                
                if admin_promoted:
                    success_message += f"✅ *Права администратора назначены в группе клана!*"
                else:
                    success_message += f"ℹ️ *Используйте `/nickname` чтобы обновить роль в группе*"
                
                query.edit_message_text(
                    success_message,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # Отправляем меню
                context.bot.send_message(
                    chat_id=user_id,
                    text="🎮 *Выберите действие:*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=self.get_personal_menu_keyboard()
                )
            else:
                query.edit_message_text("❌ Ошибка при регистрации")
        else:
            query.edit_message_text("🔄 Введите правильный тег:")
            return REGISTER
        
        return ConversationHandler.END
    
    def cancel_registration(self, update: Update, context: CallbackContext):
        update.message.reply_text("❌ Регистрация отменена.")
        return ConversationHandler.END
    
    # ============ SYNC ME COMMAND ============
    
    def sync_me(self, update: Update, context: CallbackContext):
        """Синхронизация данных пользователя с API"""
        user_id = update.effective_user.id
        db_user = db.get_user_by_telegram_id(user_id)
        
        if not db_user:
            update.message.reply_text(
                "❌ *Вы не зарегистрированы.*\n\n"
                "Используйте /register для привязки вашего тега.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        update.message.reply_text("🔄 Синхронизирую ваши данные с Clash Royale...")
        
        # Синхронизируем данные
        success, result = nickname_manager.sync_player_data(user_id, db_user['cr_tag'])
        
        if success:
            player_name = result['name']
            player_role = result['role']
            
            # Пытаемся обновить роль в группе
            role_updated = False
            role_message = ""
            
            if Config.GROUP_CHAT_ID and Config.AUTO_NICKNAME_ENABLED:
                try:
                    success, result_text = self.promote_to_admin(
                        context, 
                        Config.GROUP_CHAT_ID, 
                        user_id, 
                        player_name, 
                        player_role
                    )
                    role_updated = success
                    if role_updated:
                        role_message = f"\n✅ *Роль обновлена в группе:* {result_text}"
                    else:
                        role_message = f"\n⚠️ *Роль не обновлена:* {result_text}"
                except Exception as e:
                    logger.error(f"Failed to update role on sync: {e}")
                    role_message = f"\n⚠️ *Роль не обновлена:* Убедитесь что бот админ в группе"
            else:
                role_message = f"\nℹ️ *Автообновление роли отключено в настройках*"
            
            response = f"✅ *Данные синхронизированы!*\n\n"
            response += f"🎮 *Игрок:* {player_name}\n"
            response += f"👑 *Роль:* {player_role}\n"
            response += f"🏆 *Трофеи:* {result.get('trophies', 0):,}\n"
            response += f"⭐ *Уровень:* {result.get('level', 1)}\n"
            response += role_message
            
            update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        else:
            update.message.reply_text(
                f"❌ *Ошибка синхронизации:*\n\n{result}",
                parse_mode=ParseMode.MARKDOWN
            )
    
    # ============ MASS PROMOTION COMMANDS ============
    
    def mass_promote_users(self, update: Update, context: CallbackContext):
        """Массовое назначение ролей всем зарегистрированным пользователям"""
        user_id = update.effective_user.id
        
        # Проверяем права администратора
        if not self.is_admin(user_id):
            update.message.reply_text("❌ Только администраторы могут выполнять эту команду.")
            return
        
        if not Config.GROUP_CHAT_ID:
            update.message.reply_text(
                "❌ *Групповой чат не настроен.*\n\n"
                "Настройте GROUP_CHAT_ID в конфигурации.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        update.message.reply_text(
            "🔄 *Запускаю массовое назначение ролей...*\n\n"
            "Это может занять некоторое время. Пожалуйста, подождите.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Выполняем массовое назначение
        self._execute_mass_promote(
            context, 
            update.effective_chat.id, 
            None  # Нет query для команды
        )
    
    def mass_promote_callback(self, update: Update, context: CallbackContext):
        """Обработка массового назначения ролей из callback кнопки"""
        query = update.callback_query
        query.answer()
        
        user_id = query.from_user.id
        
        if not self.is_admin(user_id):
            query.answer("❌ Только администраторы могут выполнять эту команду.", show_alert=True)
            return
        
        if not Config.GROUP_CHAT_ID:
            query.edit_message_text(
                "❌ *Групповой чат не настроен.*\n\n"
                "Настройте GROUP_CHAT_ID в конфигурации.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Редактируем сообщение чтобы показать что начали
        query.edit_message_text(
            "🔄 *Запускаю массовое назначение ролей...*\n\n"
            "Это может занять некоторое время. Пожалуйста, подождите.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Выполняем массовое назначение
        self._execute_mass_promote(
            context, 
            query.message.chat_id, 
            query  # Передаем query для callback
        )
    
    def _execute_mass_promote(self, context: CallbackContext, chat_id: int, query=None):
        """Выполнение массового назначения ролей (общая логика)"""
        group_chat_id = Config.GROUP_CHAT_ID
        
        # Получаем всех зарегистрированных пользователей
        users = db.get_all_users()
        total_users = len(users)
        
        if total_users == 0:
            if query:
                query.edit_message_text("❌ Нет зарегистрированных пользователей.")
            else:
                context.bot.send_message(chat_id=chat_id, text="❌ Нет зарегистрированных пользователей.")
            return
        
        success_count = 0
        failed_count = 0
        results = []
        
        # Отправляем прогресс
        if query:
            # Редактируем сообщение callback
            try:
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=query.message.message_id,
                    text=f"⏳ *Начинаю обработку {total_users} пользователей...*\n\n"
                         f"✅ Успешно: 0\n"
                         f"❌ Ошибок: 0",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
        else:
            # Отправляем новое сообщение прогресса
            progress_message = context.bot.send_message(
                chat_id=chat_id,
                text=f"⏳ *Начинаю обработку {total_users} пользователей...*",
                parse_mode=ParseMode.MARKDOWN
            )
        
        for index, user in enumerate(users, 1):
            try:
                telegram_id = user['telegram_id']
                cr_tag = user.get('cr_tag')
                
                if not cr_tag:
                    results.append(f"❌ {index}. Нет тега: {user.get('username', 'Unknown')}")
                    failed_count += 1
                    continue
                
                # Обновляем прогресс каждые 5 пользователей
                if index % 5 == 0 or index == total_users:
                    try:
                        if query:
                            context.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=query.message.message_id,
                                text=f"⏳ *Обработка {index}/{total_users} пользователей...*\n\n"
                                     f"✅ Успешно: {success_count}\n"
                                     f"❌ Ошибок: {failed_count}",
                                parse_mode=ParseMode.MARKDOWN
                            )
                        else:
                            progress_message.edit_text(
                                f"⏳ *Обработка {index}/{total_users} пользователей...*\n"
                                f"✅ Успешно: {success_count}\n"
                                f"❌ Ошибок: {failed_count}",
                                parse_mode=ParseMode.MARKDOWN
                            )
                    except:
                        pass
                
                # 1. Получаем данные игрока
                player_data = api.get_player_info(cr_tag)
                if not player_data:
                    results.append(f"❌ {index}. Данные не найдены: {cr_tag}")
                    failed_count += 1
                    continue
                
                player_name = player_data.get('name', '')
                if not player_name:
                    results.append(f"❌ {index}. Нет имени: {cr_tag}")
                    failed_count += 1
                    continue
                
                # 2. Получаем роль в клане
                current_role = nickname_manager.get_clan_role(cr_tag) or 'member'
                
                # 3. Обновляем в БД
                db.update_user_nickname(telegram_id, player_name, current_role)
                
                # 4. Назначаем права администратора в группе с заголовком
                try:
                    success, result_text = self.promote_to_admin(
                        context,
                        group_chat_id,
                        telegram_id,
                        player_name,
                        current_role
                    )
                    
                    if success:
                        # Удаляем эмодзи из имени для результата
                        clean_name = self.remove_emojis(player_name)
                        results.append(f"✅ {index}. {clean_name} → {current_role}")
                        success_count += 1
                    else:
                        results.append(f"❌ {index}. {player_name} - {result_text[:50]}")
                        failed_count += 1
                        
                except Exception as e:
                    error_msg = str(e)
                    # Если пользователь не в группе
                    if "user not found" in error_msg.lower() or "chat not found" in error_msg.lower():
                        results.append(f"⚠️ {index}. {player_name} - не в группе")
                    else:
                        results.append(f"❌ {index}. {player_name} - ошибка: {error_msg[:50]}")
                    failed_count += 1
                    
            except Exception as e:
                results.append(f"❌ {index}. Общая ошибка: {str(e)[:50]}")
                failed_count += 1
        
        # Формируем итоговый отчет
        report = f"📊 *ОТЧЕТ О МАССОВОМ НАЗНАЧЕНИИ РОЛЕЙ*\n\n"
        report += f"👥 *Всего пользователей:* {total_users}\n"
        report += f"✅ *Успешно:* {success_count}\n"
        report += f"❌ *Ошибок:* {failed_count}\n"
        
        if total_users > 0:
            report += f"⚡ *Эффективность:* {success_count/total_users*100:.1f}%\n\n"
        else:
            report += "\n"
        
        # Показываем первые 10 результатов
        if results:
            report += "*Результаты (первые 10):*\n"
            for result in results[:10]:
                report += f"{result}\n"
            
            if len(results) > 10:
                report += f"\n... и еще {len(results) - 10} результатов"
        
        # Создаем файл с полным отчетом
        try:
            report_file_content = "Отчет о массовом назначении ролей\n"
            report_file_content += f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            report_file_content += f"Всего пользователей: {total_users}\n"
            report_file_content += f"Успешно: {success_count}\n"
            report_file_content += f"Ошибок: {failed_count}\n\n"
            report_file_content += "Детальные результаты:\n"
            report_file_content += "\n".join(results)
            
            # Отправляем отчет файлом
            report_file = io.BytesIO(report_file_content.encode('utf-8'))
            report_file.name = f"mass_promote_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            
            context.bot.send_document(
                chat_id=chat_id,
                document=report_file,
                caption="📎 Полный отчет о массовом назначении ролей"
            )
        except Exception as e:
            logger.error(f"Failed to create report file: {e}")
        
        # Отправляем сводный отчет
        if query:
            # Редактируем сообщение callback
            try:
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=query.message.message_id,
                    text=report,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Failed to edit message: {e}")
                context.bot.send_message(
                    chat_id=chat_id,
                    text=report,
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            # Отправляем новое сообщение
            context.bot.send_message(
                chat_id=chat_id,
                text=report,
                parse_mode=ParseMode.MARKDOWN
            )
    
    def fix_user_role(self, update: Update, context: CallbackContext):
        """Исправить роль конкретного пользователя"""
        user_id = update.effective_user.id
        
        if not context.args:
            update.message.reply_text(
                "🔧 *Исправление роли пользователя*\n\n"
                "Использование: `/fix_user #тег`\n\n"
                "Пример:\n"
                "• `/fix_user #2P0Y8C82U` - по тегу Clash Royale",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        identifier = context.args[0]
        
        if not Config.GROUP_CHAT_ID:
            update.message.reply_text("❌ Групповой чат не настроен.")
            return
        
        update.message.reply_text(f"🔍 Ищу пользователя `{identifier}`...")
        
        # Ищем по CR тегу
        if identifier.startswith('#'):
            cr_tag = identifier
            target_user = db.get_user_by_cr_tag(cr_tag)
            if not target_user:
                update.message.reply_text(f"❌ Пользователь с тегом {cr_tag} не найден в базе.")
                return
        else:
            update.message.reply_text("❌ Неверный формат. Используйте #ТЕГ")
            return
        
        # Исправляем роль
        self._fix_single_user_role(update, context, target_user)
    
    def _fix_single_user_role(self, update: Update, context: CallbackContext, user_data):
        """Исправление роли для одного пользователя"""
        telegram_id = user_data['telegram_id']
        cr_tag = user_data.get('cr_tag')
        current_username = user_data.get('username', 'Неизвестно')
        
        update.message.reply_text(f"🔄 Исправляю роль для пользователя {current_username}...")
        
        # Получаем данные игрока
        player_data = api.get_player_info(cr_tag)
        if not player_data:
            update.message.reply_text(f"❌ Не удалось получить данные игрока {cr_tag}")
            return
        
        player_name = player_data.get('name', '')
        if not player_name:
            update.message.reply_text(f"❌ У игрока {cr_tag} не указано имя")
            return
        
        # Получаем роль в клане
        current_role = nickname_manager.get_clan_role(cr_tag) or 'member'
        
        # Обновляем в БД
        db.update_user_nickname(telegram_id, player_name, current_role)
        
        try:
            # Назначаем права администратора
            success, result_text = self.promote_to_admin(
                context,
                Config.GROUP_CHAT_ID,
                telegram_id,
                player_name,
                current_role
            )
            
            if success:
                # Удаляем эмодзи из имени для отображения
                clean_name = self.remove_emojis(player_name)
                
                response = f"✅ *Роль успешно исправлена!*\n\n"
                response += f"🎮 *Игрок:* {clean_name}\n"
                response += f"🏷️ *Тег:* `{cr_tag}`\n"
                response += f"👑 *Роль в клане:* {current_role}\n"
                if result_text:
                    response += f"📝 *Заголовок в чате:* {result_text}\n"
                response += f"✅ *Права администратора назначены*"
                
                update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
            else:
                error_msg = result_text
                response = f"⚠️ *Частичный успех*\n\n"
                response += f"🎮 *Игрок:* {player_name}\n"
                response += f"👑 *Роль:* {current_role}\n\n"
                
                if "user not found" in error_msg.lower():
                    response += f"❌ *Пользователь не найден в группе*\n"
                    response += f"Попросите пользователя зайти в группу {Config.GROUP_CHAT_ID}"
                else:
                    response += f"❌ *Ошибка назначения прав:*\n{error_msg[:100]}"
                
                update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            error_msg = str(e)
            response = f"⚠️ *Ошибка*\n\n"
            response += f"🎮 *Игрок:* {player_name}\n"
            response += f"👑 *Роль:* {current_role}\n\n"
            
            if "user not found" in error_msg.lower():
                response += f"❌ *Пользователь не найден в группе*\n"
                response += f"Попросите пользователя зайти в группу {Config.GROUP_CHAT_ID}"
            else:
                response += f"❌ *Ошибка назначения прав:*\n{error_msg[:100]}"
            
            update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
    
    def check_missing_roles(self, update: Update, context: CallbackContext):
        """Проверка пользователей без назначенных ролей"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            update.message.reply_text("❌ Только администраторы могут выполнять эту команду.")
            return
        
        update.message.reply_text("🔍 Проверяю пользователей без назначенных ролей...")
        
        # Выполняем проверку
        self._execute_check_missing_roles(
            context, 
            update.effective_chat.id, 
            None  # Нет query для команды
        )
    
    def check_missing_roles_callback(self, update: Update, context: CallbackContext):
        """Проверка пользователей без назначенных ролей из callback кнопки"""
        query = update.callback_query
        query.answer()
        
        user_id = query.from_user.id
        
        if not self.is_admin(user_id):
            query.answer("❌ Только администраторы могут выполнять эту команду.", show_alert=True)
            return
        
        # Редактируем сообщение
        query.edit_message_text("🔍 Проверяю пользователей без назначенных ролей...")
        
        # Выполняем проверку
        self._execute_check_missing_roles(
            context, 
            query.message.chat_id, 
            query  # Передаем query для callback
        )
    
    def _execute_check_missing_roles(self, context: CallbackContext, chat_id: int, query=None):
        """Выполнение проверки отсутствующих ролей"""
        users = db.get_all_users()
        
        if not users:
            if query:
                query.edit_message_text("❌ Нет зарегистрированных пользователей.")
            else:
                context.bot.send_message(chat_id=chat_id, text="❌ Нет зарегистрированных пользователей.")
            return
        
        users_without_roles = []
        users_without_group = []
        users_ok = []
        
        for user in users:
            telegram_id = user['telegram_id']
            cr_tag = user.get('cr_tag')
            
            if not cr_tag:
                continue
            
            # Проверяем, есть ли пользователь в группе
            try:
                chat_member = context.bot.get_chat_member(Config.GROUP_CHAT_ID, telegram_id)
                in_group = chat_member.status != 'left' and chat_member.status != 'kicked'
            except:
                in_group = False
            
            if not in_group:
                users_without_group.append(user)
                continue
            
            # Проверяем, есть ли роль (админские права)
            try:
                chat_member = context.bot.get_chat_member(Config.GROUP_CHAT_ID, telegram_id)
                if chat_member.status not in ['administrator', 'creator']:
                    users_without_roles.append(user)
                else:
                    users_ok.append(user)
            except:
                users_without_roles.append(user)
        
        # Формируем отчет
        report = f"📊 *ПРОВЕРКА НАЗНАЧЕННЫХ РОЛЕЙ*\n\n"
        report += f"👥 Всего зарегистрировано: {len(users)}\n"
        report += f"✅ С ролью: {len(users_ok)}\n"
        report += f"❌ Без роли: {len(users_without_roles)}\n"
        report += f"⚠️ Не в группе: {len(users_without_group)}\n\n"
        
        if users_without_roles:
            report += "*Пользователи без роли:*\n"
            for i, user in enumerate(users_without_roles[:5], 1):
                # Удаляем эмодзи из имени для отображения
                clean_name = self.remove_emojis(user.get('username', 'Неизвестно'))
                report += f"{i}. {clean_name} ({user.get('cr_tag')})\n"
            
            if len(users_without_roles) > 5:
                report += f"... и еще {len(users_without_roles) - 5} пользователей\n"
        
        # Отправляем отчет
        if query:
            # Редактируем сообщение callback
            try:
                keyboard = [
                    [InlineKeyboardButton("🔄 Назначить роли всем", callback_data="mass_promote")]
                ] if users_without_roles else None
                
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=query.message.message_id,
                    text=report,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )
            except Exception as e:
                logger.error(f"Failed to edit message: {e}")
        else:
            # Отправляем новое сообщение
            keyboard = [
                [InlineKeyboardButton("🔄 Назначить роли всем", callback_data="mass_promote")]
            ] if users_without_roles else None
            
            context.bot.send_message(
                chat_id=chat_id,
                text=report,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
            )
    
    # ============ PLAYER STATS ============
    
    def stats(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        db_user = db.get_user_by_telegram_id(user_id)
        
        if not db_user:
            keyboard = [
                [InlineKeyboardButton("📝 Зарегистрироваться", callback_data="register_now")],
                [InlineKeyboardButton("❓ Помощь", callback_data="help_menu")]
            ]
            
            update.message.reply_text(
                "❌ *Вы не зарегистрированы.*\n\n"
                "Используйте /register для привязки вашего тега.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        player_data = api.get_player_info(db_user['cr_tag'])
        
        if not player_data:
            update.message.reply_text("❌ Не удалось получить данные игрока.")
            return
        
        stats_text = api.format_player_stats(player_data)
        
        keyboard = [
            [
                InlineKeyboardButton("🎁 Мои сундуки", callback_data="my_chests"),
                InlineKeyboardButton("⚔️ Мои бои", callback_data="my_battles")
            ],
            [
                InlineKeyboardButton("🔄 Синхронизировать", callback_data="sync_me"),
                InlineKeyboardButton("📝 Обновить роль", callback_data="update_nickname")
            ]
        ]
        
        update.message.reply_text(
            stats_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        db.update_user_activity(user_id)
    
    # ============ CLAN INFO ============
    
    def clan_info(self, update: Update, context: CallbackContext):
        clan_data = api.get_clan_info(Config.CLAN_TAG)
        
        if not clan_data:
            update.message.reply_text("❌ Не удалось получить информацию о клане.")
            return
        
        emoji = Config.EMOJI
        text = f"{emoji['clan']} *{clan_data.get('name')}*\n\n"
        text += f"🏷️ *Тег:* {clan_data.get('tag')}\n"
        text += f"👥 *Участников:* {clan_data.get('members')}/50\n"
        text += f"🎯 *Требуемые трофеи:* {clan_data.get('requiredTrophies'):,}\n"
        text += f"🏆 *Трофеи клана:* {clan_data.get('clanScore'):,}\n"
        text += f"⚔️ *Трофеи войн:* {clan_data.get('clanWarTrophies', 0):,}\n\n"
        text += f"📝 *Описание:*\n{clan_data.get('description', 'Нет описания')}\n"
        
        keyboard = [
            [
                InlineKeyboardButton("👥 Участники", callback_data="show_members"),
                InlineKeyboardButton("🏆 Топ игроков", callback_data="top_players")
            ],
            [
                InlineKeyboardButton("⚔️ Война", callback_data="war_info"),
                InlineKeyboardButton("📊 Донаты", callback_data="show_donations")
            ],
            [
                InlineKeyboardButton("🔄 Обновить", callback_data="refresh_clan"),
                InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
            ]
        ]
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    # ============ WAR FUNCTIONS (РЕЧНАЯ ГОНКА) ============
    
    def war_info(self, update: Update, context: CallbackContext):
        """Информация о текущей речной гонке"""
        # ИСПРАВЛЕНО: используем get_current_river_race вместо get_current_war
        river_race = api.get_current_river_race(Config.CLAN_TAG)
        
        if not river_race:
            update.message.reply_text("❌ Не удалось получить данные о речной гонке.")
            return
        
        state = river_race.get('state', 'unknown')
        period_type = river_race.get('periodType', 'UNKNOWN')
        
        # Логируем для отладки
        logger.info(f"River Race State: {state}, Period Type: {period_type}")
        
        # Проверяем разные состояния
        if state in ['CLAN_NOT_FOUND', 'ACCESS_DENIED']:
            update.message.reply_text(f"❌ Ошибка: {state}")
            return
            
        if state in ['FULL', 'ENDED', 'MATCHMAKING']:
            # Не активная гонка
            keyboard = [
                [InlineKeyboardButton("🔄 Проверить снова", callback_data="war_info")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
            
            status_text = {
                'FULL': "Гонка заполнена",
                'ENDED': "Гонка завершена",
                'MATCHMAKING': "Идет подбор противников"
            }.get(state, "Не активно")
            
            update.message.reply_text(
                f"⚔️ *РЕЧНАЯ ГОНКА*\n\n"
                f"*Статус:* {status_text}\n"
                f"Следующая гонка скоро начнется!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # Если мы здесь, значит клан в активной гонке
        clan_data = river_race.get('clan', {})
        clans_data = river_race.get('clans', [])
        
        # Собираем информацию о противниках
        opponents = [c for c in clans_data if c.get('tag') != clan_data.get('tag')]
        
        # В зависимости от типа периода
        if period_type == 'TRAINING':
            text = f"🏋️ *ТРЕНИРОВОЧНЫЙ ДЕНЬ*\n\n"
            text += f"*Наш клан:* {clan_data.get('name', 'Неизвестно')}\n"
            text += f"*Слава:* {clan_data.get('fame', 0):,}\n"
            text += f"*Очки ремонта:* {clan_data.get('repairPoints', 0):,}\n\n"
            text += "🎯 *Задача:* Тренируйтесь и готовьтесь к битвам!\n"
            
        elif period_type == 'WAR_DAY':
            text = f"⚔️ *ДЕНЬ БИТВЫ*\n\n"
            text += f"*Наш клан:* {clan_data.get('name', 'Неизвестно')}\n"
            text += f"*Слава:* {clan_data.get('fame', 0):,}\n"
            text += f"*Очки ремонта:* {clan_data.get('repairPoints', 0):,}\n\n"
            
            # Показываем противников
            if opponents:
                text += "*Противники:*\n"
                for i, opp in enumerate(opponents[:3], 1):
                    text += f"{i}. {opp.get('name', 'Неизвестно')} - {opp.get('fame', 0):,} славы\n"
            
            text += "\n🎯 *Задача:* Набирайте славу и атакуйте противников!\n"
            
        elif period_type == 'COLOSSEUM':
            text = f"🏟️ *КОЛИЗЕЙ*\n\n"
            text += f"*Наш клан:* {clan_data.get('name', 'Неизвестно')}\n"
            text += f"*Слава:* {clan_data.get('fame', 0):,}\n"
            text += f"*Очки ремонта:* {clan_data.get('repairPoints', 0):,}\n\n"
            text += "🔥 *Финальный этап!* Покажите всё, на что способны!\n"
            
        else:
            text = f"⚔️ *РЕЧНАЯ ГОНКА*\n\n"
            text += f"*Статус:* {state}\n"
            text += f"*Тип периода:* {period_type}\n"
            text += f"*Наш клан:* {clan_data.get('name', 'Неизвестно')}\n"
        
        # Добавляем информацию о участниках
        participants = clan_data.get('participants', [])
        if participants:
            active_players = sum(1 for p in participants if p.get('decksUsedToday', 0) > 0)
            text += f"\n👥 *Активных игроков:* {active_players}/{len(participants)}"
        
        # Добавляем таймеры
        collection_end = river_race.get('collectionEndTime')
        war_end = river_race.get('warEndTime')
        
        if collection_end:
            text += f"\n⏰ *До конца сбора:* {self._format_time_remaining(collection_end)}"
        
        update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=self.get_war_keyboard()
        )
    
    def war_attacks(self, update: Update, context: CallbackContext):
        """Статус атак в речной гонке"""
        # ИСПРАВЛЕНО: используем get_current_river_race вместо get_current_war
        river_race = api.get_current_river_race(Config.CLAN_TAG)
        
        if not river_race:
            update.message.reply_text("❌ Не удалось получить данные о гонке.")
            return
        
        clan_data = river_race.get('clan', {})
        participants = clan_data.get('participants', [])
        
        if not participants:
            update.message.reply_text("Нет данных об участниках гонки.")
            return
        
        # Сортируем по активности
        sorted_participants = sorted(
            participants,
            key=lambda x: (x.get('fame', 0), x.get('decksUsedToday', 0)),
            reverse=True
        )
        
        text = "🎯 *АТАКИ В РЕЧНОЙ ГОНКЕ*\n\n"
        
        active = []
        inactive = []
        
        for participant in sorted_participants[:15]:
            name = participant.get('name', 'Неизвестно')
            fame = participant.get('fame', 0)
            decks_today = participant.get('decksUsedToday', 0)
            total_decks = participant.get('decksUsed', 0)
            boat_attacks = participant.get('boatAttacks', 0)
            
            if decks_today > 0:
                active.append(f"✅ {name}: {fame:,} славы ({decks_today}/4 атак сегодня)")
            else:
                inactive.append(f"❌ {name}: {fame:,} славы (0 атак сегодня)")
        
        if active:
            text += "*Активные сегодня:*\n"
            text += "\n".join(active[:8])
            text += "\n\n"
        
        if inactive:
            text += "*Еще не атаковали:*\n"
            text += "\n".join(inactive[:8])
        
        if not inactive:
            text += "\n🎉 *ВСЕ ИГРОКИ АТАКОВАЛИ СЕГОДНЯ!* 🎉"
        
        # Общая статистика
        total_fame = sum(p.get('fame', 0) for p in participants)
        total_decks_today = sum(p.get('decksUsedToday', 0) for p in participants)
        total_players = len(participants)
        
        text += f"\n\n📊 *Общая статистика:*\n"
        text += f"• Игроков в гонке: {total_players}\n"
        text += f"• Всего славы: {total_fame:,}\n"
        text += f"• Атак сегодня: {total_decks_today}/{total_players * 4}\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="war_attacks")],
            [InlineKeyboardButton("⚔️ Инфо о гонке", callback_data="war_info")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    # ============ NICKNAME FUNCTIONS ============
    
    def update_nickname(self, update: Update, context: CallbackContext):
        """Обновление роли вручную"""
        user_id = update.effective_user.id
        
        if self.is_group_chat(update):
            chat_id = update.effective_chat.id
        elif Config.GROUP_CHAT_ID:
            chat_id = Config.GROUP_CHAT_ID
        else:
            update.message.reply_text(
                "❌ *Групповой чат не настроен.*\n\n"
                "Настройте GROUP_CHAT_ID в конфигурации.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        db_user = db.get_user_by_telegram_id(user_id)
        
        if not db_user or not db_user.get('cr_tag'):
            update.message.reply_text(
                "❌ Вы не зарегистрированы в боте.\n"
                "Используйте /register для привязки вашего тега."
            )
            return
        
        update.message.reply_text("⏳ Обновляю вашу роль...")
        
        # Получаем данные игрока
        player_data = api.get_player_info(db_user['cr_tag'])
        if not player_data:
            update.message.reply_text("❌ Не удалось получить данные игрока.")
            return
        
        player_name = player_data.get('name', '')
        if not player_name:
            update.message.reply_text("❌ Имя игрока не найдено.")
            return
        
        # Получаем роль в клане
        current_role = nickname_manager.get_clan_role(db_user['cr_tag']) or 'member'
        
        # Обновляем в БД
        db.update_user_nickname(user_id, player_name, current_role)
        
        # Назначаем права администратора
        success, result = self.promote_to_admin(
            context, 
            chat_id, 
            user_id, 
            player_name, 
            current_role
        )
        
        if success:
            update.message.reply_text(f"✅ *Роль обновлена!*\n\n{result}", parse_mode=ParseMode.MARKDOWN)
        else:
            update.message.reply_text(f"❌ *Ошибка обновления:*\n\n{result}", parse_mode=ParseMode.MARKDOWN)
    
    def update_all_nicknames(self, update: Update, context: CallbackContext):
        if not self.is_group_chat(update):
            if not Config.GROUP_CHAT_ID:
                update.message.reply_text("Эта команда работает только в групповом чате.")
                return
            chat_id = Config.GROUP_CHAT_ID
        else:
            chat_id = update.effective_chat.id
        
        user_id = update.effective_user.id
        if not self.is_admin(user_id):
            update.message.reply_text("❌ Только админы могут обновлять все роли.")
            return
        
        update.message.reply_text("⏳ Обновляю все роли в чате...")
        
        # Просто используем массовое назначение
        self._execute_mass_promote(context, chat_id, None)
    
    def set_nickname_format(self, update: Update, context: CallbackContext):
        if not self.is_group_chat(update):
            update.message.reply_text("Эта команда работает только в групповом чате.")
            return
        
        user_id = update.effective_user.id
        if not self.is_admin(user_id):
            update.message.reply_text("❌ Только админы могут изменять формат никнеймов.")
            return
        
        if not context.args:
            current_format = Config.NICKNAME_FORMAT
            examples = [
                "*Доступные переменные:*",
                "• `{emoji}` - эмодзи роли (👑, ⭐, 🔧, 🛡️, 🎮)",
                "• `{name}` - имя игрока",
                "• `{tag}` - тег игрока (например, #ABC123)",
                "• `{role}` - роль в клане (leader, coLeader, etc.)",
                "",
                f"*Текущий формат:* `{current_format}`",
                "",
                "*Примеры:*",
                "• `{emoji} {name}` → 👑 Игрок",
                "• `{name} {emoji}` → Игрок 👑",
                "• `[{role}] {name}` → [leader] Игрок",
                "• `{name} ({tag})` → Игрок (#ABC123)",
                "",
                "Использование: /nickname_format ваш_формат"
            ]
            
            update.message.reply_text("\n".join(examples), parse_mode=ParseMode.MARKDOWN)
            return
        
        new_format = ' '.join(context.args)
        
        if not any(var in new_format for var in ['{emoji}', '{name}']):
            update.message.reply_text("❌ Формат должен содержать {emoji} или {name}")
            return
        
        chat_id = update.effective_chat.id
        db.update_chat_setting(chat_id, 'nickname_format', new_format)
        
        update.message.reply_text(
            f"✅ Формат никнеймов обновлен: `{new_format}`",
            parse_mode=ParseMode.MARKDOWN
        )
    
    def sync_roles(self, update: Update, context: CallbackContext):
        if not self.is_group_chat(update):
            update.message.reply_text("Эта команда работает только в групповом чате.")
            return
        
        user_id = update.effective_user.id
        if not self.is_admin(user_id):
            update.message.reply_text("❌ Только админы могут синхронизировать роли.")
            return
        
        update.message.reply_text("⏳ Синхронизирую роли с кланом...")
        
        users = db.get_all_users()
        synced = 0
        
        for user in users:
            if user['cr_tag']:
                current_role = nickname_manager.get_clan_role(user['cr_tag'])
                if current_role and current_role != user.get('clan_role'):
                    db.update_user_nickname(user['telegram_id'], user['username'], current_role)
                    synced += 1
        
        update.message.reply_text(f"✅ Синхронизировано {synced} ролей!")
    
    # ============ ADMIN FUNCTIONS ============
    
    def admin_panel(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            update.message.reply_text("❌ У вас нет прав администратора.")
            return
        
        admin_text = "⚙️ *Панель администратора*\n\n"
        admin_text += "Используйте кнопки ниже для управления👇\n\n"
        
        stats = db.get_bot_stats()
        admin_text += f"📊 *Статистика бота:*\n"
        admin_text += f"• 👥 Пользователей: {stats.get('total_users', 0)}\n"
        admin_text += f"• 👑 Админов: {stats.get('admins', 0)}\n"
        admin_text += f"• ⚠️ Предупреждений: {stats.get('active_warnings', 0)}\n"
        
        update.message.reply_text(
            admin_text, 
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=self.get_admin_keyboard()
        )
    
    def kick_player(self, update: Update, context: CallbackContext):
        if not self.is_group_chat(update):
            update.message.reply_text("Эта команда работает только в групповом чате.")
            return
        
        user_id = update.effective_user.id
        if not self.is_admin(user_id):
            update.message.reply_text("❌ Только админы могут исключать игроков.")
            return
        
        if not context.args:
            update.message.reply_text(
                "👢 *Исключение игрока*\n\n"
                "Использование: `/kick #тег_игрока`\n"
                "Пример: `/kick #2P0Y8C82U`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        player_tag = context.args[0]
        
        if not player_tag.startswith('#'):
            update.message.reply_text("Пожалуйста, укажите тег игрока (начинается с #)")
            return
        
        player_info = api.get_player_info(player_tag)
        if not player_info:
            update.message.reply_text(f"❌ Игрок с тегом {player_tag} не найден.")
            return
        
        player_name = player_info.get('name')
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, исключить", callback_data=f"kick_confirm_{player_tag}"),
                InlineKeyboardButton("❌ Нет, отмена", callback_data="kick_cancel")
            ]
        ]
        
        update.message.reply_text(
            f"⚠️ *Подтверждение исключения*\n\n"
            f"Вы действительно хотите исключить игрока:\n"
            f"*Имя:* {player_name}\n"
            f"*Тег:* {player_tag}\n\n"
            f"Это действие нельзя отменить!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    def warn_player(self, update: Update, context: CallbackContext):
        if not self.is_group_chat(update):
            update.message.reply_text("Эта команда работает только в групповом чате.")
            return
        
        user_id = update.effective_user.id
        if not self.is_admin(user_id):
            update.message.reply_text("❌ Только админы могут предупреждать игроков.")
            return
        
        if not context.args:
            update.message.reply_text(
                "⚠️ *Предупреждение игроку*\n\n"
                "Использование: `/warn #тег причина`\n"
                "Пример: `/warn #2P0Y8C82U Не делает атаки в войне`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        player_tag = context.args[0]
        reason = ' '.join(context.args[1:]) if len(context.args) > 1 else "Нарушение правил"
        
        if not player_tag.startswith('#'):
            update.message.reply_text("Пожалуйста, укажите тег игрока (начинается с #)")
            return
        
        player_info = api.get_player_info(player_tag)
        if not player_info:
            update.message.reply_text(f"❌ Игрок с тегом {player_tag} не найден.")
            return
        
        player_name = player_info.get('name')
        admin_name = update.effective_user.first_name
        
        warning_text = (
            f"⚠️ *ПРЕДУПРЕЖДЕНИЕ ИГРОКУ*\n\n"
            f"*Игрок:* {player_name}\n"
            f"*Тег:* {player_tag}\n"
            f"*Причина:* {reason}\n"
            f"*От:* {admin_name}\n\n"
            f"Пожалуйста, исправьте ситуацию!"
        )
        
        update.message.reply_text(warning_text, parse_mode=ParseMode.MARKDOWN)
    
    def remind_war(self, update: Update, context: CallbackContext):
        if not self.is_group_chat(update):
            update.message.reply_text("Эта команда работает только в групповом чате.")
            return
        
        user_id = update.effective_user.id
        if not self.is_admin(user_id):
            update.message.reply_text("❌ Только админы могут отправлять напоминания.")
            return
        
        # ИСПРАВЛЕНО: используем get_current_river_race
        river_race = api.get_current_river_race(Config.CLAN_TAG)
        
        if not river_race:
            update.message.reply_text("❌ Не удалось получить данные о речной гонке.")
            return
        
        state = river_race.get('state', 'unknown')
        period_type = river_race.get('periodType', 'UNKNOWN')
        
        # Проверяем, активна ли гонка
        if state in ['FULL', 'ENDED', 'MATCHMAKING', 'CLAN_NOT_FOUND', 'ACCESS_DENIED']:
            update.message.reply_text("Сейчас нет активной речной гонки.")
            return
        
        reminder_text = """⚔️ *НАПОМИНАНИЕ О РЕЧНОЙ ГОНКЕ!*

Не забудьте сделать свои атаки в речной гонке!

🎯 Цель: максимальная слава для клана!
🔥 Мотивация: Давайте победим в гонке!

*Не забудьте:* 
1. Использовать все 4 атаки сегодня
2. Атаковать лодки противников
3. Набирать очки ремонта

Удачи в битве! 🏆"""
        
        # Добавляем информацию о периоде
        if period_type == 'TRAINING':
            reminder_text += "\n\n🏋️ *Сейчас тренировочный день - готовьтесь к битвам!*"
        elif period_type == 'WAR_DAY':
            reminder_text += "\n\n⚔️ *Сейчас день битвы - атакуйте противников!*"
        elif period_type == 'COLOSSEUM':
            reminder_text += "\n\n🏟️ *Сейчас КОЛИЗЕЙ - финальный этап!*"
        
        # Добавляем список неактивных
        clan_data = river_race.get('clan', {})
        participants = clan_data.get('participants', [])
        if participants:
            inactive = [p for p in participants if p.get('decksUsedToday', 0) == 0]
            if inactive:
                names = [p.get('name', 'Неизвестно') for p in inactive[:5]]
                reminder_text += f"\n\n🎯 *Еще не атаковали сегодня:*\n"
                reminder_text += "\n".join([f"• {name}" for name in names])
                if len(inactive) > 5:
                    reminder_text += f"\n• ... и еще {len(inactive) - 5} игроков"
        
        update.message.reply_text(reminder_text, parse_mode=ParseMode.MARKDOWN)
    
    def chat_settings(self, update: Update, context: CallbackContext):
        if not self.is_group_chat(update):
            update.message.reply_text("Настройки доступны только в групповом чате.")
            return
        
        user_id = update.effective_user.id
        if not self.is_admin(user_id):
            update.message.reply_text("❌ Только админы могут изменять настройки.")
            return
        
        chat_id = update.effective_chat.id
        chat_settings = db.get_chat_settings(chat_id)
        
        text = "⚙️ *НАСТРОЙКИ ЧАТА*\n\n"
        text += f"• Авто-исключение: {'✅ Вкл' if Config.AUTO_KICK_ENABLED else '❌ Выкл'}\n"
        text += f"• Напоминания о войне: {'✅ Вкл' if Config.WAR_REMINDER_ENABLED else '❌ Выкл'}\n"
        text += f"• Авто-роли: {'✅ Вкл' if Config.AUTO_NICKNAME_ENABLED else '❌ Выкл'}\n"
        text += f"• Формат никнеймов: `{Config.NICKNAME_FORMAT}`\n"
        
        keyboard = [
            [
                InlineKeyboardButton("🔧 Изменить настройки", callback_data="edit_settings"),
                InlineKeyboardButton("🔄 Сбросить", callback_data="reset_settings")
            ],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    # ============ UTILITY FUNCTIONS ============
    
    def top_players(self, update: Update, context: CallbackContext):
        clan_members = api.get_clan_members(Config.CLAN_TAG)
        
        if not clan_members:
            update.message.reply_text("❌ Не удалось получить список игроков")
            return
        
        sorted_members = sorted(clan_members, key=lambda x: x.get('trophies', 0), reverse=True)
        
        text = "🏆 *Топ игроков клана*\n\n"
        
        for i, member in enumerate(sorted_members[:15], 1):
            role_emoji = {
                'leader': '👑',
                'coLeader': '⭐',
                'admin': '🔧',
                'elder': '🛡️',
                'member': '🎮'
            }.get(member.get('role', 'member'), '🎮')
            
            db_user = db.get_user_by_cr_tag(member.get('tag'))
            bot_user = " 🤖" if db_user else ""
            
            text += f"{i}. {role_emoji} *{member.get('name')}*{bot_user}\n"
            text += f"   🏆 {member.get('trophies', 0):,} | "
            text += f"🎁 {member.get('donations', 0):,} | "
            text += f"🛡️ Ур. {member.get('expLevel', 0)}\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="top_players")],
            [InlineKeyboardButton("👥 Все участники", callback_data="show_members")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    def check_inactive(self, update: Update, context: CallbackContext):
        if self.is_group_chat(update):
            user_id = update.effective_user.id
            if not self.is_admin(user_id):
                update.message.reply_text("❌ Только админы могут проверять неактивных в группе.")
                return
        
        update.message.reply_text("⏳ Проверяю активность игроков...")
        
        clan_members = api.get_clan_members(Config.CLAN_TAG)
        if not clan_members:
            update.message.reply_text("❌ Не удалось получить список игроков")
            return
        
        inactive_threshold = Config.KICK_AFTER_DAYS
        inactive_players = []
        
        current_time = datetime.now()
        
        for member in clan_members:
            last_seen = member.get('lastSeen')
            if last_seen:
                try:
                    last_seen_date = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                    days_inactive = (current_time - last_seen_date).days
                    
                    if days_inactive >= inactive_threshold:
                        role = member.get('role', 'member')
                        if role not in ['leader', 'coLeader']:
                            inactive_players.append({
                                'name': member.get('name'),
                                'tag': member.get('tag'),
                                'days': days_inactive,
                                'role': role
                            })
                except:
                    continue
        
        report = "⚠️ *ПРОВЕРКА АКТИВНОСТИ*\n\n"
        
        if inactive_players:
            report += f"❌ *Неактивные (> {inactive_threshold} дней):* {len(inactive_players)}\n"
            for i, player in enumerate(inactive_players[:5], 1):
                report += f"{i}. {player['name']} ({player['days']} дн.)\n"
            
            if len(inactive_players) > 5:
                report += f"... и еще {len(inactive_players) - 5} игроков\n"
            
            if self.is_group_chat(update) and self.is_admin(update.effective_user.id):
                keyboard = [
                    [InlineKeyboardButton("👢 Исключить неактивных", callback_data="kick_inactive")],
                    [InlineKeyboardButton("⚠️ Предупредить", callback_data="warn_inactive")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
            else:
                reply_markup = None
        else:
            report += "✅ Все игроки активны! 🎉\n"
            reply_markup = None
        
        report += f"\n👥 Всего участников: {len(clan_members)}"
        
        update.message.reply_text(
            report,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    def show_rules(self, update: Update, context: CallbackContext):
        if not self.is_group_chat(update):
            update.message.reply_text("Правила клана доступны только в групповом чате.")
            return
        
        rules_text = """📜 *ПРАВИЛА КЛАНА*

1. 🎮 *Активность*
   - Минимум 3 дня в неделю
   - Участие в речных гонках обязательно

2. ⚔️ *Речные гонки*
   - Делать все 4 атаки в день
   - Кооперироваться с сокланамими
   - Атаковать лодки противников

3. 🎁 *Донаты*
   - Минимум 100 донатов в неделю
   - Просите нужные вам карты

4. 👥 *Общение*
   - Уважайте других игроков
   - Не спамьте в чате
   - Помогайте новичкам

5. ⚠️ *Наказания*
   - 1 предупреждение за нарушение
   - Исключение при повторных нарушениях
   - Исключение за неактивность (>14 дней)"""
        
        keyboard = [
            [InlineKeyboardButton("✅ Согласен", callback_data="agree_rules")],
            [InlineKeyboardButton("❓ Вопросы", callback_data="ask_about_rules")]
        ]
        
        update.message.reply_text(rules_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    def show_chests(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        db_user = db.get_user_by_telegram_id(user_id)
        
        if not db_user:
            update.message.reply_text(
                "❌ *Вы не зарегистрированы.*\n\n"
                "Используйте /register для привязки вашего тега.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        chests = api.get_player_chests(db_user['cr_tag'])
        
        if not chests or 'items' not in chests:
            update.message.reply_text("❌ Не удалось получить информацию о сундуках.")
            return
        
        chests_text = f"🎁 *Ваши предстоящие сундуки:*\n\n"
        
        for i, chest in enumerate(chests['items'][:10], 1):
            name = chest.get('name', 'Неизвестный сундук')
            index = chest.get('index', 0)
            
            emoji = {
                'Silver': '🥈',
                'Gold': '🥇',
                'Giant': '💎',
                'Magical': '✨',
                'Epic': '⚡',
                'Legendary': '👑',
                'Mega Lightning': '⚡⚡',
                'Crown': '👑'
            }.get(name.split()[0], '🎁')
            
            chests_text += f"{i}. {emoji} {name}\n"
            chests_text += f"   ⏳ Через *{index}* боев\n\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="my_chests")],
            [InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        update.message.reply_text(chests_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    def show_battles(self, update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        db_user = db.get_user_by_telegram_id(user_id)
        
        if not db_user:
            update.message.reply_text(
                "❌ *Вы не зарегистрированы.*\n\n"
                "Используйте /register для привязки вашего тега.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        battles = api.get_battle_log(db_user['cr_tag'], limit=8)
        
        if not battles:
            update.message.reply_text("❌ Не удалось получить историю боев.")
            return
        
        battles_text = f"⚔️ *Последние бои:*\n\n"
        
        for i, battle in enumerate(battles, 1):
            mode = battle.get('gameMode', {}).get('name', 'Неизвестно')
            battle_time = battle.get('battleTime', '')[:16].replace('T', ' ')
            
            team = battle.get('team', [{}])
            opponent = battle.get('opponent', [{}])
            
            team_crowns = team[0].get('crowns', 0) if team else 0
            opp_crowns = opponent[0].get('crowns', 0) if opponent else 0
            
            if team_crowns > opp_crowns:
                result = "✅ Победа"
            elif team_crowns < opp_crowns:
                result = "❌ Поражение"
            else:
                result = "🤝 Ничья"
            
            battles_text += f"{i}. *{mode}*\n"
            battles_text += f"   {result} {team_crowns}-{opp_crowns}\n"
            battles_text += f"   🕐 {battle_time}\n\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="my_battles")],
            [InlineKeyboardButton("🎁 Мои сундуки", callback_data="my_chests")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        update.message.reply_text(battles_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    def show_members(self, update: Update, context: CallbackContext):
        """Показать всех участников клана"""
        clan_members = api.get_clan_members(Config.CLAN_TAG)
        
        if not clan_members:
            update.message.reply_text("❌ Не удалось получить список участников.")
            return
        
        text = f"👥 *Участники клана ({len(clan_members)}/50)*\n\n"
        
        for i, member in enumerate(clan_members[:20], 1):
            role_emoji = {
                'leader': '👑',
                'coLeader': '⭐',
                'admin': '🔧',
                'elder': '🛡️',
                'member': '🎮'
            }.get(member.get('role', 'member'), '🎮')
            
            text += f"{i}. {role_emoji} {member.get('name')}\n"
            text += f"   🏆 {member.get('trophies', 0):,} | "
            text += f"🎁 {member.get('donations', 0):,}\n"
        
        if len(clan_members) > 20:
            text += f"\n... и еще {len(clan_members) - 20} участников"
        
        keyboard = [
            [InlineKeyboardButton("🏆 Топ игроков", callback_data="top_players")],
            [InlineKeyboardButton("📊 Статистика", callback_data="clan_stats")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="show_members")]
        ]
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    def show_donations(self, update: Update, context: CallbackContext):
        """Показать статистику донатов"""
        clan_members = api.get_clan_members(Config.CLAN_TAG)
        
        if not clan_members:
            update.message.reply_text("❌ Не удалось получить статистику.")
            return
        
        # Сортируем по донатам
        sorted_members = sorted(clan_members, key=lambda x: x.get('donations', 0), reverse=True)
        
        text = "🎁 *ТОП ДОНОТЕРОВ КЛАНА*\n\n"
        
        total_donations = 0
        for i, member in enumerate(sorted_members[:10], 1):
            donations = member.get('donations', 0)
            total_donations += donations
            
            text += f"{i}. {member.get('name')}\n"
            text += f"   🎁 {donations:,} карт\n"
        
        text += f"\n📊 *Общая статистика:*\n"
        text += f"• Всего донатов: {total_donations:,}\n"
        text += f"• Среднее на игрока: {total_donations // len(clan_members) if clan_members else 0:,}\n"
        
        keyboard = [
            [InlineKeyboardButton("👥 Все участники", callback_data="show_members")],
            [InlineKeyboardButton("🏆 Топ по трофеям", callback_data="top_players")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="show_donations")]
        ]
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    # ============ MESSAGE HANDLERS ============
    
    def welcome_new_member(self, update: Update, context: CallbackContext):
        if not self.is_group_chat(update):
            return
        
        new_members = update.message.new_chat_members
        for member in new_members:
            if member.id == context.bot.id:
                # Бота добавили в группу
                update.message.reply_text(
                    "🤖 *Бот активирован!*\n\n"
                    "Спасибо за добавление! Я помогу управлять вашим кланом.\n\n"
                    "🔧 *Для начала работы:*\n"
                    "1. Дайте мне права администратора\n"
                    "2. Настройте GROUP_CHAT_ID в .env\n"
                    "3. Используйте /start для начала работы",
                    parse_mode=ParseMode.MARKDOWN
                )
                continue
            
            db_user = db.get_user_by_telegram_id(member.id)
            
            welcome_text = f"👋 *Добро пожаловать в чат клана, {member.first_name}!*\n\n"
            
            if db_user and db_user.get('cr_tag'):
                player_data = api.get_player_info(db_user['cr_tag'])
                if player_data:
                    player_name = player_data.get('name', '')
                    current_role = nickname_manager.get_clan_role(db_user['cr_tag']) or 'member'
                    
                    welcome_text += f"🎮 *Ваш аккаунт Clash Royale:* {player_name}\n"
                    welcome_text += "✅ Вы уже зарегистрированы в боте!\n"
                    
                    # Пытаемся назначить права администратора
                    try:
                        success, result = self.promote_to_admin(
                            context,
                            update.effective_chat.id,
                            member.id,
                            player_name,
                            current_role
                        )
                        
                        if success:
                            if result:
                                welcome_text += f"📝 *Роль назначена:* {result}\n"
                            welcome_text += "👑 *Права администратора назначены*"
                        else:
                            welcome_text += f"⚠️ *Не удалось назначить права:* {result}"
                    except Exception as e:
                        logger.error(f"Failed to auto-update role for new member: {e}")
                        welcome_text += f"⚠️ *Не удалось обновить роль:* {str(e)[:50]}"
                else:
                    welcome_text += "❌ *Не удалось получить данные вашего аккаунта*\n"
            else:
                welcome_text += "📝 *Чтобы получить роль в чате:*\n"
                welcome_text += "1. Привяжите свой тег через /register\n"
                welcome_text += "2. Ваша роль автоматически обновится\n\n"
            
            welcome_text += "\n🏰 *Основные команды:*\n"
            welcome_text += "/war - Речная гонка\n"
            welcome_text += "/clan - Информация о клане\n"
            welcome_text += "/rules - Правила клана\n"
            
            update.message.reply_text(
                welcome_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=self.get_group_welcome_keyboard()
            )
    
    def handle_text_message(self, update: Update, context: CallbackContext):
        text = update.message.text
        
        if text == '📊 Моя статистика':
            self.stats(update, context)
        elif text == '🏰 Информация о клане':
            self.clan_info(update, context)
        elif text == '🎁 Мои сундуки':
            self.show_chests(update, context)
        elif text == '⚔️ История боев':
            self.show_battles(update, context)
        elif text == '❓ Помощь':
            self.help_command(update, context)
        elif text == '⚔️ Война':
            self.war_info(update, context)
        elif text == '🎯 Атаки':
            self.war_attacks(update, context)
        elif text == '👥 Топ игроков':
            self.top_players(update, context)
        elif text == '⚠️ Неактивные':
            self.check_inactive(update, context)
        elif text == '📜 Правила':
            self.show_rules(update, context)
    
    # ============ CALLBACK HANDLERS ============
    
    def button_handler(self, update: Update, context: CallbackContext):
        query = update.callback_query
        query.answer()
        
        data = query.data
        
        # Основные команды
        if data == 'main_menu':
            self.start_callback(update, context)
        elif data == 'help_menu':
            self.help_callback(update, context)
        elif data == 'register_now':
            self.register_callback(update, context)
        elif data == 'sync_me':
            self.sync_me_callback(update, context)
        
        # Статистика
        elif data == 'my_stats':
            self.stats_callback(update, context)
        elif data == 'my_chests':
            self.show_chests_callback(update, context)
        elif data == 'my_battles':
            self.show_battles_callback(update, context)
        elif data == 'refresh_stats':
            query.edit_message_text("🔄 Обновляю статистику...")
            self.stats_callback(update, context)
        
        # Клан
        elif data == 'my_clan':
            self.clan_info_callback(update, context)
        elif data == 'clan_info':
            self.clan_info_callback(update, context)
        elif data == 'refresh_clan':
            query.edit_message_text("🔄 Обновляю информацию о клане...")
            self.clan_info_callback(update, context)
        elif data == 'show_members':
            self.show_members_callback(update, context)
        elif data == 'show_donations':
            self.show_donations_callback(update, context)
        elif data == 'clan_stats':
            query.edit_message_text("📊 *Статистика клана*\n\nЭта функция в разработке...", parse_mode=ParseMode.MARKDOWN)
        
        # Война (River Race)
        elif data == 'war_info':
            self.war_info_callback(update, context)
        elif data == 'war_attacks':
            self.war_attacks_callback(update, context)
        elif data == 'refresh_war':
            query.edit_message_text("🔄 Обновляю информацию о гонке...")
            self.war_info_callback(update, context)
        elif data == 'remind_war':
            self.remind_war_callback(update, context)
        elif data == 'river_race_ranking':
            query.edit_message_text("📊 *РЕЙТИНГ КЛАНОВ*\n\nЭта функция в разработке...", parse_mode=ParseMode.MARKDOWN)
        elif data == 'river_race_participants':
            query.edit_message_text("👥 *УЧАСТНИКИ*\n\nЭта функция в разработке...", parse_mode=ParseMode.MARKDOWN)
        elif data == 'river_race_timer':
            query.edit_message_text("⏰ *ТАЙМЕРЫ*\n\nЭта функция в разработке...", parse_mode=ParseMode.MARKDOWN)
        
        # Топы
        elif data == 'top_players':
            self.top_players_callback(update, context)
        elif data == 'top_clan':
            self.top_players_callback(update, context)
        
        # Неактивные
        elif data == 'check_inactive':
            self.check_inactive_callback(update, context)
        elif data == 'kick_inactive':
            query.edit_message_text(
                "Для массового исключения используйте команду:\n"
                "/kick #тег_игрока\n\n"
                "Или исключайте игроков по одному."
            )
        elif data == 'warn_inactive':
            query.edit_message_text(
                "Для предупреждения используйте команду:\n"
                "/warn #тег_игрока причина\n\n"
                "Пример: /warn #2P0Y8C82U Неактивен 14 дней"
            )
        
        # Правила
        elif data == 'show_rules':
            self.show_rules_callback(update, context)
        elif data == 'agree_rules':
            query.edit_message_text("✅ Спасибо за согласие с правилами!")
        elif data == 'ask_about_rules':
            query.edit_message_text("❓ *Вопросы по правилам*\n\nЗадайте вопросы админам клана.", parse_mode=ParseMode.MARKDOWN)
        
        # Админ
        elif data.startswith('admin_'):
            admin_action = data.replace('admin_', '')
            if admin_action == 'kick':
                query.edit_message_text("👢 *Исключение игрока*\n\nИспользуйте команду: /kick #тег_игрока", parse_mode=ParseMode.MARKDOWN)
            elif admin_action == 'warn':
                query.edit_message_text("⚠️ *Предупреждение игрока*\n\nИспользуйте команду: /warn #тег_игрока причина", parse_mode=ParseMode.MARKDOWN)
            elif admin_action == 'update_nicks':
                self.update_all_nicknames_callback(update, context)
            elif admin_action == 'sync_roles':
                self.sync_roles_callback(update, context)
            elif admin_action == 'remind':
                self.remind_war_callback(update, context)
            elif admin_action == 'report':
                query.edit_message_text("📊 *Отчет*\n\nЭта функция в разработке...", parse_mode=ParseMode.MARKDOWN)
            elif admin_action == 'settings':
                self.chat_settings_callback(update, context)
            elif admin_action == 'stats':
                self.admin_panel_callback(update, context)
            elif admin_action == 'river_check':
                self.manual_river_check_callback(update, context)
        
        # Регистрация
        elif data == 'find_tag_help':
            query.edit_message_text(
                "❓ *Где найти тег?*\n\n"
                "1. Откройте Clash Royale\n"
                "2. Нажмите на свой профиль\n"
                "3. Тег находится под вашим именем\n"
                "4. Он начинается с символа #\n\n"
                "*Пример:* `#2P0Y8C82U`",
                parse_mode=ParseMode.MARKDOWN
            )
        elif data == 'update_nickname':
            self.update_nickname_callback(update, context)
        
        # Массовое назначение ролей
        elif data == 'mass_promote':
            self.mass_promote_callback(update, context)
        elif data == 'check_missing_roles':
            self.check_missing_roles_callback(update, context)
        
        # Кик подтверждение
        elif data.startswith('kick_confirm_'):
            player_tag = data.replace('kick_confirm_', '')
            self.confirm_kick_callback(query, context, player_tag)
        elif data == 'kick_cancel':
            query.edit_message_text("❌ Исключение отменено.")
        
        # Настройки
        elif data == 'settings_menu':
            query.edit_message_text("⚙️ *Настройки*\n\nЭта функция в разработке...", parse_mode=ParseMode.MARKDOWN)
        elif data == 'show_buttons':
            query.edit_message_text(
                "📱 *Кнопки управления*\n\n"
                "Бот поддерживает интерактивные кнопки:\n"
                "• В личном чате - полное меню\n"
                "• В группе - основные команды\n"
                "• В войне - статус атак\n"
                "• Для админов - панель управления",
                parse_mode=ParseMode.MARKDOWN
            )
        
        else:
            query.edit_message_text(f"ℹ️ Команда `{data}` в разработке...", parse_mode=ParseMode.MARKDOWN)
    
    def confirm_kick_callback(self, query, context, player_tag):
        user_id = query.from_user.id
        if not self.is_admin(user_id):
            query.answer("❌ Нет прав", show_alert=True)
            return
        
        player_info = api.get_player_info(player_tag)
        if not player_info:
            query.edit_message_text("❌ Игрок не найден.")
            return
        
        player_name = player_info.get('name')
        
        query.edit_message_text(
            f"✅ *Игрок отмечен для исключения*\n\n"
            f"*Имя:* {player_name}\n"
            f"*Тег:* {player_tag}\n\n"
            f"⚠️ *Внимание:* API SuperCell не позволяет исключать игроков автоматически.\n"
            f"Пожалуйста, исключите игрока вручную через игру.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # ============ CALLBACK VERSIONS OF BASIC METHODS ============
    
    def start_callback(self, update: Update, context: CallbackContext):
        """Callback версия start"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                ),
                bot=self.updater.bot
            )
        )
        
        # Вызываем оригинальный метод
        self.start(fake_update, context)
    
    def help_callback(self, update: Update, context: CallbackContext):
        """Callback версия help"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                ),
                bot=self.updater.bot
            )
        )
        
        # Вызываем оригинальный метод
        self.help_command(fake_update, context)
    
    def register_callback(self, update: Update, context: CallbackContext):
        """Callback версия register"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                ),
                bot=self.updater.bot
            )
        )
        
        # Вызываем оригинальный метод
        self.register(fake_update, context)
    
    def stats_callback(self, update: Update, context: CallbackContext):
        """Callback версия stats"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                ),
                bot=self.updater.bot
            )
        )
        
        # Вызываем оригинальный метод
        self.stats(fake_update, context)
    
    def clan_info_callback(self, update: Update, context: CallbackContext):
        """Callback версия clan_info"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                ),
                bot=self.updater.bot
            )
        )
        
        # Вызываем оригинальный метод
        self.clan_info(fake_update, context)
    
    def war_info_callback(self, update: Update, context: CallbackContext):
        """Callback версия war_info"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                ),
                bot=self.updater.bot
            )
        )
        
        # Вызываем оригинальный метод
        self.war_info(fake_update, context)
    
    def war_attacks_callback(self, update: Update, context: CallbackContext):
        """Callback версия war_attacks"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                )
            )
        )
        
        # Вызываем оригинальный метод
        self.war_attacks(fake_update, context)
    
    def top_players_callback(self, update: Update, context: CallbackContext):
        """Callback версия top_players"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                )
            )
        )
        
        # Вызываем оригинальный метод
        self.top_players(fake_update, context)
    
    def check_inactive_callback(self, update: Update, context: CallbackContext):
        """Callback версия check_inactive"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                )
            )
        )
        
        # Вызываем оригинальный метод
        self.check_inactive(fake_update, context)
    
    def show_rules_callback(self, update: Update, context: CallbackContext):
        """Callback версия show_rules"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                )
            )
        )
        
        # Вызываем оригинальный метод
        self.show_rules(fake_update, context)
    
    def show_chests_callback(self, update: Update, context: CallbackContext):
        """Callback версия show_chests"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                )
            )
        )
        
        # Вызываем оригинальный метод
        self.show_chests(fake_update, context)
    
    def show_battles_callback(self, update: Update, context: CallbackContext):
        """Callback версия show_battles"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                )
            )
        )
        
        # Вызываем оригинальный метод
        self.show_battles(fake_update, context)
    
    def show_members_callback(self, update: Update, context: CallbackContext):
        """Callback версия show_members"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                )
            )
        )
        
        # Вызываем оригинальный метод
        self.show_members(fake_update, context)
    
    def show_donations_callback(self, update: Update, context: CallbackContext):
        """Callback версия show_donations"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                )
            )
        )
        
        # Вызываем оригинальный метод
        self.show_donations(fake_update, context)
    
    def sync_me_callback(self, update: Update, context: CallbackContext):
        """Callback версия sync_me"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                )
            )
        )
        
        # Вызываем оригинальный метод
        self.sync_me(fake_update, context)
    
    def update_nickname_callback(self, update: Update, context: CallbackContext):
        """Callback версия update_nickname"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                )
            )
        )
        
        # Вызываем оригинальный метод
        self.update_nickname(fake_update, context)
    
    def admin_panel_callback(self, update: Update, context: CallbackContext):
        """Callback версия admin_panel"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                ),
                bot=self.updater.bot
            )
        )
        
        # Вызываем оригинальный метод
        self.admin_panel(fake_update, context)
    
    def chat_settings_callback(self, update: Update, context: CallbackContext):
        """Callback версия chat_settings"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                ),
                bot=self.updater.bot
            )
        )
        
        # Вызываем оригинальный метод
        self.chat_settings(fake_update, context)
    
    def remind_war_callback(self, update: Update, context: CallbackContext):
        """Callback версия remind_war"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                ),
                bot=self.updater.bot
            )
        )
        
        # Вызываем оригинальный метод
        self.remind_war(fake_update, context)
    
    def manual_river_check_callback(self, update: Update, context: CallbackContext):
        """Callback версия manual_river_check"""
        query = update.callback_query
        query.answer()
        
        # Создаем искусственный update с сообщением
        from telegram import Message, Chat, User
        
        fake_update = Update(
            update_id=update.update_id,
            message=Message(
                message_id=query.message.message_id,
                date=query.message.date,
                chat=Chat(
                    id=query.message.chat.id,
                    type=query.message.chat.type,
                    title=query.message.chat.title if hasattr(query.message.chat, 'title') else None
                ),
                from_user=User(
                    id=query.from_user.id,
                    first_name=query.from_user.first_name,
                    is_bot=query.from_user.is_bot,
                    username=query.from_user.username
                ),
                bot=self.updater.bot
            )
        )
        
        # Вызываем оригинальный метод
        self.manual_river_check(fake_update, context)
    
    # ============ SCHEDULER ============
    
    def setup_scheduler(self):
        """Setup scheduled tasks"""
        timezone = pytz.timezone('Europe/Moscow')
        
        # War reminder at 18:00
        scheduler.add_job(
            self.auto_war_reminder,
            CronTrigger(hour=18, minute=0, timezone=timezone),
            id='war_reminder'
        )
        
        # Daily report at 10:00
        scheduler.add_job(
            self.daily_report,
            CronTrigger(hour=10, minute=0, timezone=timezone),
            id='daily_report'
        )
        
        # Inactive check every 6 hours
        scheduler.add_job(
            self.auto_inactive_check,
            'interval',
            hours=6,
            timezone=timezone,
            id='auto_inactive_check'
        )
        
        # Ежедневная проверка ролей
        scheduler.add_job(
            self.auto_role_check,
            CronTrigger(hour=9, minute=0, timezone=timezone),
            id='auto_role_check'
        )

        # War Day alert every 30 minutes
        scheduler.add_job(
            self.send_war_day_alert,
            'interval',
            minutes=30,
            timezone=timezone,
            id='war_day_alert'
        )

        scheduler.start()
        logger.info("Scheduler started")
    
    def auto_war_reminder(self):
        """Auto war reminder for river race"""
        if not Config.WAR_REMINDER_ENABLED or not Config.GROUP_CHAT_ID:
            return
        
        # ИСПРАВЛЕНО: используем get_current_river_race
        river_race = api.get_current_river_race(Config.CLAN_TAG)
        
        if not river_race:
            return
        
        state = river_race.get('state', 'unknown')
        
        # Проверяем, активна ли гонка
        if state in ['FULL', 'ENDED', 'MATCHMAKING', 'CLAN_NOT_FOUND', 'ACCESS_DENIED']:
            return
        
        reminder_text = """⚔️ *АВТОМАТИЧЕСКОЕ НАПОМИНАНИЕ О РЕЧНОЙ ГОНКЕ!*

Не забудьте сделать свои атаки сегодня!

Удачи в битве! 🏆"""
        
        try:
            self.updater.bot.send_message(
                chat_id=Config.GROUP_CHAT_ID,
                text=reminder_text,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"War reminder sent to chat {Config.GROUP_CHAT_ID}")
        except Exception as e:
            logger.error(f"Failed to send war reminder: {e}")
    
    def daily_report(self):
        """Daily clan report"""
        if not Config.GROUP_CHAT_ID:
            return
        
        try:
            clan_data = api.get_clan_info(Config.CLAN_TAG)
            if not clan_data:
                return
            
            report = "📊 *ЕЖЕДНЕВНЫЙ ОТЧЕТ КЛАНА*\n\n"
            report += f"🏰 *{clan_data.get('name')}*\n"
            report += f"👥 Участников: {clan_data.get('members')}/50\n"
            report += f"🏆 Трофеи клана: {clan_data.get('clanScore'):,}\n"
            report += f"⚔️ Трофеи войн: {clan_data.get('clanWarTrophies', 0):,}\n\n"
            
            # Проверяем речную гонку
            river_race = api.get_current_river_race(Config.CLAN_TAG)
            if river_race:
                state = river_race.get('state', 'unknown')
                period_type = river_race.get('periodType', 'UNKNOWN')
                
                if state not in ['FULL', 'ENDED', 'MATCHMAKING']:
                    if period_type == 'WAR_DAY':
                        report += "⚔️ *СЕГОДНЯ ДЕНЬ БИТВЫ В РЕЧНОЙ ГОНКЕ!*\n"
                        report += "Не забудьте сделать свои атаки! 💪"
                    elif period_type == 'COLOSSEUM':
                        report += "🏟️ *СЕГОДНЯ КОЛИЗЕЙ!*\n"
                        report += "Финальный этап - покажите всё, на что способны! 💪"
                    else:
                        report += "🎮 Участвуйте в речных гонках, донируйте карты, развивайтесь! 💪"
                else:
                    report += "🎮 Участвуйте в речных гонках, донируйте карты, развивайтесь! 💪"
            else:
                report += "🎮 Участвуйте в речных гонках, донируйте карты, развивайтесь! 💪"
            
            self.updater.bot.send_message(
                chat_id=Config.GROUP_CHAT_ID,
                text=report,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"Error sending daily report: {e}")
    
    def auto_inactive_check(self):
        """Auto inactive players check"""
        if not Config.AUTO_KICK_ENABLED or not Config.GROUP_CHAT_ID:
            return
        
        clan_members = api.get_clan_members(Config.CLAN_TAG)
        if not clan_members:
            return
        
        inactive_players = []
        current_time = datetime.now()
        
        for member in clan_members:
            last_seen = member.get('lastSeen')
            if last_seen:
                try:
                    last_seen_date = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                    days_inactive = (current_time - last_seen_date).days
                    
                    if days_inactive >= Config.KICK_AFTER_DAYS:
                        role = member.get('role', 'member')
                        if role not in ['leader', 'coLeader']:
                            inactive_players.append({
                                'name': member.get('name'),
                                'tag': member.get('tag'),
                                'days': days_inactive
                            })
                except:
                    continue
        
        if inactive_players and Config.GROUP_CHAT_ID:
            players_list = "\n".join(
                [f"• {p['name']} ({p['days']} дней)" for p in inactive_players[:5]]
            )
            
            if len(inactive_players) > 5:
                players_list += f"\n• ... и еще {len(inactive_players) - 5} игроков"
            
            warning_text = (
                f"⚠️ *АВТОМАТИЧЕСКАЯ ПРОВЕРКА АКТИВНОСТИ*\n\n"
                f"Следующие игроки неактивны в течение {Config.KICK_AFTER_DAYS} дней:\n\n"
                f"{players_list}\n\n"
                f"Если активность не возобновится, они будут исключены из клана."
            )
            
            try:
                self.updater.bot.send_message(
                    chat_id=Config.GROUP_CHAT_ID,
                    text=warning_text,
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info(f"Inactive warning sent for {len(inactive_players)} players")
            except Exception as e:
                logger.error(f"Failed to send inactive warning: {e}")
    
    def auto_role_check(self):
        """Автоматическая проверка и назначение ролей"""
        if not Config.GROUP_CHAT_ID:
            return
        
        try:
            users = db.get_all_users()
            
            for user in users:
                try:
                    telegram_id = user['telegram_id']
                    cr_tag = user.get('cr_tag')
                    
                    if not cr_tag:
                        continue
                    
                    # Проверяем статус пользователя в группе
                    chat_member = self.updater.bot.get_chat_member(Config.GROUP_CHAT_ID, telegram_id)
                    
                    # Если пользователь в группе, но не админ - назначаем права
                    if chat_member.status not in ['administrator', 'creator', 'left', 'kicked']:
                        # Получаем данные игрока
                        player_data = api.get_player_info(cr_tag)
                        if player_data:
                            player_name = player_data.get('name', '')
                            current_role = nickname_manager.get_clan_role(cr_tag) or 'member'
                            
                            if player_name:
                                # Назначаем права администратора
                                success, result_text = self.promote_to_admin(
                                    self.updater.bot,
                                    Config.GROUP_CHAT_ID,
                                    telegram_id,
                                    player_name,
                                    current_role
                                )
                                
                                if success:
                                    logger.info(f"Auto-assigned role to {telegram_id}: {current_role}")
                                
                except Exception as e:
                    logger.error(f"Error in auto role check for user {user.get('telegram_id')}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Auto role check failed: {e}")
    
    # ============ NEW API COMMANDS ============
    
    def show_war_log(self, update: Update, context: CallbackContext):
        """Показать историю войн клана"""
        if not self.is_group_chat(update):
            update.message.reply_text("❌ Эта команда доступна только в групповом чате.")
            return
        
        war_log = api.get_war_log(Config.CLAN_TAG, limit=5)
        if not war_log:
            update.message.reply_text("❌ Не удалось получить историю войн.")
            return
        
        text = "📜 *История войн клана:*\n\n"
        for entry in war_log.get('items', []):
            season = entry.get('seasonId', 'N/A')
            text += f"🏆 Сезон {season}\n"
            for standing in entry.get('standings', []):
                clan = standing.get('clan', {})
                if clan.get('tag') == Config.CLAN_TAG:
                    text += f"  • Место: {standing.get('rank', 'N/A')}\n"
                    text += f"  • Трофеи: {standing.get('trophyChange', 0)}\n"
                    break
            text += "\n"
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    def show_river_race(self, update: Update, context: CallbackContext):
        """Показать текущую речную гонку"""
        if not self.is_group_chat(update):
            update.message.reply_text("❌ Эта команда доступна только в групповом чате.")
            return
        
        race = api.get_current_river_race(Config.CLAN_TAG)
        if not race:
            update.message.reply_text("❌ Не удалось получить данные о речной гонке.")
            return
        
        clan_data = race.get('clan', {})
        participants = clan_data.get('participants', [])
        clans = race.get('clans', [])
        
        text = f"🏞️ *Речная гонка: {clan_data.get('name', 'N/A')}*\n\n"
        text += f"🏆 Очки клана: {clan_data.get('clanScore', 0)}\n"
        text += f"💎 Фейм: {clan_data.get('fame', 0)}\n"
        text += f"🔧 Ремонт: {clan_data.get('repairPoints', 0)}\n\n"
        
        # Участники клана
        text += "👥 *Участники клана:*\n"
        for p in participants[:10]:  # Ограничим до 10 для читаемости
            text += f"• {p.get('name', 'N/A')}: {p.get('boatAttacks', 0)} атак, {p.get('fame', 0)} фейм\n"
        if len(participants) > 10:
            text += f"... и ещё {len(participants) - 10} участников\n"
        text += "\n"
        
        # Другие кланы
        text += "🏰 *Другие кланы в гонке:*\n"
        for c in clans[:5]:  # Топ 5 других кланов
            if c.get('tag') != Config.CLAN_TAG:
                text += f"• {c.get('name', 'N/A')}: {c.get('clanScore', 0)} очков, {c.get('fame', 0)} фейм\n"
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    def search_tournaments(self, update: Update, context: CallbackContext):
        """Поиск турниров"""
        name = ' '.join(context.args) if context.args else None
        tournaments = api.search_tournaments(name=name, limit=5)
        if not tournaments:
            update.message.reply_text("❌ Не удалось найти турниры.")
            return
        
        text = "🏆 *Найденные турниры:*\n\n"
        for t in tournaments.get('items', []):
            text += f"• {t.get('name', 'N/A')} (#{t.get('tag', 'N/A')})\n"
            text += f"  Статус: {t.get('status', 'N/A')}\n\n"
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    # ============ RIVER RACE NOTIFICATIONS ============
    
    def check_river_race_period(self):
        """Проверка периода речной гонки и отправка уведомлений"""
        try:
            race = api.get_current_river_race(Config.CLAN_TAG)
            if not race:
                return
            
            period_type = race.get('periodType', '')
            period_index = race.get('periodIndex', 0)
            section_index = race.get('sectionIndex', 0)
            
            # Проверяем, изменился ли период
            last_period = getattr(self, 'last_river_period', None)
            current_period = f"{period_type}_{period_index}_{section_index}"
            
            if last_period != current_period:
                self.last_river_period = current_period
                self.send_river_notification(race, period_type)
            
            # Проверяем невыполненные атаки (каждые 2 часа)
            now = datetime.now()
            last_attack_check = getattr(self, 'last_attack_check', None)
            if not last_attack_check or (now - last_attack_check).seconds > 7200:  # 2 часа
                self.last_attack_check = now
                self.check_missing_attacks(race)
                
        except Exception as e:
            logger.error(f"Error checking river race period: {e}")
    
    def send_river_notification(self, race, period_type):
        """Отправка уведомления о новом периоде"""
        try:
            if not Config.GROUP_CHAT_ID:
                return
            
            clan_data = race.get('clan', {})
            period_messages = {
                'TRAINING': "🏋️ *Дни тренировки начались!*\n\nПодготовьтесь к речной гонке. Практикуйте атаки и стройте лодки.",
                'WAR_DAY': "⚔️ *Дни сражений начались!*\n\nВремя атаковать! Каждый участник должен сделать максимум атак.",
                'COLOSSEUM': "🏟️ *Колизей открыт!*\n\nСпециальные бои в Колизее. Покажите свою силу!"
            }
            
            message = period_messages.get(period_type, f"🏞️ *Новый период речной гонки: {period_type}*")
            message += f"\n\n🏆 Клан: {clan_data.get('name', 'N/A')}\n💎 Фейм: {clan_data.get('fame', 0)}"
            
            self.updater.bot.send_message(
                chat_id=Config.GROUP_CHAT_ID,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"Error sending river notification: {e}")
    
    def check_missing_attacks(self, race):
        """Проверка игроков без атак"""
        try:
            if not Config.GROUP_CHAT_ID:
                return
            
            clan_data = race.get('clan', {})
            participants = clan_data.get('participants', [])
            
            # Ожидаемое количество атак (зависит от периода, но для простоты 4)
            expected_attacks = 4
            missing_players = []
            
            for p in participants:
                attacks = p.get('boatAttacks', 0)
                if attacks < expected_attacks:
                    missing_players.append({
                        'name': p.get('name', 'N/A'),
                        'attacks': attacks,
                        'missing': expected_attacks - attacks
                    })
            
            if missing_players:
                message = "⚠️ *Игроки без полных атак в речной гонке:*\n\n"
                for player in missing_players[:10]:  # Топ 10
                    message += f"• {player['name']}: {player['attacks']}/{expected_attacks} атак (не хватает {player['missing']})\n"
                
                if len(missing_players) > 10:
                    message += f"\n... и ещё {len(missing_players) - 10} игроков"
                
                self.updater.bot.send_message(
                    chat_id=Config.GROUP_CHAT_ID,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN
                )
                
        except Exception as e:
            logger.error(f"Error checking missing attacks: {e}")
    
    def manual_river_check(self, update, context):
        """Ручная проверка речной гонки"""
        try:
            if not self.is_admin(update.effective_user.id):
                update.message.reply_text("❌ Эта команда доступна только админам.")
                return
            
            update.message.reply_text("🔍 Проверяю речную гонку...")

            # Получаем данные речной гонки
            race = api.get_river_race_log(Config.CLAN_TAG)
            if not race:
                update.message.reply_text("❌ Не удалось получить данные речной гонки.")
                return
            
            # Проверяем период
            self.check_river_race_period(race)
            
            # Проверяем пропущенные атаки
            self.check_missing_attacks(race)
            
            update.message.reply_text("✅ Проверка завершена. Уведомления отправлены в групповой чат.")
            
        except Exception as e:
            logger.error(f"Error in manual river check: {e}")
            update.message.reply_text("❌ Ошибка при проверке речной гонки.")

    def send_war_day_alert(self):
        """Отправить alert когда началась War Day"""
        try:
            war = api.get_current_war(Config.CLAN_TAG)

            if not war or war.get('state') != 'WAR_DAY':
                return

            clan_members = api.get_clan_members(Config.CLAN_TAG)
            alert = api.format_war_day_alert(war, clan_members)

            if not alert:
                return

            # Формируем текст
            text = "⚔️ *WAR DAY НАЧАЛСЯ!*\n\n"

            # Время
            try:
                from dateutil import parser as date_parser
                end_time = date_parser.isoparse(alert['time_remaining'])
                remaining = (end_time - datetime.now(pytz.UTC)).total_seconds()
                if remaining > 0:
                    hours = int(remaining // 3600)
                    minutes = int((remaining % 3600) // 60)
                    text += f"⏱️ Осталось: {hours}ч {minutes}м\n\n"
            except:
                pass

            # Прогресс
            text += "📊 *ПРОГРЕСС:*\n"
            text += f"  • Место: {alert['place']} из 8 кланов\n"
            text += f"  • Наши очки: {alert['clan_score']}\n"
            text += f"  • Участников: {alert['participants']}\n\n"

            # НЕ АТАКОВАЛИ (0 боев)
            if alert['not_attacked']:
                names = [p.get('name', '?') for p in alert['not_attacked'][:5]]
                text += f"⚠️ *НЕ АТАКОВАЛИ В КВ* (0 боев):\n"
                text += f"  {' '.join(names)}\n\n"

            # НЕ ДОНАТЯТ
            if alert['not_donating']:
                names = [m.get('name', '?') for m in alert['not_donating'][:5]]
                text += f"💰 *НЕ ДОНАТЯТ КАРТЫ:*\n"
                text += f"  {' '.join(names)}\n\n"

            text += "💪 Давайте на finish!"

            self.dispatcher.bot.send_message(
                chat_id=Config.GROUP_CHAT_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error in send_war_day_alert: {e}")

    def show_donations_full(self, update: Update, context: CallbackContext):
        """Показать полную статистику донатов всех игроков"""
        try:
            donations_data = api.format_donations_full(Config.CLAN_TAG)

            if not donations_data:
                update.message.reply_text("❌ Не удалось получить статистику")
                return

            # Если много игроков (> 20), отправляем с пагинацией
            if donations_data['count'] > 20:
                self._send_donations_paginated(update, donations_data)
            else:
                text = self._format_donations_table(donations_data)
                update.message.reply_text(text, parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.error(f"Error in show_donations_full: {e}")
            update.message.reply_text("❌ Ошибка при получении данных")

    def _format_donations_table(self, donations_data):
        """Форматировать таблицу донатов"""
        text = "🎁 *ПОЛНАЯ СТАТИСТИКА ДОНАТОВ КЛАНА*\n\n"
        text += "<pre>"
        text += "Ранг | Имя           | Пожертв. | Получ. | Баланс | %\n"
        text += "─────┼───────────────┼──────────┼────────┼────────┼─────\n"

        for i, member in enumerate(donations_data['members'], 1):
            name = member.get('name', 'Unknown')[:13]
            donated = member.get('donations', 0)
            received = member.get('donationsReceived', 0)
            balance = donated - received
            percent = (donated / donations_data['total_donations'] * 100) if donations_data['total_donations'] > 0 else 0

            text += f"{i:3} | {name:13} | {donated:8} | {received:6} | {balance:+6} | {percent:4.1f}%\n"

        text += "</pre>\n\n"
        text += f"📊 *СВОДКА:*\n"
        text += f"• Всего пожертвовано: {donations_data['total_donations']:,} карт\n"
        text += f"• Всего получено: {donations_data['total_received']:,} карт\n"
        text += f"• Среднее на игрока: {donations_data['average_donations']:,} / {donations_data['average_received']:,}\n"

        return text

    def _send_donations_paginated(self, update, donations_data):
        """Отправить таблицу пагинацией (по 15 игроков)"""
        PAGE_SIZE = 15
        members = donations_data['members']
        total_pages = (len(members) + PAGE_SIZE - 1) // PAGE_SIZE

        for page in range(total_pages):
            start = page * PAGE_SIZE
            end = min(start + PAGE_SIZE, len(members))

            text = f"🎁 *СТАТИСТИКА ДОНАТОВ* (страница {page+1}/{total_pages})\n\n"
            text += "<pre>"
            text += "Ранг | Имя           | Пожертв. | Получ. | Баланс | %\n"
            text += "─────┼───────────────┼──────────┼────────┼────────┼─────\n"

            for i in range(start, end):
                member = members[i]
                name = member.get('name', 'Unknown')[:13]
                donated = member.get('donations', 0)
                received = member.get('donationsReceived', 0)
                balance = donated - received
                percent = (donated / donations_data['total_donations'] * 100) if donations_data['total_donations'] > 0 else 0

                text += f"{i+1:3} | {name:13} | {donated:8} | {received:6} | {balance:+6} | {percent:4.1f}%\n"

            text += "</pre>\n"
            update.message.reply_text(text, parse_mode=ParseMode.HTML)

    def show_war_stats(self, update: Update, context: CallbackContext):
        """Показать рейтинг участников войны"""
        war_data = api.get_current_war(Config.CLAN_TAG)
        if not war_data:
            update.message.reply_text("❌ Нет текущей войны")
            return

        stats = api.format_war_stats(war_data)
        if not stats:
            update.message.reply_text("❌ Нет данных")
            return

        text = "🏆 *СТАТИСТИКА ВОЙНЫ:*\n\n"

        for i, p in enumerate(stats['participants'], 1):
            name = p.get('name', '?')
            score = p.get('cardsEarned', 0)
            battles = p.get('battlesPlayed', 0)
            wins = p.get('wins', 0)
            total = p.get('numberOfBattles', battles) if battles else 1
            percent = (battles / total * 100) if total > 0 else 0

            text += f"{i}. {name} | {score} очков | {battles}/{total} ({percent:.0f}%)\n"

        text += f"\n📊 Всего очков: {stats['total_score']}"

        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    def run(self):
        """Run the bot"""
        logger.info("Bot starting...")
        
        try:
            if self.webhook_url:
                logger.info(f"Bot running with webhook on {self.webhook_url}")
                self.updater.idle()
            else:
                logger.info("Bot running with polling")
                self.updater.idle()
        except Exception as e:
            if "Conflict" in str(e) or "terminated by other getUpdates request" in str(e):
                logger.warning("⚠️ Bot instance conflict detected. Another instance may be running.")
                logger.warning("If this is unexpected, stop other instances and restart.")
            else:
                logger.error(f"Unexpected error in bot run: {e}")
            raise

def main():
    """Main function"""
    # Check required environment variables
    required_vars = ['BOT_TOKEN', 'CR_API_TOKEN', 'ADMIN_TAG', 'CLAN_TAG']
    
    for var in required_vars:
        if not getattr(Config, var, None):
            logger.error(f"❌ Missing required environment variable: {var}")
            logger.error("Please check your .env file or Railway environment variables")
            return
    
    logger.info("✅ All required environment variables are set")
    logger.info(f"Clan tag: {Config.CLAN_TAG}")
    logger.info(f"Admin tag: {Config.ADMIN_TAG}")
    
    # Create and run bot
    try:
        bot = ClanBot(Config.BOT_TOKEN, Config.WEBHOOK_URL)
        logger.info("Bot started successfully!")
        bot.run()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

if __name__ == '__main__':
    main()